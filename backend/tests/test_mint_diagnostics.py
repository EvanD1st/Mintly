"""HTTP codes survive signer error mapping, retries, restart and malformed replies."""
from datetime import datetime,timezone,timedelta
import json,time,uuid
from email.utils import format_datetime
import httpx,pytest
from sqlalchemy import select
from app.services import mint_diagnostics as diag
from app.services.opensea import OpenSeaClient,OpenSeaUnavailable
from app.models import MintAttemptDiagnostic,MintTask,MintAuthorization
from app.automatic_worker import step,preflight_step
from test_automatic_evm import lab


def event(code):
    return {'at':datetime.now(timezone.utc).isoformat(),'endpoint':'drop_mint','method':'POST',
        'http_status':code,'retry_after_seconds':37,'duration_ms':12,'failure':None}


@pytest.mark.parametrize('code,body',[(409,b'{}'),(429,b'{"private_key":"never-log-me"}'),(503,b'upstream-token-secret'),(200,b'{}')])
async def test_transport_retains_raw_status_without_body_headers_or_url_secrets(monkeypatch,caplog,code,body):
    class Content:
        async def read(self,*args):return body
    class Response:
        status=code;content_length=len(body);content=Content();headers={'Retry-After':'37','Authorization':'never-log-me'}
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    class Session:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def request(self,*args,**kwargs):return Response()
    monkeypatch.setattr('app.services.opensea.aiohttp.ClientSession',Session)
    caplog.set_level('INFO',logger='uvicorn.error')
    with diag.capture(str(uuid.uuid4()),'preparation') as events:
        if code==503:
            with pytest.raises(OpenSeaUnavailable):await OpenSeaClient()._request('POST','/drops/private-collection/mint',key='private-api-key-never-log',payload={'signature':'wallet-proof-secret'})
        else:await OpenSeaClient()._request('POST','/drops/private-collection/mint',key='private-api-key-never-log',payload={'signature':'wallet-proof-secret'})
    assert len(events)==1 and events[0]['http_status']==code and events[0]['retry_after_seconds']==37
    if code==503:assert events[0]['failure']=='invalid_response'
    for secret in ('never-log-me','private-api-key','wallet-proof-secret','upstream-token-secret','private-collection'):
        assert secret not in caplog.text+json.dumps(events)


@pytest.mark.parametrize('error',[TimeoutError(),ValueError('private-server-error')])
async def test_transport_failures_record_category_without_exception_text(monkeypatch,error):
    class Session:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):raise error
        async def __aexit__(self,*args):pass
    monkeypatch.setattr('app.services.opensea.aiohttp.ClientSession',Session)
    with diag.capture(str(uuid.uuid4()),'preparation') as events:
        with pytest.raises(OpenSeaUnavailable):await OpenSeaClient()._request('POST','/drops/test/mint')
    assert events[0]['http_status'] is None
    assert events[0]['failure']==('timeout' if isinstance(error,TimeoutError) else 'invalid_response')
    assert 'private-server-error' not in json.dumps(events)


def test_retry_after_parsing_and_control_plane_metadata_are_allowlisted():
    assert diag.retry_seconds('37')==37
    assert 28<=diag.retry_seconds(format_datetime(datetime.now(timezone.utc)+timedelta(seconds=30)))<=30
    assert diag.retry_seconds('Bearer secret-token') is None
    raw={**event(429),'authorization':'secret-token','body':{'private_key':'secret-key'}}
    clean=diag.clean_events([raw])
    assert 'secret' not in json.dumps(clean)
    assert diag.clean_events([{**raw,'at':'secret-token'}])==[]
    response=httpx.Response(503,headers=diag.headers([raw]),request=httpx.Request('POST','http://signer/tasks/id/prepare'))
    assert diag.from_error(httpx.HTTPStatusError('secret-payload',request=response.request,response=response))[0]['http_status']==429


@pytest.mark.parametrize('code',[409,429,503])
async def test_signer_mapping_and_worker_retain_original_code_and_retry_deadline(lab,monkeypatch,code):
    lab.kind='allowlist'
    armed=await lab.client.post('/api/tasks/arm',json={**lab.request,'mint_kind':'allowlist'})
    assert armed.status_code==200,armed.text
    tid=armed.json()['id']
    # Simulate an approved upcoming task whose proof is fetched at execution.
    async with lab.factory() as db:
        task=await db.get(MintTask,tid)
        auth=await db.get(MintAuthorization,task.authorization_id)
        auth.snapshot={**auth.snapshot,'execution':None}
        await db.commit()
    from app.services.opensea import OpenSeaClient
    async def unavailable(*args,**kwargs):
        diag.record_http('POST','/drops/test/mint',code,'37',time.monotonic())
        if code in (409,422):return code,None
        raise OpenSeaUnavailable('Private upstream payload must not cross boundary',503)
    monkeypatch.setattr(OpenSeaClient,'build_mint',unavailable)
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,tid)
        rows=(await db.scalars(select(MintAttemptDiagnostic).where(MintAttemptDiagnostic.task_id==tid))).all()
        assert len(rows)==1
        row=rows[0]
        assert row.signer_http_status==503 and row.upstream_events[0]['http_status']==code
        assert row.upstream_events[0]['retry_after_seconds']==37
        assert row.attempt_number==1 and row.outcome=='retry_scheduled'
        assert row.next_retry_at==task.next_attempt_at
        assert row.error_category=={409:'stage_not_active',429:'upstream_rate_limited',503:'upstream_server_error'}[code]
        assert task.status=='armed' and task.preparation_attempts==1 and not task.signed_tx_raw
        assert 'Private upstream' not in json.dumps(row.upstream_events)
    # New DB session proves the history survives ephemeral response/exception state.
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        rows=(await db.scalars(select(MintAttemptDiagnostic).where(MintAttemptDiagnostic.task_id==tid).order_by(MintAttemptDiagnostic.started_at))).all()
        assert [r.attempt_number for r in rows]==[1,2]


async def test_successful_preparation_is_retained_without_signature_or_nonce_leak(lab):
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);tid=armed.json()['id']
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,tid)
        row=await db.scalar(select(MintAttemptDiagnostic).where(MintAttemptDiagnostic.task_id==tid))
        assert task.signed_tx_raw and row.outcome=='request_completed' and row.signer_http_status==200
        assert task.signed_tx_raw not in json.dumps(row.upstream_events)


async def test_preflight_history_is_separate_from_execution_retry_count(lab):
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);tid=armed.json()['id']
    async def check(task_id):return {'status':'checked','_diagnostics':[event(409)]}
    await preflight_step(lab.factory,check,now=datetime.fromtimestamp(lab.start-60,timezone.utc))
    async with lab.factory() as db:
        row=await db.scalar(select(MintAttemptDiagnostic).where(MintAttemptDiagnostic.task_id==tid))
        task=await db.get(MintTask,tid)
        assert row.phase=='preflight' and row.upstream_events[0]['http_status']==409
        assert row.attempt_number is None and task.preparation_attempts==0 and not task.signed_tx_raw


async def test_failed_diagnostic_insert_does_not_change_successful_signing(lab,monkeypatch):
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);tid=armed.json()['id']
    def broken(*args,**kwargs):raise RuntimeError('simulated logging outage')
    monkeypatch.setattr('app.models.MintAttemptDiagnostic',broken)
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,tid)
        assert task.signed_tx_raw and task.status=='prepared' and task.preparation_attempts==0
