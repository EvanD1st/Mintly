"""Independent custody service: requests contain only a persisted task ID.

Run as a separate user/container with vault mounts unavailable to API/worker.
"""
import hmac
import copy
import time
from datetime import datetime, timezone
import json

from fastapi import FastAPI, Depends, Header, HTTPException
from sqlalchemy import select, func
from eth_utils import to_checksum_address

from app.api.deps import get_db
from app.config import settings
from app.models import MintTask, MintAuthorization, AutomaticGrant, AutomaticNonce, Wallet, User, CopyRule, CopyWatch, CopyCheck
from app.services import automatic, mint_instruction_cache
from app.services.custody import CustodyVault, private_read
from app.services.custody_accounts import verify_account
from app.services.automatic_fees import quote_gas, maximum_fee, receipt_cost
from app.services.mint_plans import aware
from app.services.opensea import OpenSeaUnavailable

app = FastAPI(title='Mintly isolated custody signer', docs_url=None, redoc_url=None, openapi_url=None)

# Unsigned execution data only. Restart/expiry falls back to full preparation.
_preflights = {}
_reconciled = {}


def intent_for(snapshot, grant):
    return automatic.digest({'snapshot': snapshot, 'policy': grant.context_hash})


async def reconcile_policy(journal, web3, grant):
    for entry in journal.execute('SELECT * FROM signed WHERE policy=? AND actual IS NULL', (grant.id,)).fetchall():
        hashes = [entry['hash']] + [row['hash'] for row in journal.execute(
            'SELECT hash FROM recoveries WHERE task=?', (entry['task'],)).fetchall()]
        for tx_hash in hashes:
            receipt = await final_receipt(web3, tx_hash, grant.chain_id)
            if receipt:
                tx = await web3.eth.get_transaction(tx_hash)
                actual = await receipt_cost(web3, receipt, grant.chain_id, tx.value)
                journal.execute('UPDATE signed SET actual=? WHERE task=?', (actual, entry['task']))
                from app.services.daily_budget import day_key
                included = await web3.eth.get_block(receipt.blockNumber)
                journal.execute('UPDATE daily_signed SET day=? WHERE task=?',
                    (day_key(datetime.fromtimestamp(included.timestamp,timezone.utc)),entry['task']))
                break
    journal.commit()
    _reconciled[grant.context_hash] = time.monotonic()
    if len(_reconciled) > 256:
        _reconciled.pop(next(iter(_reconciled)))


async def preflight_task(db, task_id, vault=None):
    """Advance checks never decrypt a key, allocate a nonce or return a signature."""
    task = await db.get(MintTask, task_id)
    if not task or task.status != 'armed' or task.signed_tx_raw or task.copy_rule_id:
        raise ValueError('Task is not available for advance checks')
    auth = await db.get(MintAuthorization, task.authorization_id)
    s = copy.deepcopy(auth.snapshot)
    grant = await automatic.grant_for(db, auth.grant_id, s['user_id'])
    if auth.is_revoked or aware(task.expires_at_utc) <= datetime.now(timezone.utc):
        raise ValueError('Task expired or was cancelled')
    intent = intent_for(s, grant)
    vault = vault or CustodyVault()
    policy = vault.policy(grant)
    await db.commit()  # No execution lock is held during advance RPC checks.
    web3 = await automatic.provider_for(grant.chain_id)
    journal = vault.journal()
    execution = None
    note = 'Advance checks passed. Gas and eligibility are checked again at mint time.'
    try:
        await verify_account(web3, policy)
        await reconcile_policy(journal, web3, grant)
        try:
            if s.get('execution'):
                execution = await automatic.validate_mint(web3, s, {'to':s['execution']['target'],
                    'value':s['execution']['value'], 'data':s['execution']['data']})
            else:
                execution = await automatic.prepare_mint(web3, s)
            balance = await web3.eth.get_balance(to_checksum_address(s['account']), 'pending')
            if balance < s['total_cap_wei']:
                note = 'Balance is below the approved maximum. Add ETH before mint time.'
        except OpenSeaUnavailable as error:
            from app.services.mint_diagnostics import MINT_REASONS
            note = MINT_REASONS.get(error.mint_reason,'Wallet-specific instructions are not ready. Another check will run at mint time.')
        except Exception:
            note = 'Advance checks unavailable. Mint-time checks are still required.'
    finally:
        journal.close()
        await web3.provider.disconnect()
    await automatic.lock_execution(db)
    await db.refresh(task)
    await db.refresh(auth)
    await db.refresh(grant)
    await automatic.require_running(db, grant.user_id)
    if task.status != 'armed' or task.signed_tx_raw or auth.is_revoked or intent_for(auth.snapshot, grant) != intent:
        raise ValueError('Task changed during advance checks')
    checked = time.monotonic()
    # Bounded, signer-private, short-lived cache; never trust API-supplied readiness.
    for key, value in list(_preflights.items()):
        if checked - value[0] > 90:
            _preflights.pop(key, None)
    if len(_preflights) >= 256:
        _preflights.pop(next(iter(_preflights)))
    if execution is not None:
        _preflights[task.id] = (checked, intent, execution)
        cache_journal=vault.journal()
        try:
            mint_instruction_cache.put(cache_journal,task.id,intent,execution,s['expiry']);cache_journal.commit()
        finally:cache_journal.close()
    task.preflight_checked_at, task.preflight_note = datetime.now(timezone.utc), note
    await db.commit()
    return {'status':'checked', 'note':note}


