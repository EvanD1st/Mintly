"""Independent-session regressions for atomic owner-aware device registration."""
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.sql.dml import Insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.main import app
from app.api.deps import get_db
from app.models.activity import NotificationDevice


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
        if isinstance(statement,Insert) and statement.table.name==NotificationDevice.__tablename__:
            arrived+=1
            if arrived==2:ready.set()
            await asyncio.wait_for(ready.wait(),10)
        return await original(self,statement,*args,**kwargs)
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
