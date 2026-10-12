"""Concurrent UI features while three real copies and one automatic task sign."""
import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace

from app.services.opensea import OpenSeaClient
from test_automatic_evm import lab
from test_copy_mints import copying
from test_copy_presales import test_three_user_copies_and_automatic_mint_prepare_concurrently as run_four


async def test_mixed_feature_reads_and_writes_during_four_wallet_preparation(copying,monkeypatch):
    c=copying;instance=c['lab']
    from app.api import artwork
    artwork._cache.clear()
    metadata_calls=0
    monkeypatch.setattr(OpenSeaClient,'_key',AsyncMock(return_value='disposable-artwork-key'))
    async def metadata(*args,**kwargs):
        nonlocal metadata_calls
        metadata_calls+=1
        await asyncio.sleep(.01)
        return 200,{'collection':'local-test','image_url':'https://i.seadn.io/local-test.png'}
    monkeypatch.setattr(OpenSeaClient,'_request',metadata)
    from app.services import automatic
    original_provider=automatic.provider_for
    async def balance(*args):
        await asyncio.sleep(.02)
        return 10**18
    async def provider(chain):
        if chain==31337:return await original_provider(chain)
        return SimpleNamespace(eth=SimpleNamespace(get_balance=balance),
            provider=SimpleNamespace(disconnect=AsyncMock()))
    monkeypatch.setattr(automatic,'provider_for',provider)
    arrived=0;ready=asyncio.Event();release=asyncio.Event()
    original=instance.sign
    async def coordinated(task_id):
        nonlocal arrived
        arrived+=1
        if arrived==4:ready.set()
        await release.wait()
        return await original(task_id)
    monkeypatch.setattr(instance,'sign',coordinated)
    login=await instance.client.post('/api/auth/login',json={'username':'admin','password':'Admin test password 123'})
    admin_headers={'Authorization':'Bearer '+login.json()['token']}
    scenario=asyncio.create_task(run_four(c,monkeypatch))
    try:
        await asyncio.wait_for(ready.wait(),90)
        from sqlalchemy import select
        from app.models import CopyEvent
        async with instance.factory() as db:
            event_id=await db.scalar(select(CopyEvent.id).where(CopyEvent.watch_id==c['watch_id']))
            # Fetch once, then exercise the persisted artwork while preparation is urgent.
            assert await artwork.collection_image('local-test',chain_id=31337,
                contract=instance.nft.address,db=db)=='https://i.seadn.io/local-test.png'
        paths=['/healthz','/api/auth/me','/api/wallets','/api/wallets/readiness','/api/automatic/status',
            '/api/automatic/daily-limit','/api/automatic/policies','/api/mint-plans',
            '/api/tasks/queue','/api/mint-permissions','/api/copy-mints','/api/copy-mints/activity',
            '/api/copy-mints/check-results','/api/history','/api/notifications/recent',
            '/api/source/status','/api/activity','/api/drops',
            f'/api/artwork?reference=copy:{event_id}']
        async def read(path):
            response=await instance.client.get(path,headers=admin_headers if path in
                ('/api/notifications/recent','/api/source/status') else {})
            assert response.status_code==200,(path,response.status_code,response.text)
            if path.startswith('/api/artwork'):
                assert response.json()['image_url']=='https://i.seadn.io/local-test.png'
        async def logins():
            # Additional logins do not revoke the established session.
            for _ in range(3):
                r=await instance.client.post('/api/auth/login',json={
                    'username':'member','password':'Member test password 123'})
                assert r.status_code==200
        async def device_settings():
            token='disposable-mixed-feature-device-token'
            for path,body in [('register',{'token':token}),('preferences',{'token':token,'daily_list':False}),
                              ('unregister',{'token':token})]:
                r=await instance.client.post('/api/notifications/'+path,json=body)
                assert r.status_code==200
        release.set()
        await asyncio.gather(*(read(path) for path in paths for _ in range(3)),logins(),device_settings(),scenario)
        # After simultaneous preparation, verify all nominal screen APIs again.
        await asyncio.gather(*(read(path) for path in paths))
        assert metadata_calls==1, 'Cached artwork must not issue repeated provider requests.'
    finally:
        release.set()
        if not scenario.done():
            scenario.cancel()
            await asyncio.gather(scenario,return_exceptions=True)