@app.post('/tasks/{task_id}/preflight')
async def advance_checks(task_id: str, authorization: str | None = Header(default=None), db=Depends(get_db)):
    from app.services import mint_diagnostics
    with mint_diagnostics.capture(task_id,'preflight') as events:
        authenticate(authorization)
        try:
            result=await preflight_task(db, task_id)
            return {**result,'_diagnostics':events}
        except Exception:
            await db.rollback()
            raise HTTPException(503, 'Advance checks unavailable; no transaction was signed.',headers=mint_diagnostics.headers(events)) from None


def authenticate(authorization: str | None = Header(default=None)):
    try:
        token = private_read(settings.AUTOMATIC_SIGNER_TOKEN_FILE)
        if len(token) < 32 or not hmac.compare_digest(authorization or '', 'Bearer ' + token):
            raise ValueError()
    except Exception:
        raise HTTPException(401, 'Signer authentication required.') from None


async def final_receipt(web3, tx_hash, chain_id=None):
    from web3.exceptions import TransactionNotFound
    try:
        receipt = await web3.eth.get_transaction_receipt(tx_hash)
    except TransactionNotFound:
        return None
    block = await web3.eth.get_block(receipt.blockNumber)
    if block.hash != receipt.blockHash or await web3.eth.block_number - receipt.blockNumber + 1 < max(2, settings.AUTOMATIC_CONFIRMATIONS):
        return None
    if (settings.AUTOMATIC_CHAIN_ID if chain_id is None else chain_id) in (1, 8453, 11155111, 4663):
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
    s = copy.deepcopy(auth.snapshot)
    grant = await automatic.grant_for(db, auth.grant_id, s['user_id'])
    wallet = await db.get(Wallet, task.wallet_id)
    user = await db.get(User, grant.user_id)
    if (auth.is_revoked or not user or not user.is_active or user.deleted_at
            or not wallet or wallet.archived_at or wallet.user_id != grant.user_id or wallet.id != grant.wallet_id
            or wallet.address.lower() != grant.account.lower() or auth.wallet_id != wallet.id
            or s['account'].lower() != wallet.address.lower() or s['recipient'].lower() != wallet.address.lower()
            or task.stage_id != auth.stage_id or task.drop_id != auth.drop_id
            or s['stage_id'] != auth.stage_id or s['drop_id'] != auth.drop_id
            or s['chain_id'] != grant.chain_id or s['quantity'] != auth.quantity
            or (s['price_cap_wei'], s['fee_cap_wei'], s['total_cap_wei']) !=
                (auth.max_price_per_token_wei, auth.max_fee_wei, auth.total_spend_cap_wei)
            or s['expiry'] != int(aware(task.expires_at_utc).timestamp())):
        raise ValueError('Authorization ownership, account or task scope mismatch')
    if s.get('execute_at') is not None:
        if int(aware(task.scheduled_for_utc).timestamp()) != s['execute_at']:
            raise ValueError('Task mint time differs from the reviewed authorization')
        if int(datetime.now(timezone.utc).timestamp()) < s['execute_at']:
            return {'task_id':task.id, 'status':'armed', 'note':'Waiting for the selected mint time.'}
    vault = vault or CustodyVault()
    policy = vault.policy(grant)
    if (not automatic.allows_collection(policy, s['contract'])
            or s['mint_kind'] not in policy['mint_kinds'] or s['expiry'] > policy['expires_at']
            or not 0 < s['total_cap_wei'] <= policy['max_task_wei']
            or not 0 < s['fee_cap_wei'] <= s['total_cap_wei']
            or not 1 <= s['quantity'] <= 100 or not 0 <= s['price_wei'] <= s['price_cap_wei']):
        raise ValueError('Independent signer policy limits exceeded')
    web3 = await automatic.provider_for(grant.chain_id)
    journal = vault.journal()
    try:
        copy_key = None
        if s.get('copy_source'):
            from app.services import copy_mints
            copy_mints.enabled()
            copy_key = copy_mints.stage_key(s)
            source = s['copy_source']
            active_check=await db.scalar(select(CopyCheck).join(CopyWatch,CopyWatch.id==CopyCheck.watch_id).where(
                CopyCheck.user_id==user.id,CopyCheck.active.is_(True),
                func.lower(CopyWatch.address)==source['source_address'].lower()))
            if active_check:
                raise ValueError('Check-only mode cannot sign copied mints')
            if (task.copy_stage_key != copy_key or s['mint_kind'] != source.get('mint_kind', 'public')
                    or source['chain_id'] != s['chain_id'] or source['contract'].lower() != s['contract'].lower()
                    or any(source[k] != s[k] for k in ('start','end'))
                    or (s['mint_kind'] == 'public' and source['price_wei'] != s['price_wei'])
                    or (s['mint_kind'] != 'public' and source['onchain_stage_index'] != s.get('onchain_stage_index'))):
                raise ValueError('Copy source differs from the authorized public stage')
            await copy_mints.verify_source(web3, source)
            if task.copy_rule_id:
                rule = await db.get(CopyRule, task.copy_rule_id)
                check=await db.get(CopyCheck,rule.watch_id) if rule else None
                if check and check.active:
                    raise ValueError('Check-only mode cannot sign copied mints')
                pin = journal.execute('SELECT * FROM copy_rules WHERE id=?', (task.copy_rule_id,)).fetchone()
                if not rule or rule.status != 'active' or not pin or pin['intent'] != rule.context_hash:
                    raise ValueError('Copy approval is paused or not independently registered')
                r = json.loads(pin['snapshot'])
                mode = copy_mints.quantity_mode(r)
                group = copy_mints.budget_group(r)
                if group is not None:
                    if rule.id not in group['members']:
                        raise ValueError('Copy approval is outside its shared budget')
                    for member in group['members']:
                        sibling = journal.execute('SELECT snapshot FROM copy_rules WHERE id=?', (member,)).fetchone()
                        sibling = json.loads(sibling['snapshot']) if sibling else None
                        if (not sibling or copy_mints.budget_group(sibling) != group
                                or any(sibling[k] != r[k] for k in ('user_id','watch_id','wallet_id','account','source_address'))):
                            raise ValueError('Shared copy approval is not fully pinned')
                quantity_matches = (r['quantity'] == s['quantity'] if mode == 'fixed' else (
                    s.get('copy_quantity_mode') == mode and 1 <= s['quantity'] <= r['quantity']
                    and (mode=='max_available' or (s['price_wei'] == 0 and s['price_cap_wei'] == 0))))
                if (automatic.digest(rule.snapshot) != pin['intent'] or s.get('copy_rule_id') != rule.id
                        or s['mint_kind'] not in r.get('mint_kinds', ['public'])
                        or r['grant_id'] != grant.id or r['user_id'] != grant.user_id
                        or r['chain_id'] != s['chain_id'] or r['wallet_id'] != wallet.id
                        or r['source_address'].lower() != source['source_address'].lower()
                        or source['block_number'] <= r['after_block']
                        or not quantity_matches or s['expiry'] > r['expiry']
                        or s['price_cap_wei'] != r['price_cap_wei'] or s['fee_cap_wei'] != r['fee_cap_wei']
                        or (s['total_cap_wei'] != r['total_cap_wei'] if mode!='max_available' else not 0<s['total_cap_wei']<=r['total_cap_wei'])
                        or not copy_mints.accepts_price(r,s['price_wei'])):
                    raise ValueError('Copy mint differs from the independently approved limits')
            duplicate = journal.execute('SELECT task FROM copy_signed WHERE stage=?', (copy_key,)).fetchone()
            if duplicate and duplicate['task'] != task.id:
                raise ValueError('This public stage already has a signed copy for this wallet')
        elif task.copy_rule_id or task.copy_stage_key:
            raise ValueError('Copy task lacks a verified source')
        block = await web3.eth.get_block('latest')
        now = max(int(datetime.now(timezone.utc).timestamp()), block.timestamp)
        if now >= min(s['expiry'], policy['expires_at']):
            raise ValueError('Task or signer policy expired')
        if block.timestamp < s['start']:
            return {'task_id': task.id, 'status': 'armed', 'note': 'Waiting for chain time.'}
        await verify_account(web3, policy)
        intent = intent_for(s, grant)
        previous = journal.execute('SELECT * FROM signed WHERE task=?', (task.id,)).fetchone()
        if previous:
            if previous['intent'] != intent:
                raise ValueError('Attempt to change a previously signed task')
            raw, tx_hash, nonce = previous['raw'], previous['hash'], previous['nonce']
        else:
            from app.services import daily_budget
            await daily_budget.check_private(db,journal,vault,user,task,auth,web3,datetime.now(timezone.utc))
            # Independently reconcile the signer's lifetime budget; API DB edits cannot reset it.
            advance = _preflights.get(task.id)
            if (not advance or advance[1] != intent or time.monotonic() - advance[0] > 90
                    or time.monotonic() - _reconciled.get(grant.context_hash, -1000) > 30):
                await reconcile_policy(journal, web3, grant)
            charged = journal.execute('SELECT COALESCE(SUM(COALESCE(actual,liability)),0) FROM signed WHERE policy=?', (grant.id,)).fetchone()[0]
            if charged + s['total_cap_wei'] > policy['budget_wei']:
                raise ValueError('Independent signer budget exhausted or reserved by uncertain submissions')
            if task.copy_rule_id:
                if group is not None:
                    await reconcile_copy_group(journal, group, web3, grant.chain_id)
                    marks = ','.join('?' for _ in group['members'])
                    charged_group = journal.execute('SELECT COALESCE(SUM(COALESCE(s.actual,s.liability)),0) '
                        f'FROM signed s JOIN copy_signed c ON c.task=s.task WHERE c.rule IN ({marks})',
                        group['members']).fetchone()[0]
                    if charged_group + s['total_cap_wei'] > group['budget_wei']:
                        raise ValueError('Independent shared copy budget exhausted or reserved')
                charged_copy = journal.execute('SELECT COALESCE(SUM(COALESCE(s.actual,s.liability)),0) FROM signed s '
                    'JOIN copy_signed c ON c.task=s.task WHERE c.rule=?', (task.copy_rule_id,)).fetchone()[0]
                if charged_copy + s['total_cap_wei'] > r['budget_wei']:
                    raise ValueError('Independent copy budget exhausted or reserved')
            address = to_checksum_address(s['account'])
            if await web3.eth.get_balance(address, 'pending') <= s['price_wei'] * s['quantity']:
                raise ValueError('Insufficient funds for mint value and gas')
            if copy_key:
                await copy_mints.no_mixed_stage_copy(db, s, task_id=task.id)
                verify_collection_copy_journal(journal, s, task.id)
            execution = None
            cached = _preflights.pop(task.id, None)
            if cached and cached[1] == intent and time.monotonic() - cached[0] <= 90:
                execution = cached[2]
            if not execution:
                execution=mint_instruction_cache.get(journal,task.id,intent)
            if not execution:
                execution=s.get('execution')
            if execution:
                try:
                    await automatic.validate_mint(web3, s, {'to': execution['target'], 'value': execution['value'], 'data': execution['data']})
                except OpenSeaUnavailable as error:
                    if error.mint_reason!='invalid_proof':raise
                    # Only unsigned tasks reach this branch. Renew the proof once,
                    # preserving the exact pinned approval and all independent checks.
                    from app.services.opensea import forget_verified_mint,collection_slug
                    forget_verified_mint(collection_slug(s['mint_page_url']),s['account'],s['quantity'])
                    execution=await automatic.prepare_mint(web3,s)
            else:
                execution = await automatic.prepare_mint(web3, s)
            mint_instruction_cache.put(journal,task.id,intent,execution,s['expiry'])
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
            try:
                gas, gas_price = await quote_gas(web3, tx, s['chain_id'])
            except Exception as error:
                from app.services.copy_mints import balance_error
                if balance_error(error):
                    raise ValueError('Insufficient funds for mint value and gas') from None
                raise
            tx['gasPrice'] = gas_price
            fee = await maximum_fee(web3, tx, s['chain_id'], gas, gas_price)
            if fee > s['fee_cap_wei'] or tx['value'] + fee > s['total_cap_wei']:
                raise ValueError('Estimated gas or total debit exceeds task authorization')
            if await web3.eth.get_balance(address, 'pending') < tx['value'] + fee:
                raise ValueError('Insufficient funds for mint value and gas')
            # Nitro checks affordability against eth_call's gas limit. Omitting it
            # uses a block-sized RPC default, rejecting otherwise funded wallets.
            tx['gas'] = gas
            await web3.eth.call(tx, 'pending')
            # Recheck wall time after network preparation, immediately before using the key.
            if int(datetime.now(timezone.utc).timestamp()) >= s['expiry']:
                raise ValueError('Task expired during preparation')
            if s.get('execute_at') is not None and int(datetime.now(timezone.utc).timestamp()) < s['execute_at']:
                raise ValueError('Selected mint time has not arrived')
            await verify_account(web3, policy)
            account = vault.account(policy)
            signed = account.sign_transaction(tx)
            del account
            raw, tx_hash = '0x' + bytes(signed.raw_transaction).hex(), '0x' + bytes(signed.hash).hex()
            journal.execute('INSERT INTO signed(task,policy,intent,address,chain,nonce,liability,raw,hash) VALUES(?,?,?,?,?,?,?,?,?)',
                (task.id, grant.id, intent, address.lower(), s['chain_id'], nonce, s['total_cap_wei'], raw, tx_hash))
            journal.execute('INSERT INTO daily_signed(task,user_id,day) VALUES(?,?,?)',
                (task.id,user.id,daily_budget.day_key(datetime.now(timezone.utc))))
            if copy_key:
                journal.execute('INSERT INTO copy_signed(task,rule,stage) VALUES(?,?,?)', (task.id, task.copy_rule_id, copy_key))
                journal.execute('INSERT INTO copy_collections(task,address,chain,contract,kind) VALUES(?,?,?,?,?)',
                    (task.id, address.lower(), s['chain_id'], s['contract'].lower(), s['mint_kind']))
            journal.commit()  # fsync BEFORE returning or persisting anything broadcastable to the worker
        reservation = await db.get(AutomaticNonce, task.id)
        if not reservation:
            db.add(AutomaticNonce(task_id=task.id, chain_id=s['chain_id'], address=s['account'].lower(), nonce=nonce))
        task.signed_tx_raw, task.transaction_hash, task.assigned_nonce = raw, tx_hash, nonce
        task.status = 'prepared'
        task.next_attempt_at = None
        task.failure_reason = None
        task.prepared_calldata = json.dumps(s.get('execution')) if s.get('execution') else None
        await db.commit()  # signed payload and hash durable before scheduler may broadcast
        return {'task_id': task.id, 'status': task.status, 'hash': tx_hash}
    finally:
        journal.close()
        await web3.provider.disconnect()


