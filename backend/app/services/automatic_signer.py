"""Independent custody service: requests contain only a persisted task ID.

Run as a separate user/container with vault mounts unavailable to API/worker.
"""
import hmac
from datetime import datetime, timezone
import json

from fastapi import FastAPI, Depends, Header, HTTPException
from sqlalchemy import select, func
from eth_utils import to_checksum_address

from app.api.deps import get_db
from app.config import settings
from app.models import MintTask, MintAuthorization, AutomaticGrant, AutomaticNonce, Wallet, User
from app.services import automatic
from app.services.custody import CustodyVault, private_read
from app.services.custody_accounts import verify_account
from app.services.automatic_fees import quote_gas
from app.services.mint_plans import aware
from app.services.opensea import OpenSeaUnavailable

app = FastAPI(title='Mintly isolated custody signer', docs_url=None, redoc_url=None, openapi_url=None)


def authenticate(authorization: str | None = Header(default=None)):
    try:
        token = private_read(settings.AUTOMATIC_SIGNER_TOKEN_FILE)
        if len(token) < 32 or not hmac.compare_digest(authorization or '', 'Bearer ' + token):
            raise ValueError()
    except Exception:
        raise HTTPException(401, 'Signer authentication required.') from None


async def final_receipt(web3, tx_hash):
    from web3.exceptions import TransactionNotFound
    try:
        receipt = await web3.eth.get_transaction_receipt(tx_hash)
    except TransactionNotFound:
        return None
    block = await web3.eth.get_block(receipt.blockNumber)
    if block.hash != receipt.blockHash or await web3.eth.block_number - receipt.blockNumber + 1 < max(2, settings.AUTOMATIC_CONFIRMATIONS):
        return None
    if settings.AUTOMATIC_CHAIN_ID in (11155111, 4663):
        finalized = await web3.eth.get_block('finalized')
        if finalized.number < receipt.blockNumber:
            return None
    return receipt


