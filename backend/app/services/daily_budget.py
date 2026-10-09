"""One account-wide ETH debit ceiling per WAT day, with carried liabilities."""
from datetime import datetime, timezone, timedelta
import json
import uuid
from fastapi import HTTPException
from sqlalchemy import select, or_, and_
from app.models import DailyDebit, User, Wallet, MintTask, MintAuthorization
from app.services.mint_plans import aware

LIMIT_NOTE = 'Daily spending limit reached. Pending mints count toward this limit.'


def day_key(value=None):
    return (aware(value or datetime.now(timezone.utc)) + timedelta(hours=1)).date().isoformat()


def configuration(user):
    return {'user_id':user.id, 'limit_wei':user.daily_limit_wei, 'revision':user.daily_limit_revision, 'timezone':'WAT'}


async def seed_existing(db, user_id):
    rows = (await db.execute(select(MintTask, MintAuthorization).join(MintAuthorization,
        MintAuthorization.id == MintTask.authorization_id).join(Wallet, Wallet.id == MintTask.wallet_id)
        .where(Wallet.user_id == user_id, MintTask.execution_mode == 'custodial_v1'))).all()
    for task, auth in rows:
        if await db.get(DailyDebit,task.id):
            continue
        settled = task.status in ('confirmed','reverted','failed','expired','disarmed') and (
            task.status in ('confirmed','reverted') or not task.signed_tx_raw)
        db.add(DailyDebit(task_id=task.id, user_id=user_id,
            day=day_key(task.included_at or task.submitted_at or task.scheduled_for_utc),
            maximum_wei=auth.total_spend_cap_wei,
            actual_wei=(task.actual_total_cost_wei or 0) if settled else None))
    await db.flush()


async def usage(db, user_id, day=None, excluding=None):
    day = day or day_key()
    rows = (await db.scalars(select(DailyDebit).where(DailyDebit.user_id == user_id,
        or_(DailyDebit.day == day, and_(DailyDebit.day < day, DailyDebit.actual_wei.is_(None))),
        *([DailyDebit.task_id != excluding] if excluding else [])))).all()
    return {'spent_wei':sum(r.actual_wei or 0 for r in rows),
        'reserved_wei':sum(r.maximum_wei for r in rows if r.actual_wei is None)}


async def reserve(db, task, auth, user_id, *, now=None):
    user = await db.get(User,user_id,populate_existing=True)
    if user.daily_limit_status != 'active':
        raise HTTPException(503,'Daily limit confirmation is pending. Retry in Settings.')
    day = day_key(now or task.scheduled_for_utc)
    used = await usage(db,user_id,day,excluding=task.id)
    if user.daily_limit_wei is not None and used['spent_wei'] + used['reserved_wei'] + auth.total_spend_cap_wei > user.daily_limit_wei:
        raise HTTPException(429,LIMIT_NOTE)
    row = await db.get(DailyDebit,task.id)
    if not row:
        db.add(DailyDebit(task_id=task.id,user_id=user_id,day=day,maximum_wei=auth.total_spend_cap_wei))
    elif not task.signed_tx_raw and task.status in ('armed','preparing'):
        if row.actual_wei not in (None,0):
            raise ValueError('A settled debit cannot be reused')
        row.day,row.actual_wei = day,None
    await db.flush()


async def settle(db, task, actual):
    row = await db.get(DailyDebit,task.id)
    if row:
        if row.actual_wei is not None:
            if row.actual_wei != actual:
                raise ValueError('Daily debit cannot be settled twice with different costs')
            return
        row.actual_wei = actual
        if task.included_at:
            row.day = day_key(task.included_at)


def private_configuration(journal, user):
    from app.services.automatic import digest
    pin = journal.execute('SELECT * FROM daily_limits WHERE user_id=?',(user.id,)).fetchone()
    config = configuration(user)
    if user.daily_limit_status != 'active':
        raise HTTPException(503,'Daily limit confirmation is pending. Retry in Settings.')
    if (pin and pin['intent'] != digest(config)) or (
            not pin and (user.daily_limit_revision != 0 or user.daily_limit_wei is not None)):
        raise ValueError('Daily limit differs from its independently registered configuration')
    return pin