@app.post('/tasks/{task_id}/prepare', dependencies=[Depends(authenticate)])
async def prepare(task_id: str, db=Depends(get_db)):
    from app.services import mint_diagnostics
    with mint_diagnostics.capture(task_id,'preparation') as events:
        try:
            result=await prepare_task(db, task_id)
            return {**result,'_diagnostics':events}
        except OpenSeaUnavailable as error:
            await db.rollback()
            retry_headers=mint_diagnostics.headers(events)
            if error.retry_after_seconds is not None:
                retry_headers['Retry-After']=str(max(1,min(86400,error.retry_after_seconds)))
            if error.mint_reason:retry_headers['X-Mintly-Reason']=error.mint_reason
            if error.upstream_status:retry_headers['X-Mintly-Upstream-Status']=str(error.upstream_status)
            raise HTTPException(409 if error.status in (400,409,422) else 503,str(error),headers=retry_headers) from None
        except (ValueError, HTTPException) as error:
            await db.rollback()
            if isinstance(error,HTTPException) and (error.status_code == 429 or error.status_code >= 500):
                error.headers={**(error.headers or {}),**mint_diagnostics.headers(events)}
                raise error
            actionable = {'Insufficient funds for mint value and gas', 'Estimated gas or total debit exceeds task authorization',
                          'Task or signer policy expired', 'Public stage changed on chain',
                          'Independent signer budget exhausted or reserved by uncertain submissions',
                          'Independent shared copy budget exhausted or reserved',
                          'Whitelist copy already signed. Public mint skipped.', 'Public copy already signed. Whitelist mint skipped.'}
            detail = str(error) if str(error) in actionable else 'Independent signer rejected task policy, identity, budget or chain readiness.'
            raise HTTPException(409, detail,headers=mint_diagnostics.headers(events)) from None
        except Exception:
            await db.rollback()
            raise HTTPException(503, 'Signer or RPC temporarily unavailable; no fresh-nonce retry is permitted.',headers=mint_diagnostics.headers(events)) from None