async def prepare_task(db, task_id, vault=None):
    """Idempotent signing under the same DB lock used by cancellation and arming."""
    automatic.enabled()
    await automatic.lock_execution(db)
    task = (await db.execute(select(MintTask).where(MintTask.id == task_id).execution_options(populate_existing=True))).scalar_one_or_none()
    if not task or task.execution_mode != automatic.MODE:
        raise ValueError('Automatic task not found')
    if task.signed_tx_raw:
        return {'task_id': task.id, 'status': task.status, 'hash': task.transaction_hash}
    if task.status not in ('armed', 'preparing'):
        raise ValueError('Task is cancelled or already terminal')
    auth = await db.get(MintAuthorization, task.authorization_id)
    s = auth.snapshot
    grant = await automatic.grant_for(db, auth.grant_id, s['user_id'])
    wallet = await db.get(Wallet, task.wallet_id)
    user = await db.get(User, grant.user_id)
    if (auth.is_revoked or not user or not user.is_active or user.deleted_at
            or not wallet or wallet.user_id != grant.user_id or wallet.id != grant.wallet_id
            or wallet.address.lower() != grant.account.lower() or auth.wallet_id != wallet.id
            or s['account'].lower() != wallet.address.lower() or s['recipient'].lower() != wallet.address.lower()
            or task.stage_id != auth.stage_id or task.drop_id != auth.drop_id
            or s['stage_id'] != auth.stage_id or s['drop_id'] != auth.drop_id
            or s['chain_id'] != grant.chain_id or s['quantity'] != auth.quantity
            or (s['price_cap_wei'], s['fee_cap_wei'], s['total_cap_wei']) !=
                (auth.max_price_per_token_wei, auth.max_fee_wei, auth.total_spend_cap_wei)
            or s['expiry'] != int(aware(task.expires_at_utc).timestamp())):
        raise ValueError('Authorization ownership, account or task scope mismatch')
    vault = vault or CustodyVault()
    policy = vault.policy(grant)
    if (not automatic.allows_collection(policy, s['contract'])
            or s['mint_kind'] not in policy['mint_kinds'] or s['expiry'] > policy['expires_at']
            or not 0 < s['total_cap_wei'] <= policy['max_task_wei']
            or not 0 < s['fee_cap_wei'] <= s['total_cap_wei']
            or not 1 <= s['quantity'] <= 100 or not 0 <= s['price_wei'] <= s['price_cap_wei']):
        raise ValueError('Independent signer policy limits exceeded')
    web3 = await automatic.provider()
    journal = vault.journal()
    try:
        block = await web3.eth.get_block('latest')
        now = max(int(datetime.now(timezone.utc).timestamp()), block.timestamp)
        if now >= min(s['expiry'], policy['expires_at']):
            raise ValueError('Task or signer policy expired')
        if block.timestamp < s['start']:
            return {'task_id': task.id, 'status': 'armed', 'note': 'Waiting for chain time.'}
        await verify_account(web3, policy)
        intent = automatic.digest({'snapshot': s, 'policy': grant.context_hash})
        previous = journal.execute('SELECT * FROM signed WHERE task=?', (task.id,)).fetchone()
        if previous:
            if previous['intent'] != intent:
                raise ValueError('Attempt to change a previously signed task')
            raw, tx_hash, nonce = previous['raw'], previous['hash'], previous['nonce']
        else:
            # Independently reconcile the signer's lifetime budget; API DB edits cannot reset it.
            for entry in journal.execute('SELECT * FROM signed WHERE policy=? AND actual IS NULL', (grant.id,)).fetchall():
                receipt = await final_receipt(web3, entry['hash'])
                if receipt:
                    tx = await web3.eth.get_transaction(entry['hash'])
                    actual = receipt.gasUsed * receipt.effectiveGasPrice + (tx.value if receipt.status == 1 else 0)
                    journal.execute('UPDATE signed SET actual=? WHERE task=?', (actual, entry['task']))
            journal.commit()
            charged = journal.execute('SELECT COALESCE(SUM(COALESCE(actual,liability)),0) FROM signed WHERE policy=?', (grant.id,)).fetchone()[0]
            if charged + s['total_cap_wei'] > policy['budget_wei']:
                raise ValueError('Independent signer budget exhausted or reserved by uncertain submissions')
            execution = s.get('execution')
            if execution:
                await automatic.validate_mint(web3, s, {'to': execution['target'], 'value': execution['value'], 'data': execution['data']})
            else:
                execution = await automatic.prepare_mint(web3, s)
            address = to_checksum_address(s['account'])
            pending = await web3.eth.get_transaction_count(address, 'pending')
            stored = (await db.execute(select(func.max(AutomaticNonce.nonce)).where(
                AutomaticNonce.address == address.lower(), AutomaticNonce.chain_id == s['chain_id']))).scalar()
            signed_max = journal.execute('SELECT MAX(nonce) FROM signed WHERE address=? AND chain=?', (address.lower(), s['chain_id'])).fetchone()[0]
            nonce = max(pending, (stored + 1) if stored is not None else 0, (signed_max + 1) if signed_max is not None else 0)
            # A missing pending nonce indicates a prior signed submission has not propagated.
            # Do not place more mints behind an uncertain gap.
            if nonce > pending:
                return {'task_id': task.id, 'status': 'armed', 'note': 'Waiting for the prior reserved wallet nonce.'}
            tx = {'from': address, 'to': execution['target'], 'data': execution['data'],
                'value': int(execution['value']), 'chainId': s['chain_id'], 'nonce': nonce}
            gas, gas_price = await quote_gas(web3, tx, s['chain_id'])
            tx['gasPrice'] = gas_price
            if gas * gas_price > s['fee_cap_wei'] or tx['value'] + gas * gas_price > s['total_cap_wei']:
                raise ValueError('Estimated gas or total debit exceeds task authorization')
            if await web3.eth.get_balance(address, 'pending') < tx['value'] + gas * gas_price:
                raise ValueError('Insufficient funds for mint value and gas')
            await web3.eth.call(tx, 'pending')
            tx['gas'] = gas
            # Recheck wall time after network preparation, immediately before using the key.
            if int(datetime.now(timezone.utc).timestamp()) >= s['expiry']:
                raise ValueError('Task expired during preparation')
            await verify_account(web3, policy)
            account = vault.account(policy)
            signed = account.sign_transaction(tx)
            del account
            raw, tx_hash = '0x' + bytes(signed.raw_transaction).hex(), '0x' + bytes(signed.hash).hex()
            journal.execute('INSERT INTO signed(task,policy,intent,address,chain,nonce,liability,raw,hash) VALUES(?,?,?,?,?,?,?,?,?)',
                (task.id, grant.id, intent, address.lower(), s['chain_id'], nonce, s['total_cap_wei'], raw, tx_hash))
            journal.commit()  # fsync BEFORE returning or persisting anything broadcastable to the worker
        reservation = await db.get(AutomaticNonce, task.id)
        if not reservation:
            db.add(AutomaticNonce(task_id=task.id, chain_id=s['chain_id'], address=s['account'].lower(), nonce=nonce))
        task.signed_tx_raw, task.transaction_hash, task.assigned_nonce = raw, tx_hash, nonce
        task.status = 'prepared'
        task.failure_reason = None
        task.prepared_calldata = json.dumps(s.get('execution')) if s.get('execution') else None
        await db.commit()  # signed payload and hash durable before scheduler may broadcast
        return {'task_id': task.id, 'status': task.status, 'hash': tx_hash}
    finally:
        journal.close()
        await web3.provider.disconnect()


