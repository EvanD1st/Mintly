"""Explicit upstream rejections stop copying; unknown reasons retain bounded retries."""
import json,time
from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select
from app.models import CopyEvent,CopyRule,MintTask
from app.services import copy_mints as copy_service,mint_diagnostics as diag,opensea_limits as limits
from app.services.opensea import OpenSeaClient,OpenSeaUnavailable,_contract_cache
from app.config import settings
from test_copy_event_retry import prepared_events
from test_copy_presales import presale
from test_copy_mints import copying
from test_automatic_evm import lab


@pytest.mark.parametrize('message,reason',[
    ('The minter is not on the active presale allowlist','wallet_not_allowlisted'),
    ('Insufficient native balance to pay gas','insufficient_funds'),
    ('Quantity exceeds the wallet limit','wallet_limit'),
    ('Quantity exceeds the remaining supply','supply_exhausted'),
    ('Paid stage has no creator payout address','creator_payout_missing'),
    ('Unexpected error containing secret-token','precondition_unknown'),
])
def test_only_allowlisted_reasons_survive_body_classification(message,reason):
    assert diag.mint_rejection_reason({'errors':[message],'private_key':'never-store-this'})==reason
    assert 'secret' not in diag.MINT_REASONS[reason]


async def test_transport_reason_is_sanitized_and_scoped_to_one_event(monkeypatch,caplog):
    body=json.dumps({'errors':['Insufficient native balance; token=secret-token'],'signature':'secret-proof'}).encode()
    class Content:
        async def read(self,*args):return body
    class Response:
        status=422;content_length=len(body);content=Content();headers={}
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    class Session:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def request(self,*args,**kwargs):return Response()
    monkeypatch.setattr('app.services.opensea.aiohttp.ClientSession',Session)
    async def key(*args):return 'secret-key'
    monkeypatch.setattr(OpenSeaClient,'_key',key)
    caplog.set_level('INFO',logger='uvicorn.error')
    client=OpenSeaClient()
    with diag.capture('','copy',event_id='a'*64) as events:
        assert await client.build_mint('test','0x'+'11'*20)==(422,None)
    assert client.last_mint_reason=='insufficient_funds'
    assert diag.clean_events(events)[0]['mint_reason']=='insufficient_funds'
    assert '"event_id":"'+'a'*64+'"' in caplog.text and '"phase":"copy"' in caplog.text
    for secret in ('secret-token','secret-proof','secret-key'):assert secret not in caplog.text+json.dumps(events)
    assert diag.current_phase() is None


@pytest.mark.parametrize('reason',['wallet_not_allowlisted','insufficient_funds','wallet_limit','supply_exhausted','creator_payout_missing'])
async def test_clear_rejection_is_durable_and_never_automatically_revived(presale,monkeypatch,reason):
    c,_,_,eid,_=await prepared_events(presale);lab=c['lab']
    async def rejected(self,*args,**kwargs):
        self.last_mint_reason=reason
        diag.record_http('POST','/drops/test/mint',422,None,time.monotonic(),mint_reason=reason)
        return 422,None
    monkeypatch.setattr(OpenSeaClient,'build_mint',rejected)
    async with lab.factory() as db:await copy_service.process_copy_events(db,c['watch_id'],31337)
    async with lab.factory() as db:
        e=await db.get(CopyEvent,eid)
        assert e.status=='skipped' and e.next_attempt_at is None and e.task_id is None
        assert e.last_error_category==reason and e.last_upstream_status==422 and e.preparation_attempts==1
        assert e.upstream_events[0]['mint_reason']==reason
        assert copy_service.is_funding_note(e.note,31337)==(reason=='insufficient_funds')
    async def unexpected(*args):raise AssertionError('Skipped rejection must not be revived')
    monkeypatch.setattr(copy_service,'arm_event',unexpected)
    async with lab.factory() as db:await copy_service.process_copy_events(db,c['watch_id'],31337)
    activity=(await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert activity['preparation_attempts']==1 and activity['upstream_events'][0]['mint_reason']==reason
    assert activity['retryable']==(reason=='insufficient_funds')


async def test_unknown_rejection_backs_off_and_keeps_original_expiry(presale,monkeypatch):
    c,_,_,eid,o=await prepared_events(presale);lab=c['lab']
    async def unknown(self,*args,**kwargs):
        self.last_mint_reason='precondition_unknown'
        return 422,None
    monkeypatch.setattr(OpenSeaClient,'build_mint',unknown)
    async with lab.factory() as db:await copy_service.process_copy_events(db,c['watch_id'],31337)
    async with lab.factory() as db:
        e=await db.get(CopyEvent,eid);assert e.preparation_attempts==1
        first=e.next_attempt_at;e.next_attempt_at=None;await db.commit()
    async with lab.factory() as db:await copy_service.process_copy_events(db,c['watch_id'],31337)
    async with lab.factory() as db:
        e=await db.get(CopyEvent,eid)
        from app.services.mint_plans import aware
        assert e.status=='detected' and e.preparation_attempts==2 and e.task_id is None
        assert aware(e.next_attempt_at)>=aware(first)+timedelta(seconds=59)
        assert aware(e.next_attempt_at).timestamp()<=o['end']
        assert 'specific reason is unknown' in e.note


async def test_due_copy_reserves_capacity_against_advance_checks(presale,monkeypatch):
    c,_,_,eid,o=await prepared_events(presale);lab=c['lab']
    now=datetime.now(timezone.utc)
    async with lab.factory() as db:
        e=await db.get(CopyEvent,eid)
        e.observation={**o,'start':int(now.timestamp())-1,'end':int(now.timestamp())+300}
        await db.commit()
    monkeypatch.setattr(settings,'OPENSEA_COORDINATE_REQUESTS',True)
    with diag.capture('','preflight'):
        assert await limits.acquire('/drops/test/mint',factory=lab.factory,now=now)==(30,'execution_priority')
    with diag.capture('','copy',event_id=eid):
        assert await limits.acquire('/drops/test/mint',factory=lab.factory,now=now)==(0,None)
    # No active approval means no capacity reservation.
    async with lab.factory() as db:
        rule=await db.scalar(select(CopyRule).where(CopyRule.watch_id==c['watch_id']))
        rule.status='paused';await db.commit()
    with diag.capture('','preflight'):
        assert (await limits.acquire('/drops/test/mint',factory=lab.factory,now=now+timedelta(seconds=30)))[0]==0


async def test_verified_contract_cache_rechecks_schedule_and_network(monkeypatch):
    contract='0x'+'33'*20;calls=[]
    async def request(self,method,path,**kwargs):
        calls.append(path)
        return 200,{'chain':'base','address':contract,'contract_standard':'erc721','collection':'test'}
    detail={'chain':'base','contract_address':contract};checks=[]
    async def drop(self,slug):checks.append(slug);return detail
    async def key(self):return 'secret-key'
    monkeypatch.setattr(OpenSeaClient,'_request',request);monkeypatch.setattr(OpenSeaClient,'get_drop',drop);monkeypatch.setattr(OpenSeaClient,'_key',key)
    client=OpenSeaClient()
    assert await client.collection_for_contract(8453,contract)=='test'
    assert await OpenSeaClient().collection_for_contract(8453,contract.upper().replace('0X','0x'))=='test'
    assert len(calls)==1 and len(checks)==2
    detail['chain']='ethereum'
    with pytest.raises(OpenSeaUnavailable):await client.collection_for_contract(8453,contract)
    assert (8453,contract.lower()) not in _contract_cache