@app.post('/account-limits/{user_id}/register',dependencies=[Depends(authenticate)])
async def register_daily_limit(user_id: str, db=Depends(get_db)):
    from app.services import daily_budget
    await automatic.lock_execution(db)
    user = await db.get(User,user_id,populate_existing=True)
    if not user or not user.is_active or user.deleted_at or user.daily_limit_status not in ('active','registering'):
        raise HTTPException(409,'Daily limit owner is unavailable.')
    vault = CustodyVault()
    journal = vault.journal()
    try:
        config = daily_budget.configuration(user)
        pin = journal.execute('SELECT * FROM daily_limits WHERE user_id=?',(user.id,)).fetchone()
        if pin and (pin['revision'] > config['revision'] or (
                pin['revision'] == config['revision'] and pin['intent'] != automatic.digest(config))):
            raise ValueError('Cannot rewrite a registered limit revision')
        if config['limit_wei'] is not None and not 0 < config['limit_wei'] < 2**63:
            raise ValueError('Invalid daily ceiling')
        await daily_budget.backfill_private(journal,vault,user.id)
        journal.execute('INSERT INTO daily_limits(user_id,revision,intent,configuration) VALUES(?,?,?,?) '
            'ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision,intent=excluded.intent,configuration=excluded.configuration',
            (user.id,config['revision'],automatic.digest(config),json.dumps(config,sort_keys=True)))
        journal.commit()
        await db.commit()
        return {'registered':True,'revision':config['revision']}
    except Exception:
        await db.rollback()
        raise HTTPException(503,'Daily limit confirmation unavailable. Future signing remains blocked.') from None
    finally:
        journal.close()


