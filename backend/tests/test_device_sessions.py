"""Real rotating families, recoverable responses and owner revocation."""
import asyncio
from datetime import datetime,timezone,timedelta
from httpx import ASGITransport,AsyncClient
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import async_sessionmaker
from fastapi import HTTPException
import pytest
from app.models import DeviceSession,DeviceRefreshUse,AuthSession,User
from app.api.deps import get_db
from app.main import app
from app.config import settings
from app.services.device_sessions import rotate

@pytest.fixture
async def client(test_db):
    async def dep():yield test_db
    app.dependency_overrides[get_db]=dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:yield client
    finally:app.dependency_overrides.pop(get_db,None)

async def remembered(client,username='member'):
    r=await client.post('/api/auth/device-login',json={'username':username,
        'password':('Admin' if username=='admin' else 'Member')+' test password 123',
        'origin':settings.PUBLIC_URL+'/api','protocol':2})
    assert r.status_code==200,r.text
    return r.json()

def request(data,request_id='disposable-refresh-request-'+'a'*32):
    return {k:data[k] for k in ('device_session_id','refresh_token','origin')}|{'request_id':request_id}

async def test_rotation_lost_response_same_request_and_reuse_revoke(client,test_db):
    original=await remembered(client)
    first=await client.post('/api/auth/device-refresh',json=request(original));assert first.status_code==200
    retry=await client.post('/api/auth/device-refresh',json=request(original));assert retry.json()==first.json()
    assert first.json()['refresh_token']!=original['refresh_token']
    assert await test_db.scalar(select(func.count()).select_from(DeviceRefreshUse))==1
    assert (await client.get('/api/auth/me',headers={'Authorization':'Bearer '+first.json()['token']})).status_code==200
    changed=await client.post('/api/auth/device-refresh',json=request(original,'different-refresh-request-'+'b'*32))
    assert changed.status_code==401
    assert (await client.get('/api/auth/me',headers={'Authorization':'Bearer '+first.json()['token']})).status_code==401
    assert (await client.post('/api/auth/device-refresh',json=request(first.json()))).status_code==401

async def test_local_sign_out_retires_only_bearer_and_preserves_remembered_accounts(client,test_db):
    saved=await remembered(client)
    other=await remembered(client)
    admin=await remembered(client,'admin')
    auth={'Authorization':'Bearer '+saved['token']}
    assert (await client.post('/api/auth/sign-out',json={},headers=auth)).status_code==200
    assert (await client.get('/api/auth/me',headers=auth)).status_code==401
    assert (await client.get('/api/auth/me',headers={'Authorization':'Bearer '+other['token']})).status_code==200
    assert (await client.get('/api/auth/me',headers={'Authorization':'Bearer '+admin['token']})).status_code==200
    assert not (await test_db.get(DeviceSession,saved['device_session_id'])).revoked_at
    rotated=await client.post('/api/auth/device-refresh',json=request(saved))
    assert rotated.status_code==200
    # Explicit account-wide logout still revokes all remembered families.
    assert (await client.post('/api/auth/logout',headers={'Authorization':'Bearer '+rotated.json()['token']})).status_code==200
    assert (await client.post('/api/auth/device-refresh',json=request(other))).status_code==401

async def test_local_sign_out_ordinary_and_unauthenticated(client):
    login=await client.post('/api/auth/login',json={'username':'member','password':'Member test password 123'})
    auth={'Authorization':'Bearer '+login.json()['token']}
    assert (await client.post('/api/auth/sign-out',headers=auth)).status_code==200
    assert (await client.get('/api/auth/me',headers=auth)).status_code==401
    assert (await client.post('/api/auth/sign-out')).status_code==401

async def test_recovery_window_exact_boundary_and_history_replays(client,test_db):
    data=await remembered(client);now=datetime.now(timezone.utc)
    one=await rotate(test_db,**dict(family_id=data['device_session_id'],refresh=data['refresh_token'],
        request_id='a'*40,origin=data['origin'],now=now))
    assert (await rotate(test_db,data['device_session_id'],data['refresh_token'],'a'*40,data['origin'],now=now+timedelta(seconds=30)))['refresh_token']==one['refresh_token']
    with pytest.raises(HTTPException):
        await rotate(test_db,data['device_session_id'],data['refresh_token'],'a'*40,data['origin'],now=now+timedelta(seconds=30,microseconds=1))
    row=await test_db.get(DeviceSession,data['device_session_id']);assert row.revoked_at

