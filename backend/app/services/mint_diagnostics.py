"""Allowlisted, credential-free upstream diagnostics; never retain provider bodies."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import json,logging,re,time

_context=ContextVar('mint_http_diagnostics',default=None)
log=logging.getLogger('uvicorn.error')
FAILURES={'timeout','network_error','invalid_response','redirect','response_too_large','cooldown','paced','queued','execution_priority'}
ENDPOINTS={'drop_mint','drop_schedule','key_creation','contract_lookup','other_opensea'}
PREPARATION_REASONS={
    'upstream_server_error':'OpenSea mint preparation is temporarily unavailable. Waiting to retry.',
    'stage_not_active':'The selected stage is not active yet; waiting for mint instructions.',
    'instructions_unavailable':'Waiting for wallet-specific mint instructions; another check is required.',
    'invalid_proof':'The wallet proof or creator signature is invalid under the current contract rules.',
    'rpc_unavailable':'Blockchain checks are temporarily unavailable. No transaction was signed.',
    'api_key_unavailable':'The application OpenSea key is missing or expired; operator action is required.',
    'api_access_denied':'OpenSea denied the application API access; check the key and endpoint permissions. Operator action is required.',
    'upstream_rate_limited':'OpenSea is rate-limiting mint preparation; waiting for the shared cooldown.',
    'wrong_phase':'OpenSea returned instructions for a different phase. No phase fallback is allowed.',
    'terms_changed':'The approved mint terms changed. Review the phase again.',
    'wallet_not_allowlisted':'This wallet is not eligible for the active whitelist stage.',
    'insufficient_funds':'This wallet has insufficient native balance for mint price and gas.',
    'wallet_limit':'This mint exceeds the receiving wallet’s remaining allowance.',
    'supply_exhausted':'This mint exceeds the remaining collection or stage supply.',
    'creator_payout_missing':'The creator has not configured the payout address required for this paid mint.',
    'precondition_unknown':'OpenSea rejected a mint precondition; the specific reason could not be verified.',
}
# Preserve the existing copy-event terminal-reason contract.
MINT_REASONS={key:PREPARATION_REASONS[key] for key in ('wallet_not_allowlisted','insufficient_funds',
    'wallet_limit','supply_exhausted','creator_payout_missing','precondition_unknown')}
PROVIDER_CODES={'STAGE_NOT_ACTIVE':'stage_not_active','MINT_NOT_ACTIVE':'stage_not_active',
    'INVALID_PROOF':'invalid_proof','INVALID_SIGNATURE':'invalid_proof','INSUFFICIENT_FUNDS':'insufficient_funds',
    'WALLET_LIMIT_EXCEEDED':'wallet_limit','MAX_SUPPLY_EXCEEDED':'supply_exhausted','SOLD_OUT':'supply_exhausted',
    'NOT_ALLOWLISTED':'wallet_not_allowlisted','RATE_LIMIT_EXCEEDED':'upstream_rate_limited'}


def provider_code(body):
    if not isinstance(body,dict):return None
    for candidate in (body,body.get('error'),body.get('detail')):
        if not isinstance(candidate,dict):continue
        for key in ('code','error_code'):
            value=candidate.get(key)
            if isinstance(value,str) and value in PROVIDER_CODES:return value
    return None


def mint_rejection_reason(body):
    """Classify only explicit provider messages; never retain arbitrary response text."""
    if not isinstance(body,dict):return 'precondition_unknown'
    code=provider_code(body)
    if code:return PROVIDER_CODES[code]
    parts=[]
    for key in ('message','error','errors','detail'):
        value=body.get(key)
        if isinstance(value,dict):value=value.get('message')
        values=value if isinstance(value,list) else [value]
        values=[v.get('message') if isinstance(v,dict) else v for v in values[:8]]
        parts.extend(v.lower() for v in values[:8] if isinstance(v,str) and len(v)<=2000)
    message=' '.join(parts)
    if any(x in message for x in ('stage not active','stage is not active','stage is inactive','not yet active','has not started','not started yet','mint not active','no active stage')):return 'stage_not_active'
    if any(x in message for x in ('invalid proof','invalid signature','proof is invalid','signature is invalid')):return 'invalid_proof'
    if any(x in message for x in ('insufficient funds','insufficient native balance','insufficient balance','cannot afford','cannot pay')):return 'insufficient_funds'
    if any(x in message for x in ('not on the allowlist','not on the active presale','not in the allowlist','not allowlisted','not eligible for the active','not eligible for this stage','not on this allowlist','not in allowlist')):return 'wallet_not_allowlisted'
    if any(x in message for x in ('supply exhausted','sold out','exceeds remaining supply','exceeds the remaining supply','over the remaining supply')):return 'supply_exhausted'
    if any(x in message for x in ('wallet limit exceeded','exceeds wallet limit','exceeds the wallet','over the wallet','max per wallet exceeded')):return 'wallet_limit'
    if any(x in message for x in ('no creator payout address','creator payout address is not set','creator payout address not configured')):return 'creator_payout_missing'
    return 'precondition_unknown'


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
def capture(task_id,phase,*,event_id=None):
    context={'task_id':task_id if re.fullmatch(r'[a-fA-F0-9-]{36}',task_id) else None,
        'phase':phase if phase in ('preflight','preparation','copy') else 'unknown',
        'event_id':event_id if isinstance(event_id,str) and re.fullmatch(r'[a-f0-9]{64}',event_id) else None,'events':[]}
    token=_context.set(context)
    try:yield context['events']
    finally:_context.reset(token)


def current_phase():
    context=_context.get()
    return context['phase'] if context else None


def record_terms(snapshot,mint):
    """Only validated scalar terms; never log calldata, proofs or signatures."""
    context=_context.get()
    if context is None:return
    params=mint.get('params')
    number=lambda v:v if type(v) is int and 0<=v<2**256 else None
    fields={'task_id':context['task_id'],'phase':context['phase'],
        'expected_start':number(snapshot.get('start')),'expected_end':number(snapshot.get('end')),
        'expected_price':number(snapshot.get('price_wei')),'expected_index':number(snapshot.get('onchain_stage_index')),
        'actual_start':number(params[2]) if params else None,'actual_end':number(params[3]) if params else None,
        'actual_price':number(params[0]) if params else None,'actual_index':number(params[4]) if params else None}
    log.info('mint_terms %s',json.dumps(fields,separators=(',',':')))


def record_http(method,path,status,retry_after,started,failure=None,*,mint_reason=None,upstream_code=None):
    context=_context.get()
    event={'at':datetime.now(timezone.utc).isoformat(),'endpoint':endpoint(path),
        'method':method if method in ('GET','POST') else 'OTHER','http_status':status,
        'retry_after_seconds':retry_seconds(retry_after),'duration_ms':min(600000,max(0,int((time.monotonic()-started)*1000))),
        'failure':failure if failure in FAILURES else None}
    if mint_reason in PREPARATION_REASONS:event['mint_reason']=mint_reason
    if upstream_code in PROVIDER_CODES:event['upstream_code']=upstream_code
    if context is not None and len(context['events'])<16:context['events'].append(event)
    # Uvicorn's configured logger is visible inside the isolated signer process.
    if context is not None:
        log.info('mint_upstream %s',json.dumps({'task_id':context['task_id'],'event_id':context['event_id'],'phase':context['phase'],**event},separators=(',',':')))


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
        if row.get('mint_reason') in PREPARATION_REASONS:result[-1]['mint_reason']=row['mint_reason']
        if row.get('upstream_code') in PROVIDER_CODES:result[-1]['upstream_code']=row['upstream_code']
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
        if row.get('mint_reason'):return row['mint_reason']
        if code==409:return 'mint_instructions_unavailable'
        if code==422:return row.get('mint_reason','mint_instructions_unavailable')
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
            from app.models import MintAuthorization
            auth=await db.get(MintAuthorization,task.authorization_id)
            snapshot=auth.snapshot if auth else {}
            selected=snapshot.get('selected_phase') or {}
            number=lambda value:value if type(value) is int and 0<=value<2**256 else None
            phase_id=selected.get('uuid')
            log.info('mint_attempt %s',json.dumps({'task_id':task.id,'phase':phase,'attempt':attempt,
                'phase_uuid':phase_id if isinstance(phase_id,str) and re.fullmatch(r'[a-fA-F0-9-]{32,36}',phase_id) else None,
                'stage_index':number(snapshot.get('onchain_stage_index')),'stage_start':number(snapshot.get('start')),
                'stage_end':number(snapshot.get('end')),'price_wei':number(snapshot.get('price_wei')),
                'quantity':number(snapshot.get('quantity')),'outcome':outcome,
                'retry_at':task.next_attempt_at.isoformat() if task.next_attempt_at else None,
                'has_broadcast':bool(task.broadcast_attempts)},separators=(',',':')))
    except Exception:
        logging.getLogger('mintly.automatic').warning('Mint diagnostics persistence unavailable task_id=%s',task.id)