@app.get('/account-limits/{user_id}/usage',dependencies=[Depends(authenticate)])
async def daily_usage(user_id: str, db=Depends(get_db)):
    from app.services import daily_budget
    user = await db.get(User,user_id)
    if not user or not user.is_active or user.deleted_at:
        raise HTTPException(404,'Account not found.')
    journal = CustodyVault().journal()
    try:
        daily_budget.private_configuration(journal,user)
        await daily_budget.reconcile_private(journal,user.id)
        used = daily_budget.private_usage(journal,user.id,daily_budget.day_key())
        return {**{k:str(v) for k,v in used.items()},'signed_tasks':[
            r['task'] for r in journal.execute('SELECT task FROM daily_signed WHERE user_id=?',(user.id,)).fetchall()]}
    except Exception:
        raise HTTPException(503,'Registered spending information unavailable.') from None
    finally:
        journal.close()


@app.post('/copy-rules/{rule_id}/register', dependencies=[Depends(authenticate)])
async def register_copy_rule(rule_id: str, db=Depends(get_db)):
    from app.services import copy_mints
    copy_mints.enabled()
    rule = await db.get(CopyRule, rule_id)
    if not rule or rule.status not in ('registering','active','paused'):
        raise HTTPException(409, 'Copy approval is unavailable.')
    grant = await automatic.grant_for(db, rule.grant_id, rule.user_id)
    watch = await db.get(CopyWatch, rule.watch_id)
    vault = CustodyVault()
    policy = vault.policy(grant)
    r = rule.snapshot
    try:
        copy_mints.quantity_mode(r)
        group = copy_mints.budget_group(r)
        if group is not None and rule.id not in group['members']:
            raise ValueError('Rule missing from shared budget')
    except (ValueError, KeyError):
        raise HTTPException(409, 'Copy quantity mode is outside the approved free-mint scope.') from None
    user = await db.get(User, rule.user_id)
    if (not watch or watch.archived_at or watch.user_id != grant.user_id or not user or not user.is_active or user.deleted_at
            or automatic.digest(r) != rule.context_hash or r['user_id'] != grant.user_id
            or r['grant_id'] != grant.id or r['wallet_id'] != grant.wallet_id or r['account'].lower() != grant.account.lower()
            or r['chain_id'] != grant.chain_id or r['source_address'].lower() != watch.address.lower()
            or watch.address.lower() == grant.account.lower() or r['watch_id'] != watch.id
            or r['expiry'] != int(aware(rule.expires_at).timestamp()) or r['expiry'] > policy['expires_at']
            or r['expiry'] <= int(datetime.now(timezone.utc).timestamp())
            or not set(r.get('mint_kinds', ['public'])) <= set(policy['mint_kinds'])
            or r.get('mint_kinds', ['public']) not in (['public'], ['public','allowlist','signed'])
            or not 1 <= r['quantity'] <= 100
            or not 0 <= r['price_cap_wei'] or not 0 < r['fee_cap_wei']
            or r['total_cap_wei'] != (min(r['price_cap_wei']*r['quantity']+r['fee_cap_wei'],r['budget_wei'],policy['max_task_wei'])
                if r.get('quantity_mode')=='max_available' else r['price_cap_wei']*r['quantity']+r['fee_cap_wei'])
            or not r['total_cap_wei'] <= min(r['budget_wei'], policy['max_task_wei'])
            or r['budget_wei'] != rule.budget_wei or r['budget_wei'] > policy['budget_wei']
            or (r['free_only'] and r['price_cap_wei'] != 0)):
        raise HTTPException(409, 'Copy limits differ from the wallet policy or approval.')
    journal = vault.journal()
    try:
        prior = journal.execute('SELECT intent FROM copy_rules WHERE id=?', (rule.id,)).fetchone()
        if prior and prior['intent'] != rule.context_hash:
            raise HTTPException(409, 'A pinned copy approval cannot be changed.')
        journal.execute('INSERT OR IGNORE INTO copy_rules(id,intent,snapshot) VALUES(?,?,?)',
            (rule.id, rule.context_hash, json.dumps(r, sort_keys=True)))
        journal.commit()
    finally:
        journal.close()
    return {'status': 'registered', 'rule_id': rule.id}