@app.post('/tasks/{task_id}/prepare', dependencies=[Depends(authenticate)])
async def prepare(task_id: str, db=Depends(get_db)):
    try:
        return await prepare_task(db, task_id)
    except OpenSeaUnavailable as error:
        await db.rollback()
        raise HTTPException(409 if error.status in (400,409,422) else 503,
            'SeaDrop proof or exact-stage validation failed.' if error.status in (400,409,422) else 'Presale provider temporarily unavailable.') from None
    except (ValueError, HTTPException) as error:
        await db.rollback()
        actionable = {'Insufficient funds for mint value and gas', 'Estimated gas or total debit exceeds task authorization',
                      'Task or signer policy expired', 'Public stage changed on chain',
                      'Independent signer budget exhausted or reserved by uncertain submissions'}
        detail = str(error) if str(error) in actionable else 'Independent signer rejected task policy, identity, budget or chain readiness.'
        raise HTTPException(409, detail) from None
    except Exception:
        await db.rollback()
        raise HTTPException(503, 'Signer or RPC temporarily unavailable; no fresh-nonce retry is permitted.') from None


@app.get('/readyz', dependencies=[Depends(authenticate)])
async def ready():
    automatic.enabled()
    vault = CustodyVault()
    private_read(settings.CUSTODY_PASSWORD_FILE)
    journal = vault.journal()
    journal.close()
    web3 = await automatic.provider()
    await web3.provider.disconnect()
    return {'status': 'ready', 'chain_id': settings.AUTOMATIC_CHAIN_ID, 'custodial': True}


@app.get('/policies/{grant_id}/ready', dependencies=[Depends(authenticate)])
async def policy_ready(grant_id: str, db=Depends(get_db)):
    automatic.enabled()
    try:
        grant = await db.get(AutomaticGrant, grant_id)
        if not grant or grant.status != 'enabled' or aware(grant.expires_at) <= datetime.now(timezone.utc):
            raise ValueError()
        vault = CustodyVault()
        policy = vault.policy(grant)
        web3 = await automatic.provider()
        try:
            await verify_account(web3, policy)
        finally:
            await web3.provider.disconnect()
        account = vault.account(policy)
        del account
        return {'status': 'ready', 'policy_id': grant.id, 'account': grant.account}
    except Exception:
        raise HTTPException(409, 'Custodial policy or encrypted keystore is unavailable.') from None
