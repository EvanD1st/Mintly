import asyncio
from unittest.mock import AsyncMock
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.api import artwork
from app.api.deps import get_db
from app.main import app
from app.models import (User, Wallet, MintPlan, OpenSeaRequestWaiter, CopyWatch, CopyRule,
    CopyEvent, CopyCheck, AutomaticGrant)
from datetime import datetime, timezone, timedelta
from app.services.opensea import OpenSeaClient, OpenSeaUnavailable
from app.models import CollectionArtwork


@pytest.fixture(autouse=True)
def clear_artwork():
    artwork._cache.clear()
    yield
    artwork._cache.clear()


@pytest.mark.parametrize('url', [None, '', 'http://i.seadn.io/a', 'https://i.seadn.io.evil.test/a',
    'https://i.seadn.io@evil.test/a', 'https://user:secret@i.seadn.io/a',
    'https://i.seadn.io:444/a', 'file:///private/key', 'https://127.0.0.1/a'])
def test_artwork_rejects_non_cdn_images(url):
    assert artwork.image_url(url) is None


async def test_artwork_singleflight_cache_and_optional_failure(monkeypatch):
    monkeypatch.setattr(OpenSeaClient, '_key', AsyncMock(return_value='server-only-test-key'))
    request = AsyncMock(return_value=(200, {'collection': 'example', 'image_url': 'https://i.seadn.io/example.png'}))
    monkeypatch.setattr(OpenSeaClient, '_request', request)
    values = await asyncio.gather(*(artwork.collection_image('example') for _ in range(6)))
    assert values == ['https://i.seadn.io/example.png'] * 6
    request.assert_awaited_once_with('GET', '/collections/example', key='server-only-test-key')
    assert await artwork.collection_image('example') == values[0]
    assert await artwork.collection_image('example', allow_fetch=False) == values[0]
    assert await artwork.collection_image('busy', allow_fetch=False) is None
    assert request.await_count == 1
    request.side_effect = OpenSeaUnavailable('Shared cooldown')
    assert await artwork.collection_image('unavailable') is None
    assert await artwork.collection_image('unavailable') is None
    assert request.await_count == 2  # No render/rebuild retry storm.


async def test_artwork_yields_to_urgent_waiters_without_mutating_them(test_db):
    now = datetime.now(timezone.utc)
    waiter = OpenSeaRequestWaiter(id='urgent-artwork-test', priority=0, expires_at=now + timedelta(seconds=8))
    test_db.add(waiter)
    await test_db.commit()
    assert await artwork.minting_busy(test_db) is True
    assert await test_db.get(OpenSeaRequestWaiter, waiter.id) is waiter
    waiter.expires_at = now - timedelta(seconds=1)
    await test_db.commit()
    assert await artwork.minting_busy(test_db) is False


async def test_artwork_contract_binding_and_response_validation(monkeypatch):
    monkeypatch.setattr(OpenSeaClient, '_key', AsyncMock(return_value='server-only-test-key'))
    contract = '0x' + '1' * 40
    request = AsyncMock(side_effect=[
        (200, {'chain': 'base', 'address': contract, 'collection': 'example'}),
        (200, {'collection': 'wrong-collection', 'image_url': 'https://i.seadn.io/wrong.png'}),
    ])
    monkeypatch.setattr(OpenSeaClient, '_request', request)
    assert await artwork.collection_image(chain_id=8453, contract=contract) is None
    assert request.await_count == 2
    assert all(call.args[0] == 'GET' for call in request.await_args_list)