async def test_old_generation_and_wrong_secret_do_not_strand_unrelated_account(client,test_db):
    a=await remembered(client);b=await remembered(client,'admin')
    one=(await client.post('/api/auth/device-refresh',json=request(a))).json()
    two=(await client.post('/api/auth/device-refresh',json=request(one,'b'*40))).json()
    wrong=await client.post('/api/auth/device-refresh',json={**request(b),'refresh_token':'z'*43})
    assert wrong.status_code==401 and not (await test_db.get(DeviceSession,b['device_session_id'])).revoked_at
    assert (await client.post('/api/auth/device-refresh',json=request(a))).status_code==401
    assert (await client.get('/api/auth/me',headers={'Authorization':'Bearer '+two['token']})).status_code==401
    assert (await client.get('/api/auth/me',headers={'Authorization':'Bearer '+b['token']})).status_code==200

async def test_ninety_day_inactivity_and_current_lifetimes(client,test_db):
    for name,hours in (('admin',12),('member',168)):
        data=await remembered(client,name);row=await test_db.get(DeviceSession,data['device_session_id'])
        assert 90*86400-1<=(row.expires_at.replace(tzinfo=timezone.utc)-row.last_used_at.replace(tzinfo=timezone.utc)).total_seconds()<=90*86400
        assert hours*3600-1<=(row.access_expires_at.replace(tzinfo=timezone.utc)-row.last_used_at.replace(tzinfo=timezone.utc)).total_seconds()<=hours*3600
        row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);await test_db.commit()
        assert (await client.post('/api/auth/device-refresh',json=request(data))).status_code==401

@pytest.mark.parametrize('action',['logout','change-password','reset-password','disable','delete'])
async def test_account_wide_actions_revoke_remembering(client,test_db,action):
    data=await remembered(client)
    if action in ('logout','change-password'):
        body={} if action=='logout' else {'current_password':'Member test password 123','new_password':'Changed password long 123'}
        assert (await client.post('/api/auth/'+action,json=body,headers={'Authorization':'Bearer '+data['token']})).status_code==200
    elif action=='disable':
        row=await test_db.get(User,data['user']['id']);row.is_active=False;await test_db.commit()
    else:
        admin=await remembered(client,'admin')
        assert (await client.post('/api/admin/users/'+data['user']['id']+'/'+action,
            headers={'Authorization':'Bearer '+admin['token']},json={'admin_password':'Admin test password 123'})).status_code==200
    assert (await client.post('/api/auth/device-refresh',json=request(data))).status_code==401
    row=await test_db.get(DeviceSession,data['device_session_id']);await test_db.refresh(row);assert row.revoked_at

async def test_origin_rollback_and_existing_session_migration(client,test_db,monkeypatch):
    legacy=await client.post('/api/auth/login',json={'username':'member','password':'Member test password 123'})
    assert 'refresh_token' not in legacy.json()
    token=legacy.json()['token']
    data=await client.post('/api/auth/device-remember',headers={'Authorization':'Bearer '+token},json={'origin':settings.PUBLIC_URL+'/api'})
    assert data.status_code==200 and (await client.get('/api/auth/me',headers={'Authorization':'Bearer '+token})).status_code==200
    assert (await client.post('/api/auth/device-refresh',json={**request(data.json()),'origin':'https://other.example/api'})).status_code==400
    monkeypatch.setattr(settings,'REMEMBERED_LOGIN_ISSUANCE_ENABLED',False)
    assert (await client.post('/api/auth/device-remember',headers={'Authorization':'Bearer '+token},json={'origin':settings.PUBLIC_URL+'/api'})).status_code==503
    assert (await client.post('/api/auth/device-refresh',json=request(data.json()))).status_code==200
    assert (await client.post('/api/auth/login',json={'username':'member','password':'Member test password 123'})).status_code==200

async def test_simultaneous_rotation_independent_sessions(test_db,client):
    if test_db.bind.dialect.name!='postgresql':pytest.skip('Independent concurrent rotation uses PostgreSQL row locking.')
    data=await remembered(client);factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    async def refresh():
        async with factory() as db:return await rotate(db,data['device_session_id'],data['refresh_token'],'r'*40,data['origin'])
    first,second=await asyncio.gather(refresh(),refresh())
    assert first==second
    async with factory() as db:assert await db.scalar(select(func.count()).select_from(DeviceRefreshUse))==1
