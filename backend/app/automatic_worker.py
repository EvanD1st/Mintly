"""Dedicated deadline-aware automatic scheduler. No discovery, FCM or key material.

Run independently of app.worker; all retries reuse the persisted bytes and nonce.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import time
import tempfile

import httpx
from sqlalchemy import select, or_
from eth_utils import keccak
from web3.exceptions import TransactionNotFound

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import MintTask, MintAuthorization, ActivityEvent, MintRecovery
from app.services import automatic
from app.services.automatic_signer import final_receipt
from app.services.automatic_fees import receipt_cost, additional_fee
from app.services.mint_plans import aware

log = logging.getLogger('mintly.automatic')


async def request_signature(task_id):
    token = Path(settings.AUTOMATIC_SIGNER_TOKEN_FILE).read_text().strip()
    if len(token) < 32:
        raise ValueError('Signer authentication is not configured')
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        result = await client.post(settings.AUTOMATIC_SIGNER_URL + f'/tasks/{task_id}/prepare',
            headers={'Authorization': 'Bearer ' + token})
        result.raise_for_status()
        return result.json()


async def finish(db, task, status, note, actual=0):
    task.status, task.failure_reason = status, note
    task.notification_pending = True
    await automatic.release_reservation(db, task, actual)
    auth = await db.get(MintAuthorization, task.authorization_id)
    db.add(ActivityEvent(user_id=auth.snapshot['user_id'], event_type='automatic_' + status,
        label='Automatic mint ' + status, detail=f'{task.id}: {note or "Receipt confirmed"}',
        is_demo=False, icon_name='gem'))


async def step(session_factory=AsyncSessionLocal, sign=request_signature, *, now=None):
    automatic.enabled()
    now = now or datetime.now(timezone.utc)
    async with session_factory() as db:
        await automatic.lock_execution(db)
        task = (await db.execute(select(MintTask).where(
            MintTask.execution_mode == automatic.MODE,
            MintTask.status.in_(['armed','preparing','prepared','submitted','uncertain']),
            or_(MintTask.next_attempt_at.is_(None), MintTask.next_attempt_at <= now),
            MintTask.scheduled_for_utc <= now,
        ).order_by(MintTask.expires_at_utc, MintTask.id).limit(1))).scalar_one_or_none()
        if not task:
            await db.commit()
            return False
        task_id = task.id
        if task.status in ('armed', 'preparing'):
            if aware(task.expires_at_utc) <= now:
                await finish(db, task, 'expired', 'Submission window expired before signing.')
                await db.commit()
                return True
            task.next_attempt_at = now + timedelta(seconds=1)
            await db.commit()  # signer independently acquires the same lock
        else:
            recovery = await db.scalar(select(MintRecovery).where(MintRecovery.task_id == task.id))
            active_recovery = recovery if recovery and recovery.activated_at else None
            candidates = [(task.transaction_hash, task.signed_tx_raw)]
            if recovery:
                candidates += [(recovery.previous_hash, recovery.previous_signed_tx_raw)]
                if active_recovery:
                    candidates += [(recovery.replacement_hash, recovery.replacement_signed_tx_raw)]
            candidates = list(dict(candidates).items())
            auth = await db.get(MintAuthorization, task.authorization_id)
            chain_id = auth.snapshot['chain_id']
            web3 = await automatic.provider_for(chain_id)
            try:
                receipt = None
                for tx_hash, signed_raw in candidates:
                    receipt = await final_receipt(web3, tx_hash, chain_id)
                    if receipt:
                        task.transaction_hash, task.signed_tx_raw = tx_hash, signed_raw
                        task.explorer_url = explorer_url(tx_hash, chain_id)
                        if recovery:
                            recovery.status = ('confirmed' if receipt.status == 1 else 'reverted') if tx_hash == recovery.replacement_hash else 'superseded'
                        break
                if receipt:
                    auth = await db.get(MintAuthorization, task.authorization_id)
                    actual = await receipt_cost(web3, receipt, chain_id, auth.snapshot['price_wei'] * auth.quantity)
                    task.actual_gas_used, task.actual_effective_gas_price = receipt.gasUsed, receipt.effectiveGasPrice
                    task.actual_total_cost_wei = actual
                    task.block_number = receipt.blockNumber
                    task.receipt_block_hash = '0x' + bytes(receipt.blockHash).hex()
                    task.confirmed_at = now
                    await finish(db, task, 'confirmed' if receipt.status == 1 else 'reverted',
                        None if receipt.status == 1 else 'Mint reverted; receipt gas is charged. No automatic second mint.', actual)
                    await db.commit()
                    return True
                seen_receipt = None
                for tx_hash, _ in candidates:
                    try:
                        seen_receipt = await web3.eth.get_transaction_receipt(tx_hash)
                    except TransactionNotFound:
                        continue
                    if seen_receipt:
                        break
                task.next_attempt_at = now + timedelta(seconds=2)
                if seen_receipt:
                    task.status = 'submitted'
                    if active_recovery:
                        recovery.status = 'submitted'
                    task.failure_reason = 'Receipt observed; waiting for canonical confirmations.'
                    await db.commit()
                    return True
                expiry = active_recovery.expires_at if active_recovery else task.expires_at_utc
                attempt_ceiling = active_recovery.attempt_ceiling if active_recovery else 4
                if (aware(expiry) <= now or task.broadcast_attempts >= attempt_ceiling):
                    task.status = 'uncertain'
                    if active_recovery:
                        recovery.status = 'uncertain'
                    task.failure_reason = 'No confirmed receipt. Reservation retained; no new nonce or further broadcast.'
                    task.next_attempt_at = now + timedelta(seconds=15)
                    await db.commit()
                    return True
                # Verify durable integrity and publish intent before the network call.
                if active_recovery:
                    task.transaction_hash = recovery.replacement_hash
                    task.signed_tx_raw = recovery.replacement_signed_tx_raw
                raw = bytes.fromhex(task.signed_tx_raw.removeprefix('0x'))
                if '0x' + keccak(raw).hex() != task.transaction_hash:
                    raise ValueError('Signed transaction integrity mismatch')
                if chain_id == 8453:
                    from eth_account._utils.legacy_transactions import Transaction
                    decoded = Transaction.from_bytes(raw)
                    fee = decoded.gas * decoded.gasPrice + await additional_fee(web3, chain_id, decoded.gas, len(raw))
                    if fee > auth.max_fee_wei or decoded.value + fee > auth.total_spend_cap_wei:
                        task.status = 'uncertain'
                        task.failure_reason = 'Base parent or operator fees exceed the approved cap; saved transaction held without broadcasting.'
                        task.next_attempt_at = now + timedelta(seconds=15)
                        await db.commit()
                        return True
                task.status = 'uncertain'
                task.broadcast_attempts += 1
                task.submitted_at = task.submitted_at or now
                task.failure_reason = 'Broadcast may be in flight; cancellation cannot undo a signed transaction.'
                task.explorer_url = explorer_url(task.transaction_hash, chain_id)
                if active_recovery:
                    recovery.status = 'uncertain'
                await db.commit()
                try:
                    returned = await web3.eth.send_raw_transaction(raw)
                    if '0x' + bytes(returned).hex() != task.transaction_hash:
                        raise ValueError('Unexpected transaction hash')
                    await automatic.lock_execution(db)
                    await db.refresh(task)
                    if task.status in automatic.TERMINAL:
                        await db.commit()
                        return True
                    task.status = 'submitted'
                    if active_recovery:
                        recovery.status = 'submitted'
                    task.failure_reason = None
                    task.notification_pending = True
                except Exception:
                    # Includes accepted-then-timeout and already-known. Never release funds.
                    await automatic.lock_execution(db)
                    await db.refresh(task)
                    if task.status in automatic.TERMINAL:
                        await db.commit()
                        return True
                    task.status = 'uncertain'
                    task.failure_reason = 'RPC outcome uncertain; tracking the saved hash and retrying only identical bytes.'
                    task.next_attempt_at = now + timedelta(seconds=min(2 ** task.broadcast_attempts, 15))
                await db.commit()
                return True
            finally:
                await web3.provider.disconnect()
    try:
        await sign(task_id)
    except Exception as error:
        async with session_factory() as db:
            await automatic.lock_execution(db)
            task = await db.get(MintTask, task_id)
            # The signer may have committed before its HTTP response was lost.
            if task.status not in ('armed', 'preparing') or task.signed_tx_raw:
                await db.commit()
                return True
            task.preparation_attempts += 1
            permanent = isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 409
            if permanent or task.preparation_attempts >= 6:
                note = 'Bounded preparation retries exhausted. No transaction broadcast.'
                if permanent:
                    note = error.response.json().get('detail', 'Signer rejected readiness or policy.')
                await finish(db, task, 'expired' if note == 'Task or signer policy expired' else 'failed', note)
            else:
                task.next_attempt_at = now + timedelta(seconds=max(15, min(2 ** task.preparation_attempts, 60)))
                task.failure_reason = 'Preparation temporarily unavailable; bounded retry scheduled.'
            await db.commit()
    return True


def explorer_url(tx_hash, chain_id=None):
    base = {11155111: 'https://sepolia.etherscan.io/tx/',
            4663: 'https://robinhoodchain.blockscout.com/tx/', 1: 'https://etherscan.io/tx/',
            8453: 'https://basescan.org/tx/'}.get(settings.AUTOMATIC_CHAIN_ID if chain_id is None else chain_id)
    return base + tx_hash if base else None


async def run():
    automatic.enabled()
    while True:
        started = time.monotonic()
        try:
            await step()
            (Path(tempfile.gettempdir()) / 'mintly-automatic.heartbeat').touch()
        except Exception:
            # Do not log provider payloads, auth headers or signing data.
            log.error('Automatic scheduler iteration unavailable; durable state retained.')
        elapsed = time.monotonic() - started
        log.info('automatic_tick duration_ms=%d chain_id=%d', elapsed * 1000, settings.AUTOMATIC_CHAIN_ID)
        await asyncio.sleep(max(0.05, min(1.0, settings.AUTOMATIC_POLL_SECONDS) - elapsed))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
