"""Recovery never changes passwords, transfers admin identity, or reuses codes."""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.api.auth import LoginRequest, authenticate_password
from app.api.deps import get_db
from app.config import settings
from app.main import app
from app.models import AccountRecoveryCode, ActivityEvent, AuthSession, DeviceSession, LoginAttempt, User
from app.services.auth import token_digest, verify_password


@pytest.fixture
async def client(test_db):
    async def dep():
        try:
            yield test_db
            await test_db.commit()
        except Exception:
            await test_db.rollback()
            raise
    app.dependency_overrides[get_db] = dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def credentials(client, username='admin'):
    r = await client.post('/api/auth/device-login', json={'username': username,
        'password': ('Admin' if username == 'admin' else 'Member') + ' test password 123',
        'origin': settings.PUBLIC_URL + '/api', 'protocol': 2})
    assert r.status_code == 200, r.text
    return r.json()


async def issue(client, test_db, admin=None):
    admin = admin or await credentials(client)
    member_id = await test_db.scalar(select(User.id).where(User.username == 'member'))
    r = await client.post(f'/api/admin/users/{member_id}/recovery-code',
        headers={'Authorization': 'Bearer ' + admin['token']},
        json={'admin_password': 'Admin test password 123'})
    assert r.status_code == 200, r.text
    assert r.headers['cache-control'] == 'no-store'
    return r.json(), admin


async def redeem(client, code, *, remembered=True, username='member', origin=None):
    body = {'username': username, 'password': code}
    if remembered:
        body.update(origin=origin or settings.PUBLIC_URL + '/api', protocol=2)
    return await client.post('/api/auth/' + ('device-login' if remembered else 'login'), json=body)


@pytest.mark.parametrize('remembered', [True, False])
async def test_single_use_password_unchanged_and_admin_kept(client, test_db, remembered):
    member = await test_db.scalar(select(User).where(User.username == 'member'))
    original_hash = member.password_hash
    original_session = await credentials(client, 'member')
    data, admin = await issue(client, test_db)
    code = data['recovery_code']
    row = await test_db.scalar(select(AccountRecoveryCode))
    assert row.code_hash == token_digest(code) and code not in row.code_hash
    assert 599 <= (row.expires_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds() <= 600
    r = await redeem(client, code, remembered=remembered)
    assert r.status_code == 200, r.text
    assert r.json()['user']['id'] == member.id and r.json()['user']['role'] == 'member'
    assert r.json()['user']['must_change_password'] is False
    if remembered:
        assert (await test_db.get(DeviceSession, r.json()['device_session_id'])).user_id == member.id
    assert (await redeem(client, code)).status_code == 401
    await test_db.refresh(member)
    assert member.password_hash == original_hash and verify_password(member.password_hash, 'Member test password 123')
    for data in (admin, original_session):
        me = await client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + data['token']})
        assert me.status_code == 200 and me.json()['id'] == data['user']['id']
    events = (await test_db.execute(select(ActivityEvent).where(ActivityEvent.event_type.like('account_recovery_%')))).scalars().all()
    assert len(events) == 4 and {e.user_id for e in events} == {admin['user']['id'], member.id}
    assert all(code not in e.detail for e in events)
    assert (await client.post('/api/auth/login', json={'username': 'member', 'password': 'Member test password 123'})).status_code == 200


async def test_reissue_revokes_old_code_and_wrong_user_cannot_consume(client, test_db):
    first, admin = await issue(client, test_db)
    second, _ = await issue(client, test_db, admin)
    assert (await redeem(client, first['recovery_code'])).status_code == 401
    assert (await redeem(client, second['recovery_code'], username='admin')).status_code == 401
    assert (await redeem(client, second['recovery_code'])).status_code == 200


@pytest.mark.parametrize('reason', ['expired', 'revoked', 'disabled', 'deleted', 'issuer_disabled', 'issuer_demoted', 'issuer_deleted', 'password_change_required'])
async def test_invalid_state_does_not_issue_session(client, test_db, reason):
    data, admin = await issue(client, test_db)
    member = await test_db.scalar(select(User).where(User.username == 'member'))
    issuer = await test_db.get(User, admin['user']['id'])
    row = await test_db.scalar(select(AccountRecoveryCode))
    if reason == 'expired': row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif reason == 'revoked': row.revoked_at = datetime.now(timezone.utc)
    elif reason == 'disabled': member.is_active = False
    elif reason == 'deleted': member.deleted_at = datetime.now(timezone.utc)
    elif reason == 'issuer_disabled': issuer.is_active = False
    elif reason == 'issuer_demoted': issuer.role = 'member'
    elif reason == 'issuer_deleted': issuer.deleted_at = datetime.now(timezone.utc)
    else: member.must_change_password = True
    await test_db.commit()
    before = await test_db.scalar(select(func.count()).select_from(AuthSession))
    assert (await redeem(client, data['recovery_code'])).status_code == 401
    assert await test_db.scalar(select(func.count()).select_from(AuthSession)) == before
    row = await test_db.scalar(select(AccountRecoveryCode))
    assert row.used_at is None


