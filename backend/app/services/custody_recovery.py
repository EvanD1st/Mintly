"""Explicit owner-authorized recovery, invoked only in the isolated signer.

No automatic fee bumps and no new nonce. Old authorization/signature are retained.
"""
import uuid
from datetime import datetime, timezone, timedelta
from eth_account import Account
from eth_account._utils.legacy_transactions import Transaction
from eth_utils import keccak
from sqlalchemy import select
from app.models import MintRecovery, MintTask, MintAuthorization, Wallet, User, ActivityEvent
from app.services import automatic
from app.services.custody import CustodyVault
from app.services.custody_accounts import verify_account
from app.services.automatic_fees import quote_gas
from app.services.mint_plans import aware


async def recover_task(db, task_id, owner_id, expires_at, reference, vault=None):
    """Caller supplies fresh human consent; a stable reference freezes all retries."""
    if not reference or len(reference) > 200:
        raise ValueError('Explicit recovery authorization reference is required')
    automatic.enabled()
    vault = vault or CustodyVault()
    recovery_id = str(uuid.uuid5(uuid.NAMESPACE_URL, task_id + ':' + reference))
    await automatic.lock_execution(db)
    task = await db.get(MintTask, task_id, populate_existing=True)
    if not task or task.execution_mode != automatic.MODE:
        raise ValueError('Automatic task not found')
    auth = await db.get(MintAuthorization, task.authorization_id)
    s = auth.snapshot
    user = await db.get(User, owner_id)
    wallet = await db.get(Wallet, task.wallet_id)
    if (not user or not user.is_active or user.deleted_at or user.must_change_password
            or not wallet or s['user_id'] != owner_id or wallet.user_id != owner_id or auth.is_revoked
            or wallet.id != auth.wallet_id or wallet.address.lower() != s['account'].lower()):
        raise ValueError('Recovery must belong to the active authorizing owner')
    existing = await db.scalar(select(MintRecovery).where(MintRecovery.task_id == task.id))
    if existing:
        if existing.id != recovery_id or existing.user_id != owner_id:
            raise ValueError('Task already has a different recovery authorization')
        if existing.activated_at:
            return {'task_id': task.id, 'recovery_id': existing.id, 'hash': existing.replacement_hash, 'status': existing.status}
        recovery = existing
    else:
        if task.status not in ('prepared', 'submitted', 'uncertain') or not task.signed_tx_raw or task.assigned_nonce is None:
            raise ValueError('Recovery requires an existing signed unresolved task')
        expiry = aware(expires_at)
        now = datetime.now(timezone.utc)
        grant = await automatic.grant_for(db, auth.grant_id, owner_id)
        if not now + timedelta(seconds=30) < expiry <= min(
                datetime.fromtimestamp(s['end'], timezone.utc), aware(grant.expires_at), now + timedelta(minutes=20)):
            raise ValueError('Recovery requires a fresh finite submission window within stage and policy')
        raw = bytes.fromhex(task.signed_tx_raw.removeprefix('0x'))
        if '0x' + keccak(raw).hex() != task.transaction_hash or Account.recover_transaction(raw).lower() != s['account'].lower():
            raise ValueError('Original signature identity or integrity mismatch')
        recovery = MintRecovery(id=recovery_id, task_id=task.id, user_id=owner_id,
            authorization_reference=reference, authorized_at=now, expires_at=expiry,
            attempt_ceiling=task.broadcast_attempts + 2, status='approved',
            snapshot={**s, 'expiry': int(expiry.timestamp()), 'recovery_nonce': task.assigned_nonce},
            previous_hash=task.transaction_hash, previous_signed_tx_raw=task.signed_tx_raw)
        db.add(recovery)
        db.add(ActivityEvent(user_id=owner_id, event_type='recovery_authorized', label='Same-nonce recovery authorized',
            detail=f'{task.id}: nonce {task.assigned_nonce}; same mint and original finite spend caps. {reference}',
            icon_name='gem', is_demo=False))
        await db.commit()  # consent survives a crash; inactive approvals do not extend worker broadcast authority
        await automatic.lock_execution(db)
        task = await db.get(MintTask, task_id, populate_existing=True)
    if task.status in automatic.TERMINAL:
        raise ValueError('Original task already settled; no recovery signed')
    grant = await automatic.grant_for(db, auth.grant_id, owner_id)
    policy = vault.policy(grant)
    if datetime.now(timezone.utc) >= aware(recovery.expires_at):
        raise ValueError('Recovery authorization expired before signing')
    if recovery.snapshot != {**s, 'expiry': int(aware(recovery.expires_at).timestamp()), 'recovery_nonce': task.assigned_nonce}:
        raise ValueError('Recovery scope differs from immutable original authorization')
    original = Transaction.from_bytes(bytes.fromhex(recovery.previous_signed_tx_raw.removeprefix('0x')))
    if (original.nonce != task.assigned_nonce or original.value != s['price_wei'] * s['quantity']
            or (original.v - 35) // 2 != s['chain_id'] or auth.total_spend_cap_wei != s['total_cap_wei']
            or auth.max_fee_wei != s['fee_cap_wei'] or grant.reserved_wei < s['total_cap_wei']):
        raise ValueError('Original nonce or immutable debit bounds differ')
    if (not automatic.allows_collection(policy, s['contract']) or s['mint_kind'] not in policy['mint_kinds']
            or not 0 < s['total_cap_wei'] <= policy['max_task_wei']
            or s['chain_id'] != policy['chain_id'] or s['account'].lower() != policy['account'].lower()):
        raise ValueError('Recovery is outside independently provisioned policy')
    if int(aware(recovery.expires_at).timestamp()) > policy['expires_at']:
        raise ValueError('Recovery outlives signer policy')
    web3 = await automatic.provider()
    journal = vault.journal()
    try:
        from web3.exceptions import TransactionNotFound
        block = await web3.eth.get_block('latest')
        if block.timestamp >= int(aware(recovery.expires_at).timestamp()):
            raise ValueError('Recovery authorization expired on chain before signing')
        for tx_hash in (recovery.previous_hash, recovery.replacement_hash):
            if not tx_hash:
                continue
            try:
                await web3.eth.get_transaction_receipt(tx_hash)
            except TransactionNotFound:
                pass
            else:
                raise ValueError('An existing transaction has a receipt; keep reconciling instead of replacing')
        latest = await web3.eth.get_transaction_count(s['account'], 'latest')
        pending = await web3.eth.get_transaction_count(s['account'], 'pending')
        if latest != original.nonce or pending not in (original.nonce, original.nonce + 1):
            raise ValueError('Nonce was consumed or wallet has unrelated pending activity')
        if pending == original.nonce + 1:
            try:
                known = await web3.eth.get_transaction(recovery.previous_hash)
            except TransactionNotFound:
                raise ValueError('An unrelated pending transaction may own this nonce') from None
            if known.nonce != original.nonce or known['from'].lower() != s['account'].lower():
                raise ValueError('Pending nonce identity mismatch')
        await verify_account(web3, policy)
        intent = automatic.digest({'recovery': recovery.snapshot, 'previous_hash': recovery.previous_hash,
                                   'policy': grant.context_hash})
        old_entry = journal.execute('SELECT * FROM signed WHERE task=?', (task.id,)).fetchone()
        if (not old_entry or old_entry['hash'] != recovery.previous_hash or old_entry['raw'] != recovery.previous_signed_tx_raw
                or old_entry['nonce'] != original.nonce
                or old_entry['policy'] != grant.id or old_entry['liability'] != s['total_cap_wei']
                or old_entry['intent'] != automatic.digest({'snapshot': s, 'policy': grant.context_hash})):
            raise ValueError('Original independent signing journal entry differs')
        saved = journal.execute('SELECT * FROM recoveries WHERE id=?', (recovery.id,)).fetchone()
        if saved:
            if saved['intent'] != intent or saved['nonce'] != original.nonce:
                raise ValueError('Previously signed recovery cannot change')
            raw, tx_hash = saved['raw'], saved['hash']
        else:
            execution = await automatic.prepare_mint(web3, dict(recovery.snapshot))
            if (execution['data'].lower() != ('0x' + original.data.hex()).lower()
                    or execution['target'].lower() != ('0x' + original.to.hex()).lower()):
                raise ValueError('Recovery may not change the original mint calldata or destination')
            tx = {'from': s['account'], 'to': execution['target'], 'data': execution['data'],
                  'value': original.value, 'chainId': s['chain_id'], 'nonce': original.nonce}
            gas, price = await quote_gas(web3, tx, s['chain_id'])
            price = max(price, (original.gasPrice * 1125 + 999) // 1000)
            if gas * price > s['fee_cap_wei'] or original.value + gas * price > s['total_cap_wei']:
                raise ValueError('Recovery fee exceeds the original owner-approved debit ceiling')
            if await web3.eth.get_balance(s['account'], 'pending') < original.value + gas * price:
                raise ValueError('Insufficient funds for bounded recovery')
            tx.update(gas=gas, gasPrice=price)
            await web3.eth.call(tx, 'pending')
            if datetime.now(timezone.utc) >= aware(recovery.expires_at):
                raise ValueError('Recovery authorization expired before signing')
            await verify_account(web3, policy)
            account = vault.account(policy)
            signed = account.sign_transaction(tx)
            del account
            raw, tx_hash = '0x' + bytes(signed.raw_transaction).hex(), '0x' + bytes(signed.hash).hex()
            journal.execute('INSERT INTO recoveries(id,task,intent,nonce,raw,hash) VALUES(?,?,?,?,?,?)',
                            (recovery.id, task.id, intent, original.nonce, raw, tx_hash))
            journal.commit()  # fsync before worker-visible activation; lifetime liability remains charged once
        recovery.replacement_signed_tx_raw, recovery.replacement_hash = raw, tx_hash
        recovery.activated_at, recovery.status = datetime.now(timezone.utc), 'prepared'
        task.signed_tx_raw, task.transaction_hash = raw, tx_hash
        task.status, task.failure_reason, task.next_attempt_at = 'prepared', None, None
        db.add(ActivityEvent(user_id=owner_id, event_type='recovery_prepared', label='Same-nonce recovery prepared',
            detail=f'{task.id}: {recovery.previous_hash} → {tx_hash}; no new nonce or additional budget reservation.',
            is_demo=False, icon_name='gem'))
        await db.commit()
        return {'task_id': task.id, 'recovery_id': recovery.id, 'hash': tx_hash, 'nonce': original.nonce, 'status': 'prepared'}
    finally:
        journal.close()
        await web3.provider.disconnect()
