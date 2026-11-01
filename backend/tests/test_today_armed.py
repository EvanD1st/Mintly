"""Today shows owner-scoped automatic tasks ahead of display eligibility."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import pytest

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.drops import list_drops
from app.models import Drop, FeedWalletCheck, MintAuthorization, MintStage, MintTask
from app.services import feed_checks
from test_daily_feed import fixtures


async def armed_fixture(db, monkeypatch):
    users, wallets, drop = await fixtures(db, monkeypatch)
    now = datetime.now(timezone.utc)
    drop.contract_address = '0x' + 'a' * 40
    # Plans use private discovery rows, not the public Today row or its name.
    private = Drop(id='private', name='Renamed collection', chain_id=8453,
        contract_address=drop.contract_address, mint_page_url='https://opensea.io/collection/test')
    db.add(private)
    await db.flush()
    db.add(MintStage(id='private-stage', drop_id=private.id, stage_name='GTD', start_time_utc=now))
    await db.flush()
    auth = MintAuthorization(id='auth', wallet_id=wallets[0].id, drop_id=private.id,
        stage_id='private-stage', quantity=2, max_price_per_token_wei=0,
        max_fee_wei=10, total_spend_cap_wei=10, recipient_address=wallets[0].address,
        user_consent_text='Test approval', authorized_at=now,
        snapshot=dict(chain_id=8453, contract=drop.contract_address.upper(), stage_name='Approved GTD',
            mint_page_url=private.mint_page_url))
    db.add(auth)
    await db.flush()
    task = MintTask(id='task', authorization_id=auth.id, wallet_id=wallets[0].id,
        drop_id=private.id, stage_id='private-stage', status='armed', is_demo=False,
        idempotency_key='today-task', scheduled_for_utc=now + timedelta(hours=1),
        expires_at_utc=now + timedelta(hours=2))
    db.add(task)
    await db.commit()
    return users, wallets, drop, task, auth


async def test_today_active_status_overrides_missing_stale_and_changed_checks(test_db, monkeypatch):
    users, wallets, drop, task, auth = await armed_fixture(test_db, monkeypatch)
    for status in ('armed', 'preparing', 'prepared', 'submitting', 'submitted', 'uncertain'):
        task.status = status
        await test_db.commit()
        result = await list_drops('all', users[0], test_db, wallet_id=wallets[0].id, daily_only=True)
        card = result.drops[0]
        assert card.automatic_mint['id'] == task.id
        assert card.automatic_mint['status'] == status
        assert card.automatic_mint['quantity'] == 2
        assert card.automatic_mint['stage_name'] == 'Approved GTD'
        assert not card.wallet_check['setup_enabled']
        assert card.wallet_check['status'] == status
        # Wire response remains safe and JSON serializable, including WAT schedule input.
        assert result.model_dump(mode='json')['drops'][0]['automatic_mint']['scheduled_for_utc'].endswith('Z')
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    test_db.add(FeedWalletCheck(user_id=users[0].id, wallet_id=wallets[0].id, drop_id=drop.id,
        status='unverified', checked_at=old, expires_at=old,
        result={'collection_slug': 'old-collection', 'stages': [], 'note': 'Provider unavailable'}))
    await test_db.commit()
    result = await list_drops('all', users[0], test_db, wallet_id=wallets[0].id, daily_only=True)
    assert result.drops[0].automatic_mint['id'] == task.id
    assert 'Provider' not in result.drops[0].wallet_check['note']
    assert await test_db.scalar(select(func.count()).select_from(MintTask)) == 1


@pytest.mark.parametrize('status', ['armed', 'confirmed'])
async def test_today_task_identity_is_scoped_to_owner_wallet_network_and_contract(test_db, monkeypatch, status):
    users, wallets, drop, task, auth = await armed_fixture(test_db, monkeypatch)
    task.status = status
    await test_db.commit()
    assert await feed_checks.existing_mints(test_db, users[0], wallets[0], [drop])
    assert not await feed_checks.existing_mints(test_db, users[0], wallets[1], [drop])
    assert not await feed_checks.existing_mints(test_db, users[1], wallets[0], [drop])
    assert not await feed_checks.existing_mints(test_db, users[1], wallets[2], [drop])
    # Same name/slug on another network or changed contract cannot inherit Armed.
    auth.snapshot = {**auth.snapshot, 'chain_id': 1}
    await test_db.commit()
    assert not await feed_checks.existing_mints(test_db, users[0], wallets[0], [drop])
    auth.snapshot = {**auth.snapshot, 'chain_id': 8453, 'contract': '0x' + 'b' * 40}
    await test_db.commit()
    assert not await feed_checks.existing_mints(test_db, users[0], wallets[0], [drop])
    # Source lists without verified contracts can match the exact collection URL.
    drop.contract_address = None
    await test_db.commit()
    assert await feed_checks.existing_mints(test_db, users[0], wallets[0], [drop])
    drop.mint_page_url = 'https://opensea.io/collection/different'
    await test_db.commit()
    assert not await feed_checks.existing_mints(test_db, users[0], wallets[0], [drop])


async def test_active_mints_skip_display_checks_then_resume_after_disarming(test_db, monkeypatch):
    users, wallets, drop, task, auth = await armed_fixture(test_db, monkeypatch)
    await feed_checks.queue_checks(test_db, users[0], wallets[0], [drop])
    assert await test_db.scalar(select(func.count()).select_from(FeedWalletCheck)) == 0
    # A display check queued before arming must not perform provider calls either.
    row = FeedWalletCheck(user_id=users[0].id, wallet_id=wallets[0].id,
        drop_id=drop.id, status='queued', result={}, attempts=0)
    test_db.add(row)
    await test_db.commit()
    provider = AsyncMock(side_effect=AssertionError('Armed display must not fetch eligibility'))
    monkeypatch.setattr(feed_checks.OpenSeaClient, 'get_drop', provider)
    assert await feed_checks.step(async_sessionmaker(test_db.bind, expire_on_commit=False))
    provider.assert_not_awaited()
    assert not await feed_checks.step(async_sessionmaker(test_db.bind, expire_on_commit=False))
    await test_db.refresh(row)
    for status in ('failed', 'expired', 'reverted', 'disarmed'):
        task.status = status
        await test_db.commit()
        assert not await feed_checks.existing_mints(test_db, users[0], wallets[0], [drop])
    await feed_checks.queue_checks(test_db, users[0], wallets[0], [drop])
    await test_db.refresh(row)
    assert row.status == 'queued'
    assert await test_db.scalar(select(func.count()).select_from(MintTask)) == 1


async def test_confirmed_mint_retains_phase_and_skips_checks_even_when_archived(test_db, monkeypatch):
    users, wallets, drop, task, auth = await armed_fixture(test_db, monkeypatch)
    now = datetime.now(timezone.utc)
    # Even a stale eligible result must not offer a second setup after confirmation.
    row = FeedWalletCheck(user_id=users[0].id, wallet_id=wallets[0].id,
        drop_id=drop.id, status='queued', result={}, attempts=0)
    test_db.add(row)
    task.status = 'confirmed'
    task.confirmed_at = now
    task.transaction_hash = '0x' + '1' * 64
    task.archived_at = now
    stage = await test_db.get(MintStage, task.stage_id)
    stage.stage_name = 'Later FCFS'
    await test_db.commit()
    result = await list_drops('all', users[0], test_db, wallet_id=wallets[0].id, daily_only=True)
    card = result.drops[0]
    assert card.automatic_mint['status'] == 'confirmed'
    assert card.automatic_mint['stage_name'] == 'Approved GTD'
    assert card.automatic_mint['quantity'] == 2
    assert card.automatic_mint['confirmed_at'] == now
    assert card.wallet_check['status'] == 'confirmed' and not card.wallet_check['setup_enabled']
    assert 'already minted' in card.wallet_check['note']
    assert result.model_dump(mode='json')['drops'][0]['automatic_mint']['confirmed_at'].endswith('Z')
    await feed_checks.queue_checks(test_db, users[0], wallets[0], [drop])
    provider = AsyncMock(side_effect=AssertionError('Minted collection must not fetch eligibility'))
    monkeypatch.setattr(feed_checks.OpenSeaClient, 'get_drop', provider)
    assert await feed_checks.step(async_sessionmaker(test_db.bind, expire_on_commit=False))
    assert not await feed_checks.step(async_sessionmaker(test_db.bind, expire_on_commit=False))
    provider.assert_not_awaited()
    await feed_checks.queue_checks(test_db, users[0], wallets[0], [drop])
    await test_db.refresh(row)
    assert row.status == 'unverified'
    # A different selected wallet still gets its own eligibility discovery.
    await feed_checks.queue_checks(test_db, users[0], wallets[1], [drop])
    other = await test_db.get(FeedWalletCheck, (users[0].id, wallets[1].id, drop.id))
    assert other.status == 'queued'


async def test_confirmed_mint_takes_precedence_over_other_attempts(test_db, monkeypatch):
    users, wallets, drop, task, auth = await armed_fixture(test_db, monkeypatch)
    now = datetime.now(timezone.utc)
    task.status, task.confirmed_at = 'confirmed', now
    extra = MintTask(id='other-task', authorization_id=auth.id, wallet_id=wallets[0].id,
        drop_id=task.drop_id, stage_id=task.stage_id, status='armed', is_demo=False,
        idempotency_key='other-today-task', scheduled_for_utc=now - timedelta(hours=1),
        expires_at_utc=now + timedelta(hours=2))
    test_db.add(extra)
    await test_db.commit()
    for status in ('armed', 'submitted', 'failed', 'reverted'):
        extra.status = status
        await test_db.commit()
        result = await feed_checks.existing_mints(test_db, users[0], wallets[0], [drop])
        assert result[drop.id]['id'] == task.id
    extra.status, extra.confirmed_at = 'confirmed', now + timedelta(minutes=1)
    await test_db.commit()
    result = await feed_checks.existing_mints(test_db, users[0], wallets[0], [drop])
    assert result[drop.id]['id'] == extra.id
