"""Persistent key, cross-worker permits, protected caches and finite retry windows."""
import asyncio,json,os,time,uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
import httpx,pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.config import settings
from app.models import OpenSeaRequestGate,MintTask,MintAuthorization,AutomaticGrant
from app.services import opensea_limits as limits,mint_instruction_cache as cache,mint_diagnostics as diag
from app.services.opensea import OpenSeaClient,OpenSeaUnavailable,remember_verified_mint
from app.services.automatic_signer import preflight_task,_preflights
from app.services.custody import CustodyVault
from app.automatic_worker import step
from test_automatic_evm import lab


def stored_key(path,expiry):
    path.write_text(json.dumps({'api_key':'disposable-shared-api-key-12345','expires_at':expiry.isoformat()}))


async def test_read_only_clients_reuse_persistent_key_after_client_restart(tmp_path,monkeypatch):
    path=tmp_path/'key.json';stored_key(path,datetime.now(timezone.utc)+timedelta(days=6))
    monkeypatch.setattr(settings,'OPENSEA_KEY_FILE',str(path));monkeypatch.setattr(settings,'OPENSEA_KEY_READ_ONLY',True)
    async def unexpected(*args,**kwargs):raise AssertionError('Read-only service must not create keys')
    monkeypatch.setattr(OpenSeaClient,'_request',unexpected)
    first=await OpenSeaClient()._key();second=await OpenSeaClient()._key()
    assert first==second=='disposable-shared-api-key-12345'


@pytest.mark.parametrize('expired',[False,True])
async def test_missing_or_expired_read_only_key_defers_without_creation(tmp_path,monkeypatch,expired):
    path=tmp_path/'key.json'
    if expired:stored_key(path,datetime.now(timezone.utc)-timedelta(seconds=1))
    monkeypatch.setattr(settings,'OPENSEA_KEY_FILE',str(path));monkeypatch.setattr(settings,'OPENSEA_KEY_READ_ONLY',True)
    async def unexpected(*args,**kwargs):raise AssertionError('Read-only service must not create keys')
    monkeypatch.setattr(OpenSeaClient,'_request',unexpected)
    with pytest.raises(OpenSeaUnavailable) as caught:await OpenSeaClient()._key()
    assert caught.value.retry_after_seconds==30


async def test_concurrent_key_owners_rotate_once_and_preserve_permissions(tmp_path,monkeypatch):
    path=tmp_path/'key.json';calls=[]
    monkeypatch.setattr(settings,'OPENSEA_KEY_FILE',str(path));monkeypatch.setattr(settings,'OPENSEA_KEY_READ_ONLY',False)
    monkeypatch.setattr(settings,'OPENSEA_SHARED_KEY_GID',os.getgid() if os.name=='posix' else None)
    async def create(*args,**kwargs):
        calls.append(1);await asyncio.sleep(.02)
        return 201,{'api_key':'disposable-shared-api-key-12345','expires_at':(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()}
    monkeypatch.setattr(OpenSeaClient,'_request',create)
    assert len(set(await asyncio.gather(OpenSeaClient()._key(),OpenSeaClient()._key())))==1
    assert len(calls)==1
    if os.name=='posix':assert path.stat().st_mode&0o777==0o640


async def test_shared_permits_serialize_workers_and_survive_new_sessions(test_db,monkeypatch):
    monkeypatch.setattr(settings,'OPENSEA_COORDINATE_REQUESTS',True)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    now=datetime.now(timezone.utc)
    results=await asyncio.gather(*[limits.acquire('/drops/example/mint',factory=factory,now=now) for _ in range(4)])
    assert sum(delay==0 for delay,_ in results)==1
    assert all(reason=='paced' for delay,reason in results if delay)
    delay,_=await limits.acquire('/drops/example/mint',factory=factory,now=now+timedelta(seconds=1))
    assert delay>=19
    assert (await limits.acquire('/drops/example/mint',factory=factory,now=now+timedelta(seconds=21)))[0]==0


async def test_endpoint_retry_after_does_not_use_unrelated_nonempty_bucket_reset(test_db,monkeypatch):
    monkeypatch.setattr(settings,'OPENSEA_COORDINATE_REQUESTS',True)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False);now=datetime.now(timezone.utc)
    await limits.observe('/drops/example/mint',429,{'Retry-After':'600','X-RateLimit-Remaining':'599','X-RateLimit-Reset':str(int(now.timestamp())+3600)},factory=factory,now=now)
    delay,reason=await limits.acquire('/drops/example/mint',factory=factory,now=now+timedelta(seconds=10))
    assert delay==590 and reason=='cooldown'
    assert (await limits.acquire('/drops/example',factory=factory,now=now+timedelta(seconds=10)))[0]==0
    assert (await limits.acquire('/drops/example/mint',factory=factory,now=now+timedelta(seconds=601)))[0]==0


