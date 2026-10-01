"""Production rejects unsupported MetaMask signing; local contract tests differ."""

import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_db
from app.config import settings
from app.main import app
from app.models import MintPermission, MintPlan, User, Wallet
from app.services.auth import token_digest
from app.services.mint_permission import permission_typed_data
from app.services.wallet_signing_policy import MINT_SIGNING_UNAVAILABLE


def test_browser_never_requests_the_unsupported_signatures():
    node = shutil.which('node')
    assert node, 'Node is required for browser signing regression tests.'
    result = subprocess.run(
        [node, '--test', str(Path(__file__).with_name('authorize-mint.browser.cjs'))],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_production_blocks_raw_signing_but_preserves_plans_and_revocation(test_db, monkeypatch):
    monkeypatch.setattr(settings, 'APP_ENV', 'production')
    monkeypatch.setattr(settings, 'ENABLE_MINT_PERMISSIONS', True)
    monkeypatch.setattr(settings, 'ENABLE_DIRECT_WALLET_GAS', True)
    monkeypatch.setattr(settings, 'ENABLE_DIRECT_WALLET_BROADCAST', True)
    rpc = AsyncMock(side_effect=AssertionError('Unsupported signing must not access a live RPC.'))
    monkeypatch.setattr('app.api.mint_permissions.checked_provider', rpc)

    member = (await test_db.execute(select(User).where(User.username == 'member'))).scalar_one()
    address = '0x' + '1' * 40
    wallet = Wallet(user_id=member.id, address=address, label='MetaMask',
                    signing_capability='interactive', supported_chains=['Robinhood'], is_demo=False)
    test_db.add(wallet)
    await test_db.flush()
    now = datetime.now(timezone.utc)
    plan = MintPlan(user_id=member.id, wallet_id=wallet.id, collection_slug='saved',
                    quantity=1, collection_name='Saved', chain='Robinhood', chain_id=4663,
                    contract_address='0x' + '2' * 40, opensea_url='https://opensea.io/collection/saved',
                    status='ready_for_approval', starts_at=now, ends_at=now + timedelta(hours=1))
    test_db.add(plan)
    await test_db.flush()
    execution = {'target': '0x' + '3' * 40, 'value': '0', 'data': '0x1234'}
    code = 'a' * 32
    permission = MintPermission(
        user_id=member.id, plan_id=plan.id, code_hash=token_digest(code),
        typed_data=permission_typed_data(4663, address, address, execution, int(now.timestamp()), int(now.timestamp()) + 300),
        execution=execution, status='awaiting_signature', expires_at=now + timedelta(minutes=5),
        execute_after=now, signature_deadline=now + timedelta(minutes=5),
    )
    test_db.add(permission)
    await test_db.commit()

    async def override():
        yield test_db
    app.dependency_overrides[get_db] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='https://test') as client:
            login = await client.post('/api/auth/login', json={'username': 'member', 'password': 'Member test password 123'})
            client.headers['Authorization'] = 'Bearer ' + login.json()['token']
            routes = [
                ('/api/mint-permissions', {'plan_id': plan.id, 'max_mint_value_wei': '0'}),
                ('/api/mint-permission-link/challenge', {'code': code}),
                ('/api/mint-permission-link/prepare-userop', {'code': code, 'signature': '0x' + '1' * 130}),
                ('/api/mint-permission-link/complete', {'code': code, 'signature': '0x' + '1' * 130}),
            ]
            for route, body in routes:
                result = await client.post(route, json=body)
                assert result.status_code == 409
                assert result.json()['detail'] == MINT_SIGNING_UNAVAILABLE
                assert 'typed_data' not in result.json()
            rpc.assert_not_awaited()
            assert permission.status == 'awaiting_signature' and permission.signature is None
            plans = await client.get('/api/mint-plans')
            assert plans.status_code == 200 and plans.json()[0]['id'] == plan.id
            cancel = await client.post(f'/api/mint-permissions/{permission.id}/cancel')
            assert cancel.status_code == 200 and cancel.json()['can_revoke'] is False

            # Previously signed requests remain revocable even after activation is off.
            permission.signature = '0x' + '1' * 130
            await test_db.commit()
            monkeypatch.setattr(settings, 'ENABLE_MINT_PERMISSIONS', False)
            revoke = await client.post(f'/api/mint-permissions/{permission.id}/revocation')
            challenge = await client.post('/api/mint-permission-link/challenge', json={'code': revoke.json()['code']})
            assert challenge.status_code == 200 and challenge.json()['mode'] == 'revoke'
            assert challenge.json()['transaction']['value'] == '0x0'
            assert 'typed_data' not in challenge.json()
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_production_workers_cannot_be_activated_with_old_flags(monkeypatch):
    from app.services.permission_relayer import process_one_permission
    from app.services.direct_wallet_worker import process_direct_permission

    monkeypatch.setattr(settings, 'APP_ENV', 'production')
    monkeypatch.setattr(settings, 'ENABLE_MINT_PERMISSIONS', True)
    monkeypatch.setattr(settings, 'ENABLE_DIRECT_WALLET_GAS', True)
    monkeypatch.setattr(settings, 'ENABLE_DIRECT_WALLET_BROADCAST', True)
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    await process_one_permission(db)
    await process_direct_permission(db, None, None, None, 'robinhood')
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()
