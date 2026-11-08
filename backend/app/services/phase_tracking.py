"""Resolve explicitly authorized opening changes without rewriting consent."""
import copy
from datetime import datetime,timezone
from app.services.opensea import OpenSeaClient,OpenSeaUnavailable,collection_slug,stage_schedule,CHAINS
from app.services.phase_identity import stage_key,stage_kind
from app.services.mint_stage_choice import pinned


class PhaseChanged(OpenSeaUnavailable):
    def __init__(self,message):
        super().__init__(message,409,mint_reason='terms_changed')


def tracking(snapshot):
    return snapshot.get('schedule_mode')=='phase_open' and bool(snapshot.get('phase_identity'))


async def resolve(snapshot,*,now=None):
    """Only timing may move. Price, phase identity and approved limits are pinned."""
    s=copy.deepcopy(snapshot)
    if not tracking(s):return s
    now=now or datetime.now(timezone.utc)
    approved=s['phase_identity']
    detail=await OpenSeaClient().get_drop(collection_slug(s['mint_page_url']))
    if CHAINS.get(detail.get('chain'),(None,))[0]!=s['chain_id'] or detail['contract_address'].lower()!=s['contract'].lower():
        raise PhaseChanged('The collection or network changed. Review this mint again.')
    candidates=[r for r in stage_schedule(detail) if stage_key(r['uuid'])==stage_key(approved['uuid'])]
    if len(candidates)!=1:
        raise PhaseChanged('The approved phase was removed or cannot be identified. Review this mint again.')
    actual=pinned(candidates[0])
    if any(actual[k]!=approved[k] for k in ('type','price_wei','max_per_wallet')):
        raise PhaseChanged('The approved phase price, method or allowance changed. Review this mint again.')
    if stage_kind(actual['type'])!=s['mint_kind']:
        raise PhaseChanged('The approved mint method changed. Review this mint again.')
    if actual['starts_at']>=s['expiry']:
        raise PhaseChanged('The phase opening moved beyond your approved deadline. Review this mint again.')
    if actual['ends_at']<=int(now.timestamp()):
        raise PhaseChanged('The approved phase has ended. No transaction was sent.')
    s['start'],s['end']=actual['starts_at'],actual['ends_at']
    s['execute_at']=actual['starts_at']
    # A previous calldata/proof cache must not survive changed phase parameters.
    if (s['start'],s['end'])!=(snapshot['start'],snapshot['end']):s.pop('execution',None)
    if s.get('selected_phase'):
        s['selected_phase']={**s['selected_phase'],'starts_at':s['start'],'ends_at':s['end']}
    return s


async def authorize(snapshot,db,req):
    """Called during review and arming; the resulting identity is consent-hashed."""
    if getattr(req,'schedule_mode','fixed')!='phase_open':return
    if getattr(req,'copy_event_id',None):raise PhaseChanged('Copy observations use their existing phase approval.')
    detail=await OpenSeaClient().get_drop(collection_slug(snapshot['mint_page_url']))
    if CHAINS.get(detail.get('chain'),(None,))[0]!=snapshot['chain_id'] or detail['contract_address'].lower()!=snapshot['contract'].lower():
        raise PhaseChanged('The collection identity changed. Review it again.')
    candidates=[r for r in stage_schedule(detail) if stage_kind(r['type'])==snapshot['mint_kind']
        and (int(r['starts_at'].timestamp()),int(r['ends_at'].timestamp()))==(snapshot['start'],snapshot['end'])]
    selected=snapshot.get('selected_phase')
    if selected:candidates=[r for r in candidates if stage_key(r['uuid'])==stage_key(selected['uuid'])]
    if len(candidates)!=1:raise PhaseChanged('A unique phase identity is required to follow its opening.')
    snapshot['schedule_mode']='phase_open'
    snapshot['phase_identity']=pinned(candidates[0])
    snapshot['execute_at']=snapshot['start']


async def refresh_task(db,task_id,vault):
    from app.services.mint_plans import aware
    from app.models import MintTask,MintAuthorization,Wallet
    from app.services import automatic
    await automatic.lock_execution(db)
    task=await db.get(MintTask,task_id,populate_existing=True)
    if not task or task.status!='armed' or task.signed_tx_raw or task.transaction_hash or task.broadcast_attempts:
        raise PhaseChanged('This task is no longer available for schedule checks.')
    auth=await db.get(MintAuthorization,task.authorization_id)
    original=copy.deepcopy(auth.snapshot)
    if auth.is_revoked or not tracking(original):raise PhaseChanged('This approval uses an exact fixed schedule.')
    grant=await automatic.grant_for(db,auth.grant_id,original['user_id'])
    await automatic.require_running(db,original['user_id'])
    wallet=await db.get(Wallet,task.wallet_id)
    if not wallet or wallet.archived_at or wallet.user_id!=grant.user_id or wallet.id!=grant.wallet_id:
        raise PhaseChanged('The approved wallet changed.')
    policy=vault.policy(grant);policy_hash=grant.context_hash
    journal=vault.journal()
    try:
        if journal.execute('SELECT 1 FROM signed WHERE task=?',(task.id,)).fetchone():
            raise PhaseChanged('A signed transaction already exists; its timing cannot be rewritten.')
    finally:journal.close()
    if original.get('feed_approval_id') and aware(task.scheduled_for_utc)>datetime.now(timezone.utc):
        from app.services.auto_arm_funding import resize,queued,held
        await resize(db,task,auth,grant,min(await queued(auth),await held(db,task,auth)))
    await db.commit()
    changed=None
    try:effective=await resolve(original)
    except PhaseChanged as error:changed=error
    await automatic.lock_execution(db)
    await db.refresh(task);await db.refresh(auth);await db.refresh(grant)
    await automatic.require_running(db,original['user_id'])
    if task.status!='armed' or task.signed_tx_raw or task.transaction_hash or auth.is_revoked or auth.snapshot!=original or grant.context_hash!=policy_hash:
        raise PhaseChanged('The task approval changed while checking its schedule.')
    journal=vault.journal()
    try:
        if journal.execute('SELECT 1 FROM signed WHERE task=?',(task.id,)).fetchone():
            raise PhaseChanged('A signed transaction already exists; schedule check stopped.')
    finally:journal.close()
    now=datetime.now(timezone.utc)
    task.schedule_checked_at=now
    if changed:
        from app.automatic_worker import finish
        task.schedule_note=str(changed)
        await finish(db,task,'failed',str(changed))
    else:
        from app.services.mint_plans import aware
        from app.models import ActivityEvent
        old=aware(task.scheduled_for_utc)
        new=datetime.fromtimestamp(effective['start'],timezone.utc)
        if old!=new:
            from zoneinfo import ZoneInfo
            wat=ZoneInfo('Africa/Lagos')
            note=f"Phase opening changed from {old.astimezone(wat):%d %b %H:%M} to {new.astimezone(wat):%d %b %H:%M} WAT. Your mint remains armed."
            task.scheduled_for_utc=new;task.next_attempt_at=None
            task.schedule_note=note
            task.preflight_checked_at=None
            task.preparation_attempts=0
            db.add(ActivityEvent(user_id=grant.user_id,event_type='mint_schedule_updated',label='Mint opening updated',detail=note,is_demo=False,icon_name='gem'))
    await db.commit()
    return {'status':task.status,'note':task.schedule_note}
