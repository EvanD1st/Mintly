from httpx import ASGITransport, AsyncClient
from datetime import datetime, timezone
from sqlalchemy import select, func
from app.api.deps import get_db
from app.main import app
from app.models import Drop, DismissedDrop, SourcePost


async def test_today_removal_persists_per_user_without_deleting_shared_drop(test_db):
    post = SourcePost(id='source', post_id='manual', full_text='Test list',
        posted_at=datetime.now(timezone.utc), is_manual_import=True)
    test_db.add(post)
    await test_db.flush()
    test_db.add(Drop(id='drop', source_post_id=post.id, name='Test drop', mint_page_url='https://example.org'))
    await test_db.commit()
    async def db_override(): yield test_db
    app.dependency_overrides[get_db] = db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            login = await client.post('/api/auth/login', json={'username':'member','password':'Member test password 123'})
            member = {'Authorization':'Bearer '+login.json()['token']}
            login = await client.post('/api/auth/login', json={'username':'admin','password':'Admin test password 123'})
            admin = {'Authorization':'Bearer '+login.json()['token']}
            assert len((await client.get('/api/drops', headers=member)).json()['drops']) == 1
            for _ in range(2):
                removed = await client.delete('/api/drops/drop', headers=member)
                assert removed.status_code == 200 and removed.json()['plans_and_history_retained']
            for kind in ('all','unknown','manual'):
                assert (await client.get('/api/drops', params={'filter_kind':kind}, headers=member)).json()['drops'] == []
            assert len((await client.get('/api/drops', headers=admin)).json()['drops']) == 1
            assert (await client.get('/api/drops/drop', headers=member)).status_code == 200
            assert (await client.delete('/api/drops/missing', headers=member)).status_code == 404
            assert (await client.delete('/api/drops/drop')).status_code == 401
            assert await test_db.scalar(select(func.count()).select_from(DismissedDrop)) == 1
            assert await test_db.get(Drop, 'drop') is not None
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_x_session_diagnostics_are_admin_only(test_db):
    async def db_override(): yield test_db
    app.dependency_overrides[get_db] = db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            for username, password, allowed in [('member','Member test password 123',False),('admin','Admin test password 123',True)]:
                login = await client.post('/api/auth/login', json={'username':username,'password':password})
                headers = {'Authorization':'Bearer '+login.json()['token']}
                feed = (await client.get('/api/drops', headers=headers)).json()
                assert bool(feed['source_status_text']) == allowed
                status = await client.get('/api/source/status', headers=headers)
                assert status.status_code == (200 if allowed else 403)
                if allowed: assert 'X session' in feed['source_status_text']
            assert (await client.get('/api/source/status')).status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)