async def test_exhausted_account_bucket_blocks_all_workers_until_reset(test_db,monkeypatch):
    monkeypatch.setattr(settings,'OPENSEA_COORDINATE_REQUESTS',True)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False);now=datetime.now(timezone.utc)
    await limits.observe('/drops/example',200,{'X-RateLimit-Remaining':'0','X-RateLimit-Reset':str(int(now.timestamp())+120)},factory=factory,now=now)
    delay,reason=await limits.acquire('/drops/example/mint',factory=factory,now=now+timedelta(seconds=1))
    assert delay>=118 and reason=='cooldown'


async def test_cooldown_prevents_network_requests_and_reports_local_deferral(test_db,monkeypatch):
    monkeypatch.setattr(settings,'OPENSEA_COORDINATE_REQUESTS',True)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False);monkeypatch.setattr(limits,'AsyncSessionLocal',factory)
    await limits.observe('/drops/example/mint',429,{'Retry-After':'600'},factory=factory)
    def unexpected(*args,**kwargs):raise AssertionError('No network request during cooldown')
    monkeypatch.setattr('app.services.opensea.aiohttp.ClientSession',unexpected)
    with diag.capture(str(uuid.uuid4()),'preparation') as events:
        with pytest.raises(OpenSeaUnavailable) as caught:await OpenSeaClient()._request('POST','/drops/example/mint')
    assert caught.value.retry_after_seconds>=590
    assert events[0]['http_status'] is None and events[0]['failure']=='cooldown'


async def test_verified_transient_cache_is_wallet_quantity_bound_and_copied(monkeypatch):
    tx={'to':'0x'+'11'*20,'value':'0','data':'0x1234','chain':'local-test','token':'must-not-cache'}
    address='0x'+'22'*20
    remember_verified_mint('example',address,1,tx,time.time()+60)
    def unexpected(*args,**kwargs):raise AssertionError('Verified entry should be reused')
    monkeypatch.setattr(OpenSeaClient,'_request',unexpected)
    a=await OpenSeaClient().build_mint('example',address,1)
    assert 'token' not in a[1];a[1]['data']='0xdead'
    assert (await OpenSeaClient().build_mint('example',address,1))[1]['data']=='0x1234'
    from app.services.opensea import _verified_mints
    assert ('example',address.lower(),2) not in _verified_mints


@pytest.mark.parametrize('fault',['none','intent','payload','expiry'])
async def test_private_cache_restart_scope_and_tampering(lab,fault):
    vault=CustodyVault();j=vault.journal();task=str(uuid.uuid4());intent='a'*64
    execution={'target':lab.sea.address,'value':'0','data':'0x'+b'private-proof-fixture'.hex()}
    cache.put(j,task,intent,execution,time.time()+600);j.commit();j.close()
    assert execution['data'].encode() not in Path(settings.CUSTODY_JOURNAL_FILE).read_bytes()
    j=vault.journal()
    if fault=='payload':j.execute("UPDATE mint_instruction_cache SET payload=x'0000'");j.commit()
    if fault=='expiry':j.execute('UPDATE mint_instruction_cache SET expires_at=1');j.commit()
    result=cache.get(j,task,'b'*64 if fault=='intent' else intent);j.close()
    assert result==execution if fault=='none' else result is None