async def reconcile_copy_group(journal, group, current_web3, current_chain):
    """Charge all networks together; uncertain receipts retain their full liability."""
    marks = ','.join('?' for _ in group['members'])
    entries = journal.execute('SELECT s.* FROM signed s JOIN copy_signed c ON c.task=s.task '
        f'WHERE c.rule IN ({marks}) AND s.actual IS NULL', group['members']).fetchall()
    providers = {current_chain: current_web3}
    try:
        for entry in entries:
            try:
                chain = entry['chain']
                if chain not in providers:
                    providers[chain] = await automatic.provider_for(chain)
                web3 = providers[chain]
                hashes = [entry['hash']] + [r['hash'] for r in journal.execute(
                    'SELECT hash FROM recoveries WHERE task=?', (entry['task'],)).fetchall()]
                for tx_hash in hashes:
                    receipt = await final_receipt(web3, tx_hash, chain)
                    if receipt:
                        tx = await web3.eth.get_transaction(tx_hash)
                        actual = await receipt_cost(web3, receipt, chain, tx.value)
                        journal.execute('UPDATE signed SET actual=? WHERE task=?', (actual, entry['task']))
                        break
            except Exception:
                continue  # A failed RPC never frees an uncertain reservation.
        journal.commit()
    finally:
        for chain, web3 in providers.items():
            if chain != current_chain:
                await web3.provider.disconnect()


