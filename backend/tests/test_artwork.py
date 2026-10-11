import asyncio
from unittest.mock import AsyncMock
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.api import artwork
from app.api.deps import get_db
from app.main import app
from app.models import User, Wallet, MintPlan, OpenSeaRequestWaiter
from datetime import datetime, timezone, timedelta
from app.services.opensea import OpenSeaClient, OpenSeaUnavailable


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
    finally:
        app.dependency_overrides.pop(get_db, None)