async def test_artwork_requires_login_and_owns_private_plan(test_db, monkeypatch):
    user = await test_db.scalar(select(User).where(User.username == 'member'))
    wallet = Wallet(user_id=user.id, label='Main', address='0x' + '1' * 40,
        signing_capability='interactive', supported_chains=['Base'])
    test_db.add(wallet)
    await test_db.flush()
    plan = MintPlan(user_id=user.id, wallet_id=wallet.id, collection_slug='example',
        collection_name='Example', chain='base', chain_id=8453, contract_address='0x' + '2' * 40,
        opensea_url='https://opensea.io/collection/example')
    test_db.add(plan)
    await test_db.commit()
    fetch = AsyncMock(return_value='https://i.seadn.io/example.png')
    monkeypatch.setattr(artwork, 'collection_image', fetch)
    async def db():
        yield test_db
    app.dependency_overrides[get_db] = db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            path = f'/api/artwork?reference=plan:{plan.id}'
            assert (await client.get(path)).status_code == 401
            for username, password, status in [('admin', 'Admin test password 123', 404), ('member', 'Member test password 123', 200)]:
                login = await client.post('/api/auth/login', json={'username': username, 'password': password})
                client.headers['Authorization'] = 'Bearer ' + login.json()['token']
                response = await client.get(path)
                assert response.status_code == status
            assert response.json() == {'image_url': 'https://i.seadn.io/example.png'}
            assert fetch.await_count == 1
            assert (await client.get('/api/artwork?reference=https://evil.test')).status_code == 422
            now = datetime.now(timezone.utc)
            test_db.add(CollectionArtwork(key=artwork.artwork_key('example', 8453, plan.contract_address),
                image_url='https://i.seadn.io/saved.png', refresh_after=now-timedelta(days=14),
                stale_until=now-timedelta(days=7)))
            await test_db.commit()
            refresh = AsyncMock()
            monkeypatch.setattr(artwork, 'refresh_image', refresh)
            response = await client.get(path)
            assert response.json() == {'image_url': 'https://i.seadn.io/saved.png'}
            assert fetch.await_count == 1  # No upstream wait in the screen request.
            refresh.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_persistent_cache_survives_memory_restart_and_busy_preparation(test_db, monkeypatch):
    monkeypatch.setattr(OpenSeaClient, '_key', AsyncMock(return_value='server-only-test-key'))
    fetch = AsyncMock(return_value=(200, {'collection':'example','image_url':'https://i.seadn.io/persist.png'}))
    monkeypatch.setattr(OpenSeaClient, '_request', fetch)
    expected = await artwork.collection_image('example',chain_id=8453,contract='0x'+'a'*40,db=test_db)
    artwork._cache.clear()
    assert await artwork.collection_image('example',chain_id=8453,contract='0x'+'A'*40,
        db=test_db,allow_fetch=False)==expected
    fetch.assert_awaited_once()
    assert await test_db.get(CollectionArtwork,'contract:8453:0x'+'a'*40)


async def test_failed_refresh_keeps_previous_image_without_extending_stale_deadline(test_db, monkeypatch):
    now=datetime.now(timezone.utc)
    deadline=now-timedelta(days=1)
    test_db.add(CollectionArtwork(key='slug:example',image_url='https://i.seadn.io/old.png',
        refresh_after=now-timedelta(seconds=1),stale_until=deadline))
    await test_db.commit()
    monkeypatch.setattr(OpenSeaClient,'_key',AsyncMock(return_value='server-only-test-key'))
    monkeypatch.setattr(OpenSeaClient,'_request',AsyncMock(side_effect=OpenSeaUnavailable('cooldown')))
    assert await artwork.collection_image('example',db=test_db)=='https://i.seadn.io/old.png'
    row=await test_db.get(CollectionArtwork,'slug:example',populate_existing=True)
    from app.services.mint_plans import aware
    assert aware(row.stale_until)==deadline


async def test_expired_artwork_remains_visible_during_minting_and_refreshes_later(test_db, monkeypatch):
    now = datetime.now(timezone.utc)
    test_db.add(CollectionArtwork(key='slug:example', image_url='https://i.seadn.io/old.png',
        refresh_after=now-timedelta(days=14), stale_until=now-timedelta(days=7)))
    await test_db.commit()
    request = AsyncMock(return_value=(200, {'collection': 'example', 'image_url': 'https://i.seadn.io/new.png'}))
    monkeypatch.setattr(OpenSeaClient, '_key', AsyncMock(return_value='server-only-test-key'))
    monkeypatch.setattr(OpenSeaClient, '_request', request)
    assert await artwork.collection_image('example', db=test_db, allow_fetch=False) == 'https://i.seadn.io/old.png'
    request.assert_not_awaited()
    assert await artwork.collection_image('example', db=test_db) == 'https://i.seadn.io/new.png'
    request.assert_awaited_once()


@pytest.fixture
async def artwork_copy(test_db):
    from types import SimpleNamespace
    now = datetime.now(timezone.utc)
    user = await test_db.scalar(select(User).where(User.username == 'member'))
    wallet = Wallet(user_id=user.id, label='Art test', address='0x'+'a'*40, signing_capability='custodial')
    test_db.add(wallet)
    await test_db.flush()
    grant = AutomaticGrant(user_id=user.id, wallet_id=wallet.id, chain_id=8453,
        account=wallet.address, context_hash='artwork-grant', scope={}, status='enabled',
        expires_at=now+timedelta(days=1), budget_wei=100)
    watch = CopyWatch(id='artwork-watch', user_id=user.id, address='0x'+'b'*40, label='Art test', chains=[8453])
    test_db.add_all([grant, watch])
    await test_db.flush()
    rule = CopyRule(user_id=user.id, watch_id=watch.id, grant_id=grant.id, chain_id=8453,
        snapshot={}, context_hash='artwork-rule', status='active', expires_at=now+timedelta(days=1),
        resume_after_block=10, budget_wei=100)
    event = CopyEvent(id='artwork-event', user_id=user.id, watch_id=watch.id, status='detected',
        observation={'chain_id': 8453, 'block_number': 11, 'start': int(now.timestamp())-60,
            'end': int((now+timedelta(days=300)).timestamp())})
    test_db.add_all([rule, event])
    await test_db.commit()
    return SimpleNamespace(user=user, wallet=wallet, grant=grant, watch=watch, rule=rule, event=event, now=now)