async def test_valid_code_recovers_locked_account_invalid_code_cannot(client, test_db):
    data, _ = await issue(client, test_db)
    for _ in range(5):
        assert (await redeem(client, 'wrong password')).status_code == 401
    assert (await redeem(client, 'Member test password 123')).status_code == 429
    assert (await redeem(client, 'MRC-' + 'z' * 32)).status_code == 429
    assert (await redeem(client, data['recovery_code'])).status_code == 200
    assert await test_db.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.username_hash == hashlib.sha256(b'member').hexdigest())) == 0


async def test_wrong_origin_and_issuance_failure_do_not_consume(client, test_db, monkeypatch):
    data, _ = await issue(client, test_db)
    assert (await redeem(client, data['recovery_code'], origin='https://other.example/api')).status_code == 400
    monkeypatch.setattr(settings, 'REMEMBERED_LOGIN_ISSUANCE_ENABLED', False)
    assert (await redeem(client, data['recovery_code'])).status_code == 503
    row = await test_db.scalar(select(AccountRecoveryCode))
    assert row.used_at is None
    monkeypatch.setattr(settings, 'REMEMBERED_LOGIN_ISSUANCE_ENABLED', True)
    assert (await redeem(client, data['recovery_code'])).status_code == 200


async def test_cancelled_device_save_keeps_only_ordinary_member_session(client, test_db):
    data, admin = await issue(client, test_db)
    saved = (await redeem(client, data['recovery_code'])).json()
    response = await client.post('/api/auth/session-only', headers={'Authorization': 'Bearer ' + saved['token']})
    assert response.status_code == 200, response.text
    assert response.json()['user']['id'] == saved['user']['id']
    assert 'refresh_token' not in response.json()
    token = response.json()['token']
    current = await test_db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(token)))
    assert current.device_session_id is None
    assert (await test_db.get(DeviceSession, saved['device_session_id'])).revoked_at is not None
    assert (await client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + token})).status_code == 200
    assert (await client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + saved['token']})).status_code == 401
    assert (await client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + admin['token']})).json()['role'] == 'admin'
    assert (await client.post('/api/auth/session-only')).status_code == 401
    assert (await redeem(client, data['recovery_code'])).status_code == 401


async def test_issue_requires_admin_and_fresh_password_and_limits_failures(client, test_db):
    admin = await credentials(client)
    member = await credentials(client, 'member')
    path = f"/api/admin/users/{member['user']['id']}/recovery-code"
    assert (await client.post(path, json={'admin_password': 'wrong'})).status_code == 401
    assert (await client.post(path, headers={'Authorization': 'Bearer ' + member['token']},
        json={'admin_password': 'Admin test password 123'})).status_code == 403
    headers = {'Authorization': 'Bearer ' + admin['token']}
    for _ in range(5):
        assert (await client.post(path, headers=headers, json={'admin_password': 'wrong'})).status_code == 403
    assert (await client.post(path, headers=headers, json={'admin_password': 'Admin test password 123'})).status_code == 429
    assert await test_db.scalar(select(func.count()).select_from(AccountRecoveryCode)) == 0


async def test_cannot_issue_for_admin_inactive_or_initial_password(client, test_db):
    admin = await credentials(client)
    headers = {'Authorization': 'Bearer ' + admin['token']}
    body = {'admin_password': 'Admin test password 123'}
    assert (await client.post(f"/api/admin/users/{admin['user']['id']}/recovery-code", headers=headers, json=body)).status_code == 404
    member = await test_db.scalar(select(User).where(User.username == 'member'))
    member.must_change_password = True
    await test_db.commit()
    assert (await client.post(f'/api/admin/users/{member.id}/recovery-code', headers=headers, json=body)).status_code == 404
    member.must_change_password = False
    member.is_active = False
    await test_db.commit()
    assert (await client.post(f'/api/admin/users/{member.id}/recovery-code', headers=headers, json=body)).status_code == 404


@pytest.mark.parametrize('action', ['logout', 'change-password', 'reset-password', 'delete', 'issuer_logout'])
async def test_account_revocation_invalidates_unused_code(client, test_db, action):
    member = await credentials(client, 'member')
    data, admin = await issue(client, test_db)
    auth = {'Authorization': 'Bearer ' + member['token']}
    if action in ('logout', 'issuer_logout'):
        if action == 'issuer_logout': auth = {'Authorization': 'Bearer ' + admin['token']}
        r = await client.post('/api/auth/logout', headers=auth)
    elif action == 'change-password':
        r = await client.post('/api/auth/change-password', headers=auth,
            json={'current_password': 'Member test password 123', 'new_password': 'New member password 123'})
    else:
        r = await client.post(f"/api/admin/users/{member['user']['id']}/{action}",
            headers={'Authorization': 'Bearer ' + admin['token']}, json={'admin_password': 'Admin test password 123'})
    assert r.status_code == 200, r.text
    assert (await redeem(client, data['recovery_code'])).status_code == 401


async def test_concurrent_redemption_has_one_winner(client, test_db):
    if test_db.bind.dialect.name != 'postgresql':
        pytest.skip('Independent concurrent recovery requires PostgreSQL row locking.')
    data, _ = await issue(client, test_db)
    factory = async_sessionmaker(test_db.bind, expire_on_commit=False)
    async def attempt():
        async with factory() as db:
            try:
                result = await authenticate_password(LoginRequest(username='member', password=data['recovery_code']), db)
                return result['user']['username']
            except HTTPException as exc:
                await db.rollback()
                return exc.status_code
    assert sorted(await asyncio.gather(attempt(), attempt()), key=str) == [401, 'member']
