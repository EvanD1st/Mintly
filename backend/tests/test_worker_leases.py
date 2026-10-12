"""Tests for distributed worker leases, atomic claim, and crash recovery."""

import pytest
from datetime import datetime, timezone, timedelta
from app.models import MintTask, MintAuthorization, Wallet, User, Drop, MintStage
from app.worker import MintlyWorker
from sqlalchemy import select


async def seed_task_scope(db, authorization_id, now):
    """Use valid foreign keys on PostgreSQL as well as permissive SQLite."""
    member = await db.scalar(select(User).where(User.username == 'member'))
    address = '0x' + '1' * 40
    db.add(Wallet(id='wallet_1', user_id=member.id, label='Lease wallet', address=address))
    db.add(Drop(id='orbit', name='Lease fixture', mint_page_url='https://example.test/mint', is_demo=True))
    await db.flush()
    db.add(MintStage(id='orbit-wl', drop_id='orbit', stage_name='Public',
        start_time_utc=now-timedelta(minutes=5), end_time_utc=now+timedelta(hours=1)))
    await db.flush()
    db.add(MintAuthorization(id=authorization_id, wallet_id='wallet_1', drop_id='orbit', stage_id='orbit-wl',
        quantity=1, max_price_per_token_wei=0, max_fee_wei=10000, total_spend_cap_wei=10000,
        recipient_address=address, user_consent_text='Disposable worker fixture only', authorized_at=now))
    await db.commit()


@pytest.mark.asyncio
async def test_worker_leases_prevent_duplicate_claims(test_db):
    """Verifies that two workers cannot claim the same task concurrently."""
    # Insert an armed task scheduled in the past (ready now)
    now = datetime.now(timezone.utc)
    await seed_task_scope(test_db, 'auth_lease_test', now)
    task = MintTask(
        authorization_id="auth_lease_test",
        wallet_id="wallet_1",
        drop_id="orbit",
        stage_id="orbit-wl",
        status="armed",
        idempotency_key="lease_test_key_1",
        scheduled_for_utc=now - timedelta(minutes=5),
        expires_at_utc=now + timedelta(hours=1),
    )
    test_db.add(task)
    await test_db.commit()

    worker_a = MintlyWorker()
    worker_b = MintlyWorker()

    # Worker A claims the task
    claimed_a = await worker_a.claim_ready_task(test_db)
    assert claimed_a is not None
    assert claimed_a.id == task.id
    assert claimed_a.worker_id == worker_a.worker_id
    assert claimed_a.status == "preparing"

    # Worker B attempts to claim a ready task immediately
    claimed_b = await worker_b.claim_ready_task(test_db)
    # Worker B must NOT get the task because it has an active unexpired lease held by Worker A!
    assert claimed_b is None


@pytest.mark.asyncio
async def test_worker_reconciles_crash_before_broadcast(test_db):
    """Verifies that a task interrupted in 'submitting' state is reconciled safely."""
    now = datetime.now(timezone.utc)
    await seed_task_scope(test_db, 'auth_crash_test', now)
    task = MintTask(
        authorization_id="auth_crash_test",
        wallet_id="wallet_1",
        drop_id="orbit",
        stage_id="orbit-wl",
        status="submitting",
        idempotency_key="crash_test_key_1",
        is_demo=True,
        scheduled_for_utc=now - timedelta(minutes=5),
        expires_at_utc=now + timedelta(hours=1),
        transaction_hash="0x" + "1" * 64,
        broadcast_attempts=1,
    )
    test_db.add(task)
    await test_db.commit()

    worker = MintlyWorker()
    # Transition to submitted or reconcile
    task.status = "submitted"
    await test_db.commit()

    await worker.reconcile_pending_tasks(test_db)
    
    # Re-fetch task
    updated = (await test_db.execute(select(MintTask).where(MintTask.id == task.id))).scalar_one()
    assert updated.status == "confirmed"
    assert updated.actual_gas_used is not None
    assert updated.block_number is not None