async def test_cached_presale_survives_signer_memory_restart_and_revalidates_onchain(lab,monkeypatch):
    lab.kind='allowlist'
    armed=await lab.client.post('/api/tasks/arm',json={**lab.request,'mint_kind':'allowlist','onchain_stage_index':1})
    assert armed.status_code==200,armed.text;tid=armed.json()['id']
    async with lab.factory() as db:
        task=await db.get(MintTask,tid);auth=await db.get(MintAuthorization,task.authorization_id)
        auth.snapshot={**auth.snapshot,'execution':None};await db.commit()
    async with lab.factory() as db:await preflight_task(db,tid)
    _preflights.clear()
    async def unexpected(*args,**kwargs):raise AssertionError('Restart must reuse the protected verified cache')
    monkeypatch.setattr(OpenSeaClient,'build_mint',unexpected)
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    result=await lab.sign(tid)
    assert result['status']=='prepared'
    # Repeated prepare uses the same signed bytes, never a second nonce.
    assert (await lab.sign(tid))['hash']==result['hash']


async def test_cached_proof_is_rejected_when_onchain_allowlist_changes(lab,monkeypatch):
    lab.kind='allowlist'
    armed=await lab.client.post('/api/tasks/arm',json={**lab.request,'mint_kind':'allowlist','onchain_stage_index':1})
    tid=armed.json()['id']
    async with lab.factory() as db:
        task=await db.get(MintTask,tid);auth=await db.get(MintAuthorization,task.authorization_id)
        auth.snapshot={**auth.snapshot,'execution':None};await db.commit()
    async with lab.factory() as db:await preflight_task(db,tid)
    _preflights.clear()
    lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
    lab.sea.functions.updateAllowList(bytes.fromhex('11'*32),[],[]).transact({'from':lab.nft.address})
    lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
    async def unexpected(*args,**kwargs):raise AssertionError('The encrypted cache should be found')
    monkeypatch.setattr(OpenSeaClient,'build_mint',unexpected)
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    response=await lab.signer_client.post('/tasks/'+tid+'/prepare')
    assert response.status_code==409,response.text
    async with lab.factory() as db:assert (await db.get(MintTask,tid)).signed_tx_raw is None


def limited_error(wait):
    response=httpx.Response(503,json={'detail':'Presale provider temporarily unavailable.'},headers={'Retry-After':str(wait),**diag.headers([
        {'at':datetime.now(timezone.utc).isoformat(),'endpoint':'drop_mint','method':'POST','http_status':429,'retry_after_seconds':wait,'duration_ms':1,'failure':None}])},request=httpx.Request('POST','http://signer/tasks/id/prepare'))
    return httpx.HTTPStatusError('unavailable',request=response.request,response=response)


async def test_long_cooldown_does_not_poll_early_or_extend_expiry(lab):
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);tid=armed.json()['id'];calls=[]
    async def limited(task_id):calls.append(task_id);raise limited_error(600)
    now=datetime.fromtimestamp(lab.end-10,timezone.utc)
    await step(lab.factory,limited,now=now)
    async with lab.factory() as db:
        task=await db.get(MintTask,tid);assert task.next_attempt_at==task.expires_at_utc
    assert not await step(lab.factory,limited,now=now+timedelta(seconds=9))
    await step(lab.factory,limited,now=datetime.fromtimestamp(lab.end,timezone.utc))
    assert len(calls)==1
    async with lab.factory() as db:
        task=await db.get(MintTask,tid);assert task.status=='expired' and not task.signed_tx_raw
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==0


async def test_transient_retries_continue_after_six_within_existing_window_and_cancel(lab):
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);tid=armed.json()['id']
    async def limited(task_id):raise limited_error(20)
    now=datetime.fromtimestamp(lab.start,timezone.utc)
    for _ in range(7):
        await step(lab.factory,limited,now=now)
        async with lab.factory() as db:
            task=await db.get(MintTask,tid)
            assert task.status=='armed' and not task.signed_tx_raw
            assert task.next_attempt_at is not None
            from app.services.mint_plans import aware
            now=aware(task.next_attempt_at)
    async with lab.factory() as db:assert (await db.get(MintTask,tid)).preparation_attempts==7
    assert (await lab.client.post('/api/tasks/'+tid+'/disarm')).status_code==200
    assert not await step(lab.factory,limited,now=now)
    async with lab.factory() as db:assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==0
