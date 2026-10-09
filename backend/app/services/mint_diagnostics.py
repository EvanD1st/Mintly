"""Allowlisted, credential-free upstream diagnostics; never retain provider bodies."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import json,logging,re,time

_context=ContextVar('mint_http_diagnostics',default=None)
log=logging.getLogger('uvicorn.error')
FAILURES={'timeout','network_error','invalid_response','redirect','response_too_large','cooldown','paced'}
ENDPOINTS={'drop_mint','drop_schedule','key_creation','contract_lookup','other_opensea'}


def retry_seconds(value):
    if not isinstance(value,str) or len(value)>128:return None
    if re.fullmatch(r'[0-9]{1,8}',value):return min(int(value),86400)
    try:
        date=parsedate_to_datetime(value)
        if date.tzinfo is None:return None
        return min(86400,max(0,int((date-datetime.now(timezone.utc)).total_seconds())))
    except (ValueError,TypeError,OverflowError):return None


def endpoint(path):
    if re.fullmatch(r'/drops/[a-z0-9-]{1,100}/mint',path):return 'drop_mint'
    if re.fullmatch(r'/drops/[a-z0-9-]{1,100}',path):return 'drop_schedule'
    if path=='/auth/keys':return 'key_creation'
    if re.fullmatch(r'/chain/[a-z0-9-]+/contract/0x[0-9a-fA-F]{40}',path):return 'contract_lookup'
    return 'other_opensea'


@contextmanager
def capture(task_id,phase):
    context={'task_id':task_id if re.fullmatch(r'[a-fA-F0-9-]{36}',task_id) else None,
        'phase':phase if phase in ('preflight','preparation') else 'unknown','events':[]}
    token=_context.set(context)
    try:yield context['events']
    finally:_context.reset(token)


def record_http(method,path,status,retry_after,started,failure=None):
    context=_context.get()
    event={'at':datetime.now(timezone.utc).isoformat(),'endpoint':endpoint(path),
        'method':method if method in ('GET','POST') else 'OTHER','http_status':status,
        'retry_after_seconds':retry_seconds(retry_after),'duration_ms':min(600000,max(0,int((time.monotonic()-started)*1000))),
        'failure':failure if failure in FAILURES else None}
    if context is not None and len(context['events'])<16:context['events'].append(event)
    # Uvicorn's configured logger is visible inside the isolated signer process.
    if context is not None:
        log.info('mint_upstream %s',json.dumps({'task_id':context['task_id'],'phase':context['phase'],**event},separators=(',',':')))


def clean_events(value):
    if not isinstance(value,list):return []
    result=[]
    for row in value[:16]:
        if not isinstance(row,dict) or row.get('endpoint') not in ENDPOINTS:continue
        try:
            at=datetime.fromisoformat(row['at'])
            if at.tzinfo is None:continue
        except (ValueError,TypeError,KeyError):continue
        number=lambda v,lo,hi:v if type(v) is int and lo<=v<=hi else None
        result.append({'at':at.astimezone(timezone.utc).isoformat(),'endpoint':row['endpoint'],
            'method':row.get('method') if row.get('method') in ('GET','POST','OTHER') else 'OTHER',
            'http_status':number(row.get('http_status'),100,599),
            'retry_after_seconds':number(row.get('retry_after_seconds'),0,86400),
            'duration_ms':number(row.get('duration_ms'),0,600000),
            'failure':row.get('failure') if row.get('failure') in FAILURES else None})
    return result


def headers(events):
    return {'X-Mintly-Upstream-Diagnostics':json.dumps(clean_events(events),separators=(',',':'))}


def from_error(error):
    import httpx
    if isinstance(error,httpx.HTTPStatusError):
        raw=error.response.headers.get('X-Mintly-Upstream-Diagnostics','[]')
        if len(raw)>12000:return []
        try:return clean_events(json.loads(raw))
        except (ValueError,TypeError):return []
    return []


def category(events,status,error=None):
    for row in reversed(events):
        code=row['http_status']
        if code==429:return 'upstream_rate_limited'
        if code==409:return 'stage_not_active'
        if code==422:return 'mint_instructions_unavailable'
        if code in (401,403):return 'upstream_access_denied'
        if code is not None and code>=500:return 'upstream_server_error'
        if row['failure']:return row['failure']
    import httpx
    if isinstance(error,httpx.TimeoutException):return 'signer_timeout'
    if isinstance(error,httpx.RequestError):return 'signer_connection_error'
    if status==409:return 'signer_validation_rejected'
    return 'preparation_unavailable' if error else 'none'


async def save(db,task,phase,attempt,started,outcome,events=None,status=None,error=None):
    """A diagnostics failure must not change execution, reservations or nonce rules."""
    from app.models import MintAttemptDiagnostic
    events=clean_events(events or [])
    try:
        async with db.begin_nested():
            db.add(MintAttemptDiagnostic(task_id=task.id,phase=phase,attempt_number=attempt,
                started_at=started,finished_at=datetime.now(timezone.utc),outcome=outcome,
                signer_http_status=status,error_category=category(events,status,error),upstream_events=events,
                next_retry_at=task.next_attempt_at if task.status in ('armed','preparing') else None))
            await db.flush()
    except Exception:
        logging.getLogger('mintly.automatic').warning('Mint diagnostics persistence unavailable task_id=%s',task.id)
