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
        async def discovery_checks():
            from app.models import FeedWalletCheck, Drop, Wallet
            from app.services import feed_checks
            # The local chain is advertised only inside this disposable test.
            monkeypatch.setattr(feed_checks,'supported',lambda d:d.chain_id==31337)
            from datetime import datetime,timezone
            monkeypatch.setattr(OpenSeaClient,'get_drop',AsyncMock(return_value={'chain':'local',
                'contract_address':instance.nft.address,'stages':[{'uuid':'local-public','label':'Public',
                    'stage_type':'public_sale','start_time':datetime.fromtimestamp(instance.start,timezone.utc).isoformat(),
                    'end_time':datetime.fromtimestamp(instance.end,timezone.utc).isoformat(),'price':'10',
                    'max_per_wallet':'20','price_currency_address':'0x'+'0'*40}]}))
            from app.services.opensea import CHAINS
            monkeypatch.setitem(CHAINS,'local',(31337,'Local test'))
            async with instance.factory() as db:
                from app.models import User
                owner=await db.get(User,instance.user.id)
                wallet=await db.get(Wallet,instance.wallet.id)
                drop=await db.scalar(select(Drop).where(Drop.contract_address==instance.nft.address))
                drop.mint_page_url='https://opensea.io/collection/local-test'
                await db.commit()
                await feed_checks.queue_checks(db,owner,wallet,[drop])
            assert await feed_checks.step(instance.factory)
            async with instance.factory() as db:
                row=await db.get(FeedWalletCheck,(instance.user.id,instance.wallet.id,drop.id))
                assert row.status=='complete' and row.result['address']==instance.wallet.address
                assert row.result['stages'][0]['eligibility']=='eligible'
                assert row.result['stages'][0]['remaining'] is not None
        await asyncio.gather(*(read(path) for path in paths for _ in range(3)),logins(),device_settings(),discovery_checks(),scenario)
        # After simultaneous preparation, verify all nominal screen APIs again.
        await asyncio.gather(*(read(path) for path in paths))
        assert metadata_calls==1, 'Cached artwork must not issue repeated provider requests.'
    finally:
        release.set()
        if not scenario.done():
            scenario.cancel()
            await asyncio.gather(scenario,return_exceptions=True)


async def test_remaining_feature_contracts_and_session_revocation(lab,monkeypatch):
    """Separate incompatible mutations from the mixed signer workload."""
    import socket
    original_dns=socket.getaddrinfo
    def dns(host,*args,**kwargs):
        if host=='opensea.io':
            return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
        return original_dns(host,*args,**kwargs)
    monkeypatch.setattr(socket,'getaddrinfo',dns)
    login=await lab.client.post('/api/auth/login',json={'username':'admin','password':'Admin test password 123'})
    admin={'Authorization':'Bearer '+login.json()['token']}
    assert (await lab.client.get('/')).status_code==200
    assert (await lab.signer_client.get('/readyz')).json()['status']=='ready'
    assert (await lab.client.get(f'/api/wallets/{lab.wallet.id}/opensea-access')).json()['enabled'] is False
    # The old web pairing feature is retired; polling must reject a missing record.
    assert (await lab.client.get('/api/wallets/pairings/missing')).status_code==404
    for expected in (False,True):
        toggle=await lab.client.post('/api/source/toggle',headers=admin)
        assert toggle.status_code==200 and toggle.json()['is_monitoring'] is expected
    imported=await lab.client.post('/api/drops/import',headers=admin,json={
        'raw_content':'https://opensea.io/collection/disposable-audit'})
    assert imported.status_code==200,imported.text
    drops=(await lab.client.get('/api/drops')).json()['drops']
    assert len(drops)==1 and drops[0]['is_supported_integration'] is False
    recheck=await lab.client.post(f"/api/drops/{drops[0]['id']}/recheck?wallet_id={lab.wallet.id}")
    assert recheck.status_code==409 and 'cannot be verified' in recheck.json()['detail']
    # Real broker transport/validation; its authenticated provider is controlled.
    async def stages(db,wallet_id,operation,*,slug,key):
        assert (wallet_id,operation,slug,key)==(lab.wallet.id,'stages','disposable-audit','disposable-audit-api-key')
        return {'stages':[]}
    monkeypatch.setattr('app.services.opensea_identity.connection',stages)
    stage_response=await lab.signer_client.post(f'/opensea/{lab.wallet.id}/stages/disposable-audit',
        json={'api_key':'disposable-audit-api-key'})
    assert stage_response.status_code==200 and stage_response.json()=={'stages':[]}
    assert (await lab.client.post('/api/auth/logout')).status_code==200
    assert (await lab.client.get('/api/auth/me')).status_code==401
    deleted=await lab.client.post(f'/api/admin/users/{lab.user.id}/delete',headers=admin,
        json={'admin_password':'Admin test password 123'})
    assert deleted.status_code==200
    assert (await lab.client.post('/api/auth/login',json={
        'username':'member','password':'Member test password 123'})).status_code==401
