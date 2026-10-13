"""Explicitly expose a known device-registration race; never hide it as a pass."""
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.main import app
from app.api.deps import get_db
from app.models.activity import NotificationDevice


@pytest.mark.xfail(strict=True, reason='Known defect: simultaneous first device registrations return 200/500 instead of two idempotent successes.')
async def test_simultaneous_device_registration_is_idempotent(test_db, monkeypatch):
    if test_db.bind.dialect.name != 'postgresql':
        pytest.skip('Deterministic independent-session race requires disposable PostgreSQL.')
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    async def dependency():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db]=dependency
    arrived=0;ready=asyncio.Event()
    original=AsyncSession.execute
    async def synchronized(self, statement, *args, **kwargs):
        nonlocal arrived
        result=await original(self,statement,*args,**kwargs)
        if isinstance(statement,Select) and any(d.get('entity') is NotificationDevice
                for d in statement.column_descriptions):
            arrived+=1
            if arrived==2:ready.set()
            await asyncio.wait_for(ready.wait(),10)
        return result
    try:
        async with AsyncClient(transport=ASGITransport(app=app,raise_app_exceptions=False),base_url='http://test') as client:
            login=await client.post('/api/auth/login',json={'username':'member','password':'Member test password 123'})
            assert login.status_code==200
            client.headers['Authorization']='Bearer '+login.json()['token']
            monkeypatch.setattr(AsyncSession,'execute',synchronized)
            responses=await asyncio.gather(*(client.post('/api/notifications/register',json={
                'token':'disposable-concurrent-registration-token'}) for _ in range(2)))
            assert sorted(r.status_code for r in responses)==[200,200]
    finally:
        app.dependency_overrides.pop(get_db,None)
