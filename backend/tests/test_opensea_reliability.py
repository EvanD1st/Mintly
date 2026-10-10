"""Provisioned credentials, phase identity, shared queue and short-window recovery."""
import asyncio,json,uuid
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from email.utils import format_datetime
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.config import settings
from app.services.opensea import OpenSeaClient,OpenSeaUnavailable,collection_slug,singleflight
from app.services import opensea_limits as limits,mint_diagnostics as diag
from app.services.phase_identity import same_phase,schedule_matches
from app.services.mint_stage_choice import pinned
from app.services.seadrop_mint import verify_presale,match_stage,decode_mint
from app.services.preparation_retry import next_retry
from app.models import OpenSeaRequestWaiter,MintTask,MintAuthorization
from test_automatic_evm import lab

@pytest.mark.parametrize('state',['valid','missing','expired'])
async def test_production_never_creates_or_replaces_a_key(tmp_path,monkeypatch,state):
    path=tmp_path/'secret.json'
    if state!='missing':path.write_text(json.dumps({'api_key':'disposable-developer-key','provisioned':True,
        **({'expires_at':'2000-01-01T00:00:00Z'} if state=='expired' else {})}))
    monkeypatch.setattr(settings,'APP_ENV','production');monkeypatch.setattr(settings,'OPENSEA_KEY_FILE',str(path))
    monkeypatch.setattr(settings,'OPENSEA_ALLOW_INSTANT_KEYS',True)
    async def forbidden(*args,**kwargs):raise AssertionError('Key creation is prohibited')
    monkeypatch.setattr(OpenSeaClient,'_request',forbidden)
    if state=='valid':assert await asyncio.gather(*(OpenSeaClient()._key() for _ in range(8)))==['disposable-developer-key']*8
    else:
        with pytest.raises(OpenSeaUnavailable) as error:await OpenSeaClient()._key()
        assert error.value.mint_reason=='api_key_unavailable'

async def test_production_key_creation_transport_is_blocked(monkeypatch):
    monkeypatch.setattr(settings,'APP_ENV','production')
    with pytest.raises(OpenSeaUnavailable):await OpenSeaClient()._request('POST','/auth/keys')

def test_overview_link_normalizes_without_loosening_host_validation():
    assert collection_slug('https://opensea.io/collection/seeker-net/overview/')=='seeker-net'
    for url in ('https://opensea.io.evil.test/collection/seeker-net/overview','https://opensea.io/collection/seeker-net/overview/extra'):
        with pytest.raises(OpenSeaUnavailable):collection_slug(url)

def test_uuid_alias_formatting_preserves_material_phase_identity():
    a={'uuid':'3130702aa76547c595b50fc33fcf35c1','type':'signed_presale','starts_at':1,'ends_at':27,'price_wei':0,'max_per_wallet':2}
    assert same_phase(a,{**a,'uuid':'3130702a-a765-47c5-95b5-0fc33fcf35c1','type':'signed_sale'})
    assert not same_phase(a,{**a,'price_wei':1})

def test_phase_matching_uses_method_timing_and_index_not_wallet_price():
    stage={'uuid':'chosen','type':'signed_sale','starts_at':datetime.fromtimestamp(1,timezone.utc),'ends_at':datetime.fromtimestamp(27,timezone.utc),'price_wei':100,'onchain_stage_index':3}
    mint={'kind':'signed','params':(0,2,1,27,3,2222,0,True)}
    assert match_stage(mint,[stage])==stage
    with pytest.raises(OpenSeaUnavailable):match_stage(mint,[stage,{**stage,'uuid':'ambiguous'}])
    with pytest.raises(OpenSeaUnavailable):match_stage(mint,[{**stage,'onchain_stage_index':2}])

def test_selected_wallet_price_is_distinct_from_schedule_price():
    stage={'uuid':'chosen','type':'signed_presale','starts_at':datetime.fromtimestamp(1,timezone.utc),'ends_at':datetime.fromtimestamp(27,timezone.utc),'price_wei':100,'max_per_wallet':20}
    approval={**pinned(stage),'price_wei':0,'schedule_price_wei':100,'wallet_total_limit':2}
    assert schedule_matches(stage,approval,pinned)
    assert not schedule_matches({**stage,'ends_at':datetime.fromtimestamp(28,timezone.utc)},approval,pinned)