async def backfill_private(journal, vault, user_id, web3=None, chain_id=None):
    """Old identities come from immutable policy files, never mutable API history."""
    from app.services import automatic
    from app.services.custody import private_read
    from app.services.automatic_signer import final_receipt
    from app.services.automatic_fees import receipt_cost
    rows = journal.execute('SELECT s.* FROM signed s LEFT JOIN daily_signed d ON d.task=s.task WHERE d.task IS NULL').fetchall()
    for entry in rows:
        policy_id = str(uuid.UUID(entry['policy']))
        policy = json.loads(private_read(vault.root / f'{policy_id}.policy.json'))
        if policy['grant_id'] != policy_id or policy['account'].lower() != entry['address'].lower() or policy['chain_id'] != entry['chain']:
            raise ValueError('Historical signing policy identity differs')
        if policy['user_id'] != user_id:
            continue
        own = web3 if web3 is not None and chain_id == entry['chain'] else await automatic.provider_for(entry['chain'])
        try:
            receipt = None
            hashes = [entry['hash']] + [r['hash'] for r in journal.execute('SELECT hash FROM recoveries WHERE task=?',(entry['task'],)).fetchall()]
            for tx_hash in hashes:
                receipt = await final_receipt(own,tx_hash,entry['chain'])
                if receipt:
                    break
            if receipt:
                block = await own.eth.get_block(receipt.blockNumber)
                day = day_key(datetime.fromtimestamp(block.timestamp,timezone.utc))
                tx = await own.eth.get_transaction(receipt.transactionHash)
                actual = await receipt_cost(own,receipt,entry['chain'],tx.value)
                journal.execute('UPDATE signed SET actual=? WHERE task=?',(actual,entry['task']))
            elif entry['actual'] is not None:
                raise ValueError('Historical settlement date could not be verified')
            else:
                day = '0000-00-00'  # Unresolved historical signatures carry into every day.
            journal.execute('INSERT INTO daily_signed(task,user_id,day) VALUES(?,?,?)',(entry['task'],user_id,day))
            journal.commit()
        finally:
            if own is not web3:
                await own.provider.disconnect()


def private_usage(journal, user_id, day):
    rows = journal.execute('SELECT s.actual,s.liability,d.day FROM signed s JOIN daily_signed d ON d.task=s.task WHERE d.user_id=?',(user_id,)).fetchall()
    return {'spent_wei':sum(r['actual'] for r in rows if r['actual'] is not None and r['day'] == day),
        'reserved_wei':sum(r['liability'] for r in rows if r['actual'] is None)}


async def check_private(db, journal, vault, user, task, auth, web3, now):
    private_configuration(journal,user)
    if user.daily_limit_wei is not None:
        await backfill_private(journal,vault,user.id,web3,auth.snapshot['chain_id'])
        await reconcile_private(journal,user.id,web3,auth.snapshot['chain_id'])
        used = private_usage(journal,user.id,day_key(now))
        if used['spent_wei'] + used['reserved_wei'] + auth.total_spend_cap_wei > user.daily_limit_wei:
            raise HTTPException(429,LIMIT_NOTE)
    await reserve(db,task,auth,user.id,now=now)


async def reconcile_private(journal,user_id,web3=None,chain_id=None):
    from app.services import automatic
    from app.services.automatic_signer import final_receipt
    from app.services.automatic_fees import receipt_cost
    entries=journal.execute('SELECT s.* FROM signed s JOIN daily_signed d ON d.task=s.task WHERE d.user_id=? AND s.actual IS NULL',(user_id,)).fetchall()
    for entry in entries:
        own=None
        try:
            own=web3 if web3 is not None and entry['chain']==chain_id else await automatic.provider_for(entry['chain'])
            hashes=[entry['hash']]+[r['hash'] for r in journal.execute('SELECT hash FROM recoveries WHERE task=?',(entry['task'],)).fetchall()]
            for tx_hash in hashes:
                receipt=await final_receipt(own,tx_hash,entry['chain'])
                if receipt:
                    tx=await own.eth.get_transaction(tx_hash)
                    block=await own.eth.get_block(receipt.blockNumber)
                    actual=await receipt_cost(own,receipt,entry['chain'],tx.value)
                    journal.execute('UPDATE signed SET actual=? WHERE task=?',(actual,entry['task']))
                    journal.execute('UPDATE daily_signed SET day=? WHERE task=?',
                        (day_key(datetime.fromtimestamp(block.timestamp,timezone.utc)),entry['task']))
                    journal.commit()
                    break
        except Exception:
            continue  # Outage keeps the entire unresolved liability charged.
        finally:
            if own is not None and own is not web3:
                await own.provider.disconnect()