def verify_collection_copy_journal(journal, snapshot, task_id):
    """Recover old collection guards from signed bytes, never mutable task history."""
    from eth_account import Account
    from eth_account._utils.legacy_transactions import Transaction
    from app.services.seadrop_mint import decode_mint
    from eth_utils import keccak
    address, chain, contract = snapshot['account'].lower(), snapshot['chain_id'], snapshot['contract'].lower()
    entries = journal.execute('SELECT s.* FROM signed s JOIN copy_signed c ON c.task=s.task '
        'LEFT JOIN copy_collections n ON n.task=s.task WHERE s.address=? AND s.chain=? AND n.task IS NULL',
        (address, chain)).fetchall()
    for entry in entries:
        raw = bytes.fromhex(entry['raw'].removeprefix('0x'))
        tx = Transaction.from_bytes(raw)
        if (Account.recover_transaction(raw).lower() != address or '0x' + keccak(raw).hex() != entry['hash']
                or tx.v < 35 or (tx.v - 35) // 2 != chain or len(tx.data) < 132):
            raise ValueError('Stored copy signature could not be verified')
        nft = to_checksum_address(tx.data[16:36])
        count = int.from_bytes(tx.data[100:132], 'big')
        mint = decode_mint({'to': '0x' + tx.to.hex(), 'data': '0x' + tx.data.hex(), 'value': str(tx.value)}, nft, address, count)
        journal.execute('INSERT INTO copy_collections(task,address,chain,contract,kind) VALUES(?,?,?,?,?)',
            (entry['task'], address, chain, nft.lower(), mint['kind']))
    journal.commit()
    opposite = ('allowlist','signed') if snapshot['mint_kind'] == 'public' else ('public',)
    marks = ','.join('?' for _ in opposite)
    if journal.execute('SELECT task FROM copy_collections WHERE address=? AND chain=? AND contract=? '
            f'AND task<>? AND kind IN ({marks}) LIMIT 1', (address, chain, contract, task_id, *opposite)).fetchone():
        raise ValueError('Whitelist copy already signed. Public mint skipped.' if snapshot['mint_kind'] == 'public'
            else 'Public copy already signed. Whitelist mint skipped.')


@app.get('/tasks/{task_id}/unsigned', dependencies=[Depends(authenticate)])
async def unsigned_task(task_id: str):
    journal = CustodyVault().journal()
    try:
        return {'unsigned': journal.execute('SELECT task FROM signed WHERE task=?', (task_id,)).fetchone() is None}
    finally:
        journal.close()


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


@app.get('/accounts/{address}/relink-ready', dependencies=[Depends(authenticate)])
async def relink_ready(address: str):
    """Read-only check of signatures durable before a possibly failed database commit.

    Import holds the execution lock while calling this; do not acquire it again here.
    Never expose signatures or let database cancellation imply on-chain settlement.
    """
    providers = {}
    journal = CustodyVault().journal()
    try:
        address = to_checksum_address(address).lower()
        entries = journal.execute('SELECT task,chain,hash FROM signed WHERE address=? AND actual IS NULL',
            (address,)).fetchall()
        for entry in entries:
            chain = entry['chain']
            if chain not in providers:
                providers[chain] = await automatic.provider_for(chain)
            hashes = [entry['hash']] + [row['hash'] for row in journal.execute(
                'SELECT hash FROM recoveries WHERE task=?', (entry['task'],)).fetchall()]
            settled = False
            for tx_hash in hashes:
                if await final_receipt(providers[chain], tx_hash, chain):
                    settled = True
                    break
            if not settled:
                return {'ready': False}
        return {'ready': True}
    except Exception:
        return {'ready': False}
    finally:
        journal.close()
        for web3 in providers.values():
            await web3.provider.disconnect()


@app.get('/policies/{grant_id}/ready', dependencies=[Depends(authenticate)])
async def policy_ready(grant_id: str, db=Depends(get_db)):
    automatic.enabled()
    try:
        grant = await db.get(AutomaticGrant, grant_id)
        if not grant or grant.status != 'enabled' or aware(grant.expires_at) <= datetime.now(timezone.utc):
            raise ValueError()
        vault = CustodyVault()
        policy = vault.policy(grant)
        web3 = await automatic.provider_for(grant.chain_id)
        try:
            await verify_account(web3, policy)
        finally:
            await web3.provider.disconnect()
        account = vault.account(policy)
        del account
        return {'status': 'ready', 'policy_id': grant.id, 'account': grant.account}
    except Exception:
        raise HTTPException(409, 'Custodial policy or encrypted keystore is unavailable.') from None


@app.post('/opensea/{wallet_id}/register',dependencies=[Depends(authenticate)])
async def register_opensea(wallet_id:str,db=Depends(get_db)):
    from app.services.opensea_identity import connection
    try:return await connection(db,wallet_id,'register')
    except Exception:
        await db.rollback()
        raise HTTPException(503,'OpenSea access could not be confirmed. No mint transaction was signed.') from None


from pydantic import BaseModel,Field
class EligibilityLookup(BaseModel):
    api_key:str=Field(min_length=10,max_length=512)

@app.post('/opensea/{wallet_id}/stages/{slug}',dependencies=[Depends(authenticate)])
async def opensea_stages(wallet_id:str,slug:str,req:EligibilityLookup,db=Depends(get_db)):
    from app.services.opensea_identity import connection,IdentityUnavailable,IdentityWalletMismatch
    try:return await connection(db,wallet_id,'stages',slug=slug,key=req.api_key)
    except IdentityWalletMismatch:
        await db.rollback()
        raise HTTPException(409,'OpenSea returned another linked wallet. Reconnect eligibility access for this receiving wallet.') from None
    except IdentityUnavailable as error:
        await db.rollback()
        code=409 if error.status in (401,403) else 503
        raise HTTPException(code,'OpenSea eligibility access needs reconnection.' if code==409 else 'OpenSea eligibility checks are temporarily unavailable.') from None
    except Exception:
        await db.rollback()
        raise HTTPException(409,'Verify this wallet’s OpenSea eligibility access again.') from None