@pytest.mark.parametrize('message,reason',[('Stage is not active yet','stage_not_active'),('Invalid proof','invalid_proof'),('Collection sold out','supply_exhausted')])
def test_explicit_provider_message_drives_retry_classification(message,reason):
    assert diag.mint_rejection_reason({'message':message})==reason
    client=OpenSeaClient();client.last_mint_reason=reason;client.last_retry_after=3
    error=client.mint_error(409)
    assert error.upstream_status==409 and error.retry_after_seconds==3
    assert error.status==(503 if reason=='stage_not_active' else 409)

@pytest.mark.parametrize('failure',[TimeoutError('private rpc endpoint'),ValueError({'code':-32005,'message':'RPC rate limit'})])
async def test_transient_rpc_failure_is_not_an_invalid_proof(failure):
    class Eth:
        async def call(self,*args,**kwargs):raise failure
    mint={'kind':'allowlist','params':(0,2,1,27,3,2222,0,True),'contract':'0x'+'11'*20,'wallet':'0x'+'22'*20,'proof':[]}
    with pytest.raises(OpenSeaUnavailable) as error:await verify_presale(SimpleNamespace(eth=Eth()),mint)
    assert error.value.status==503 and error.value.mint_reason=='rpc_unavailable'
    assert 'private rpc' not in str(error.value)

def test_provider_codes_are_allowlisted_and_drive_classification():
    assert diag.mint_rejection_reason({'error':{'code':'STAGE_NOT_ACTIVE'}})=='stage_not_active'
    assert diag.provider_code({'code':'private-token-never-log'}) is None

async def test_identical_concurrent_lookups_share_one_request_but_not_mutable_result():
    calls=[]
    async def load():calls.append(1);await asyncio.sleep(.01);return {'value':1}
    a,b=await asyncio.gather(singleflight(('test','one'),load),singleflight(('test','one'),load))
    a['value']=2
    assert calls==[1] and b['value']==1

async def test_shared_queue_prioritizes_mint_over_background_and_expires_leases(test_db,monkeypatch):
    monkeypatch.setattr(settings,'OPENSEA_COORDINATE_REQUESTS',True)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False);now=datetime.now(timezone.utc)
    background=str(uuid.uuid4());urgent=str(uuid.uuid4())
    async with factory() as db:
        db.add_all([OpenSeaRequestWaiter(id=background,priority=2,expires_at=now+timedelta(seconds=5)),
                    OpenSeaRequestWaiter(id=urgent,priority=0,expires_at=now+timedelta(seconds=5))]);await db.commit()
    assert await limits.acquire('/drops/example',factory=factory,now=now,request_id=background)==(1,'queued')
    assert (await limits.acquire('/drops/example/mint',factory=factory,now=now,request_id=urgent))[0]==0
    assert (await limits.acquire('/drops/example',factory=factory,now=now))[0]>=6
    assert (await limits.acquire('/drops/example',factory=factory,now=now+timedelta(seconds=7),request_id=str(uuid.uuid4())))[0]==0

def test_http_date_retry_after_and_fast_fcfs_deadline():
    now=datetime.now(timezone.utc);deadline=now+timedelta(seconds=26)
    wait=diag.retry_seconds(format_datetime(now+timedelta(seconds=20),usegmt=True))
    assert 18<=wait<=20
    retry,miss=next_retry(now,deadline,1,0)
    assert retry==now+timedelta(seconds=2) and not miss
    retry,miss=next_retry(now,deadline,2,60)
    assert retry==deadline and miss