@pytest.mark.parametrize('state', ['ready', 'pending_ready', 'no_rule', 'paused_rule', 'revoked_rule',
    'expired_rule', 'archived_watch', 'paused_user', 'inactive_user', 'deleted_user', 'check_only',
    'other_chain', 'before_approval', 'pending_before_approval', 'retry_later', 'disabled_grant',
    'expired_grant', 'archived_wallet', 'phase_ended', 'phase_later'])
async def test_only_actionable_copies_defer_artwork(test_db, artwork_copy, state):
    c = artwork_copy
    if state == 'no_rule': await test_db.delete(c.rule)
    elif state == 'paused_rule': c.rule.status = 'paused'
    elif state == 'revoked_rule': c.rule.status = 'revoked'
    elif state == 'expired_rule': c.rule.expires_at = c.now-timedelta(seconds=1)
    elif state == 'archived_watch': c.watch.archived_at = c.now
    elif state == 'paused_user': c.user.automation_paused = True
    elif state == 'inactive_user': c.user.is_active = False
    elif state == 'deleted_user': c.user.deleted_at = c.now
    elif state == 'check_only': test_db.add(CopyCheck(watch_id=c.watch.id, user_id=c.user.id,
        wallet_id=c.wallet.id, version='artwork-check', snapshot={}, active=True, expires_at=c.now+timedelta(days=1)))
    elif state == 'other_chain': c.rule.chain_id = 1
    elif state == 'before_approval': c.rule.resume_after_block = 11
    elif state in ('pending_ready', 'pending_before_approval'):
        c.event.observation = {**c.event.observation, 'source_pending': True, 'block_number': 0,
            'seen_block': 11 if state == 'pending_ready' else 10}
    elif state == 'retry_later': c.event.next_attempt_at = c.now+timedelta(minutes=5)
    elif state == 'disabled_grant': c.grant.status = 'revoked'
    elif state == 'expired_grant': c.grant.expires_at = c.now-timedelta(seconds=1)
    elif state == 'archived_wallet': c.wallet.archived_at = c.now
    elif state == 'phase_ended': c.event.observation = {**c.event.observation, 'end': int(c.now.timestamp())-1}
    elif state == 'phase_later': c.event.observation = {**c.event.observation, 'start': int(c.now.timestamp())+300}
    await test_db.commit()
    assert await artwork.minting_busy(test_db) is (state in ('ready', 'pending_ready'))
    assert c.event.status == 'detected' and c.event.task_id is None


async def test_two_second_shared_capacity_preserves_twenty_second_mint_pacing(test_db,monkeypatch):
    from app.services import opensea_limits as limits
    from app.config import settings
    from sqlalchemy.ext.asyncio import async_sessionmaker
    monkeypatch.setattr(settings,'OPENSEA_COORDINATE_REQUESTS',True)
    monkeypatch.setattr(settings,'OPENSEA_GLOBAL_REQUEST_SECONDS',2)
    monkeypatch.setattr(settings,'OPENSEA_MINT_REQUEST_SECONDS',20)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    now=datetime.now(timezone.utc)
    assert await limits.acquire('/drops/a/mint',factory=factory,now=now)==(0,None)
    assert await limits.acquire('/collections/a',factory=factory,now=now)==(2,'paced')
    assert await limits.acquire('/collections/a',factory=factory,now=now+timedelta(seconds=2))==(0,None)
    assert await limits.acquire('/drops/b/mint',factory=factory,now=now+timedelta(seconds=4))==(16,'paced')


async def test_resolved_contract_survives_deferred_collection_lookup(test_db,monkeypatch):
    contract='0x'+'b'*40
    monkeypatch.setattr(OpenSeaClient,'_key',AsyncMock(return_value='server-only-test-key'))
    request=AsyncMock(side_effect=[
        (200,{'chain':'base','address':contract,'collection':'example'}),
        OpenSeaUnavailable('Shared queue'),
        (200,{'collection':'example','image_url':'https://i.seadn.io/resumed.png'})])
    monkeypatch.setattr(OpenSeaClient,'_request',request)
    assert await artwork.collection_image(chain_id=8453,contract=contract,db=test_db) is None
    row=await test_db.get(CollectionArtwork,artwork.artwork_key(None,8453,contract))
    assert row.collection_slug=='example'
    row.refresh_after=datetime.now(timezone.utc)-timedelta(seconds=1)
    await test_db.commit();artwork._cache.clear()
    assert await artwork.collection_image(chain_id=8453,contract=contract,db=test_db)=='https://i.seadn.io/resumed.png'
    assert [c.args[1] for c in request.await_args_list]==[
        f'/chain/base/contract/{contract}','/collections/example','/collections/example']