async def test_rpc_timeout_recovers_without_second_approval_or_duplicate_signature(lab,monkeypatch):
    lab.kind='allowlist'
    armed=await lab.client.post('/api/tasks/arm',json={**lab.request,'mint_kind':'allowlist','onchain_stage_index':1,
        'expires_at':datetime.fromtimestamp(lab.start+26,timezone.utc).isoformat()})
    assert armed.status_code==200,armed.text
    tid=armed.json()['id']
    from app.services import automatic
    original=automatic.verify_presale;calls=[]
    async def flaky(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:raise OpenSeaUnavailable('RPC temporarily unavailable',503,mint_reason='rpc_unavailable')
        return await original(*args,**kwargs)
    monkeypatch.setattr(automatic,'verify_presale',flaky)
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,tid);assert task.status=='armed' and not task.signed_tx_raw
        original_hash=automatic.digest((await db.get(MintAuthorization,task.authorization_id)).snapshot)
    await lab.due();first=await lab.sign(tid);second=await lab.sign(tid)
    assert first['hash']==second['hash']
    async with lab.factory() as db:
        task=await db.get(MintTask,tid)
        assert automatic.digest((await db.get(MintAuthorization,task.authorization_id)).snapshot)==original_hash

async def test_fast_fcfs_budget_admits_two_wallets_and_reports_third_deadline(test_db,monkeypatch):
    # Recorded Seeker Net FCFS window: 18:00:05 to 18:00:31, not an attribution
    # of any production failure. Three wallets contend for the same account.
    monkeypatch.setattr(settings,'OPENSEA_COORDINATE_REQUESTS',True)
    monkeypatch.setattr(settings,'OPENSEA_GLOBAL_REQUEST_SECONDS',6)
    monkeypatch.setattr(settings,'OPENSEA_MINT_REQUEST_SECONDS',20)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    now=datetime(2026,10,9,18,0,5,tzinfo=timezone.utc);end=now+timedelta(seconds=26)
    assert (await limits.acquire('/drops/seeker-net/mint',factory=factory,now=now))[0]==0
    wait,_=await limits.acquire('/drops/seeker-net/mint',factory=factory,now=now)
    retry,miss=next_retry(now,end,1,wait)
    assert retry==now+timedelta(seconds=20) and not miss
    assert (await limits.acquire('/drops/seeker-net/mint',factory=factory,now=retry))[0]==0
    wait,_=await limits.acquire('/drops/seeker-net/mint',factory=factory,now=retry)
    assert next_retry(retry,end,1,wait)==(end,True)
    client=OpenSeaClient();client.last_mint_reason='supply_exhausted'
    assert client.mint_error(422).status==409

async def test_new_unsigned_proof_refreshes_without_changing_approval(lab,monkeypatch):
    from eth_abi import encode
    from eth_utils import keccak
    from app.services.seadrop_mint import PARAM_TYPE,ALLOW_SELECTOR
    from app.services import automatic
    lab.kind='allowlist'
    armed=await lab.client.post('/api/tasks/arm',json={**lab.request,'mint_kind':'allowlist','onchain_stage_index':1})
    assert armed.status_code==200,armed.text
    tid=armed.json()['id']
    original=OpenSeaClient.build_mint
    _,old=await original(OpenSeaClient(),'local-test',lab.owner.address,2)
    mint=decode_mint(old,lab.nft.address,lab.owner.address,2)
    leaf=keccak(encode(['address',PARAM_TYPE],[lab.owner.address,mint['params']]))
    sibling=keccak(text='new disposable allowlist leaf')
    root=keccak(min(leaf,sibling)+max(leaf,sibling))
    lab.nft.functions.replaceRoot(root).transact({'from':lab.w.eth.accounts[0]})
    calls=[]
    async def refreshed(self,slug,address,quantity):
        calls.append(1)
        return 200,{**old,'data':'0x'+ALLOW_SELECTOR+encode(['address','address','address','uint256',PARAM_TYPE,'bytes32[]'],
            [mint['contract'],mint['fee'],address,quantity,mint['params'],[sibling]]).hex()}
    monkeypatch.setattr(OpenSeaClient,'build_mint',refreshed)
    async with lab.factory() as db:
        task=await db.get(MintTask,tid);before=automatic.digest((await db.get(MintAuthorization,task.authorization_id)).snapshot)
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    first=await lab.sign(tid);second=await lab.sign(tid)
    assert first['hash']==second['hash'] and calls==[1]
    async with lab.factory() as db:
        task=await db.get(MintTask,tid)
        assert automatic.digest((await db.get(MintAuthorization,task.authorization_id)).snapshot)==before
