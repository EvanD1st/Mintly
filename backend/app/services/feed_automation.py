"""Explicit standing approval for verified zero-price daily-list phases."""
import asyncio,json,uuid,logging
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select,func
from fastapi import HTTPException
from app.models import FeedMintApproval,AutomaticGrant,Wallet,User,FeedWalletCheck,MintTask,MintAuthorization,ActivityEvent
from app.services import automatic,feed_checks
from app.services.mint_plans import aware
from app.services.feed_sources import daily_collections,SOURCE_NAMES
from app.services.opensea import collection_slug
from app.services.networks import symbol

ENABLED_ONCE='free_list_enabled_once_v1'
MAX_WALLET_QUANTITY=65535  # SeaDrop's uint16 wallet allowance.


def quantity_allowed(snapshot,quantity):
    mode=snapshot.get('quantity_mode','fixed')
    return (mode=='wallet_max' and snapshot['quantity']==MAX_WALLET_QUANTITY and 1<=quantity<=MAX_WALLET_QUANTITY
        or mode=='fixed' and 1<=quantity==snapshot['quantity']<=100)



async def remember_enabled(db,user_id):
    owner=await db.scalar(select(User).where(User.id==user_id).with_for_update().execution_options(populate_existing=True))
    owner.feature_notices={**(owner.feature_notices or {}),ENABLED_ONCE:True}


async def enabled_once(db,user):
    if (user.feature_notices or {}).get(ENABLED_ONCE):return True
    # Preserve the experience of people who enabled the feature before this
    # prompt shipped, including those who subsequently turned it off.
    evidence=await db.scalar(select(ActivityEvent.id).where(ActivityEvent.user_id==user.id,
        ActivityEvent.event_type=='free_list_approved').limit(1))
    if not evidence:
        evidence=await db.scalar(select(FeedMintApproval.id).where(FeedMintApproval.user_id==user.id,
            FeedMintApproval.status=='active').limit(1))
    if not evidence:return False
    await remember_enabled(db,user.id)
    await db.commit()
    return True


def tables(journal):
    journal.execute('CREATE TABLE IF NOT EXISTS feed_approvals (id TEXT PRIMARY KEY,intent TEXT NOT NULL,snapshot TEXT NOT NULL,revoked INTEGER NOT NULL DEFAULT 0)')
    journal.commit()


def public(row):
    from app.services.auto_arm_funding import fee_ceiling
    return {'effective_fee_cap_wei':str(fee_ceiling(row.snapshot['chain_id'],row.snapshot['fee_cap_wei'])),'id':row.id,'status':'expired' if row.status=='active' and aware(row.expires_at)<=datetime.now(timezone.utc) else row.status,'snapshot':row.snapshot,'expires_at':row.expires_at,'note':row.note}


async def pin(db,journal,approval_id,vault):
    row=await db.get(FeedMintApproval,approval_id)
    if not row or row.status not in ('registering','active'):raise ValueError('Free-list approval is inactive.')
    s=row.snapshot
    grant=await automatic.grant_for(db,row.grant_id,row.user_id)
    wallet=await db.get(Wallet,row.wallet_id)
    policy=vault.policy(grant)
    if (automatic.digest(s)!=row.context_hash or s['id']!=row.id or s['user_id']!=row.user_id
        or s['grant_id']!=grant.id or s['wallet_id']!=grant.wallet_id or row.wallet_id!=grant.wallet_id
        or not wallet or wallet.user_id!=row.user_id or wallet.archived_at
        or s['account'].lower()!=policy['account'].lower() or s['chain_id']!=policy['chain_id']
        or s['expiry']!=int(aware(row.expires_at).timestamp()) or s['expiry']>policy['expires_at']
        or s['expiry']<=datetime.now(timezone.utc).timestamp()
        or not quantity_allowed(s,s['quantity']) or not 0<s['fee_cap_wei']<=policy['max_task_wei']
        or s['sources']!=list(SOURCE_NAMES) or s['free_only'] is not True):
        raise ValueError('Standing approval differs from the independently provisioned limits.')
    tables(journal)
    prior=journal.execute('SELECT intent,revoked FROM feed_approvals WHERE id=?',(row.id,)).fetchone()
    if prior and (prior['intent']!=row.context_hash or prior['revoked']):raise ValueError('A standing approval cannot be changed or revived; replace it with new consent.')
    journal.execute('INSERT OR IGNORE INTO feed_approvals(id,intent,snapshot) VALUES (?,?,?)',(row.id,row.context_hash,json.dumps(s,sort_keys=True)))
    journal.commit()
    return {'id':row.id,'context_hash':row.context_hash}


async def verify_task(db,journal,task,s,grant):
    row=await db.get(FeedMintApproval,s['feed_approval_id'])
    tables(journal)
    pin=journal.execute('SELECT * FROM feed_approvals WHERE id=?',(s['feed_approval_id'],)).fetchone()
    if not row or row.status!='active' or not pin or pin['revoked'] or pin['intent']!=row.context_hash or automatic.digest(row.snapshot)!=pin['intent']:
        raise ValueError('Free-list standing approval is inactive or differs from its signer pin.')
    r=json.loads(pin['snapshot'])
    if (r['user_id']!=grant.user_id or r['wallet_id']!=grant.wallet_id or r['grant_id']!=grant.id
        or r['chain_id']!=s['chain_id'] or r['account'].lower()!=s['account'].lower()
        or s['price_wei']!=0 or s['price_cap_wei']!=0 or not quantity_allowed(r,s['quantity'])
        or not 0<s['fee_cap_wei']<=s['total_cap_wei']<=r['fee_cap_wei'] or s['expiry']>r['expiry']
        or not s.get('phase_identity') or s.get('schedule_mode')!='phase_open'):
        raise ValueError('Free-list mint exceeds the standing approval.')
    # The signer independently checks daily-list provenance, not an API-provided flag.
    source=s.get('feed_source') or {}
    from datetime import date
    day=date.fromisoformat(source.get('list_date',''))
    if not aware(row.created_at).astimezone(ZoneInfo('Africa/Lagos')).date()<=day<=datetime.now(timezone.utc).astimezone(ZoneInfo('Africa/Lagos')).date():
        raise ValueError('The daily-list opportunity predates this standing approval.')
    groups=await daily_collections(db,day,row.user_id)
    if not any(g['drop'].id==source.get('drop_id') and g['drop'].chain_id==s['chain_id']
        and bool(g['drop'].contract_address) and g['drop'].contract_address.lower()==s['contract'].lower()
        and collection_slug(g['drop'].mint_page_url)==collection_slug(s['mint_page_url'])
        and any(p.id==source.get('post_id') and
        (p.author_username or '').lower() in r['sources'] for p,_ in g['mentions']) for g in groups):
        raise ValueError('This collection is no longer present in an approved daily list.')
    return row


async def broker(approval_id,operation='register'):
    import httpx
    from pathlib import Path
    from app.config import settings
    token=Path(settings.AUTOMATIC_SIGNER_TOKEN_FILE).read_text().strip()
    async with httpx.AsyncClient(timeout=30,trust_env=False) as client:
        response=await client.post(settings.AUTOMATIC_SIGNER_URL+f'/feed-approvals/{approval_id}/{operation}',headers={'Authorization':'Bearer '+token})
        response.raise_for_status();return response.json()


async def create(db,user,req):
    if not req.consent:raise HTTPException(422,'Approve the wallet, quantity, free-only scope and gas limit.')
    await automatic.lock_execution(db)
    await automatic.require_running(db,user.id)
    grant=await automatic.grant_for(db,req.grant_id,user.id)
    from app.services.networks import require_currency
    require_currency(grant.chain_id,req.native_symbol)
    fee=automatic.wei(req.fee_cap)
    now=datetime.now(timezone.utc)
    if not 0<fee<=int(grant.scope['max_task_wei']) or req.expires_at.tzinfo is None or not now<req.expires_at<=min(aware(grant.expires_at),now+timedelta(days=60)):
        raise HTTPException(422,'Choose a positive gas cap and an expiry within your signing approval (up to 60 days).')
    approval_id=str(uuid.UUID(req.request_id))
    busy=(await db.scalars(select(FeedMintApproval).where(FeedMintApproval.user_id==user.id,
        FeedMintApproval.wallet_id==grant.wallet_id,FeedMintApproval.id!=approval_id,
        FeedMintApproval.status.in_(('active','registering','revoking')),FeedMintApproval.expires_at>now))).all()
    if any(r.snapshot['chain_id']==grant.chain_id for r in busy):
        raise HTTPException(409,'This wallet already has a free-drop approval for this network. Turn it off before replacing its limits.')
    s={'id':approval_id,'user_id':user.id,'wallet_id':grant.wallet_id,'grant_id':grant.id,
        'chain_id':grant.chain_id,'account':grant.account,'quantity':req.quantity,'fee_cap_wei':fee,
        'expiry':int(req.expires_at.timestamp()),'sources':list(SOURCE_NAMES),'free_only':True}
    if getattr(req,'quantity_mode','fixed')=='wallet_max':s['quantity_mode']='wallet_max'
    if not quantity_allowed(s,s['quantity']):raise HTTPException(422,'Invalid quantity approval.')
    row=await db.get(FeedMintApproval,approval_id)
    if row:
        if row.user_id!=user.id or row.context_hash!=automatic.digest(s):raise HTTPException(409,'Approval request was already used with different settings.')
        if row.status!='registering':return public(row)
    else:
        row=FeedMintApproval(id=approval_id,user_id=user.id,wallet_id=grant.wallet_id,grant_id=grant.id,
            status='registering',snapshot=s,context_hash=automatic.digest(s),expires_at=req.expires_at)
        db.add(row)
    await db.commit()
    try:confirmed=await broker(row.id)
    except Exception:raise HTTPException(503,'Approval saved; signer confirmation is pending. Retry the same approval.') from None
    await automatic.lock_execution(db);await db.refresh(row)
    if row.status!='registering' or confirmed.get('context_hash')!=row.context_hash:raise HTTPException(409,'Standing approval changed during confirmation.')
    row.status='active';row.note='Watching Today for eligible free phases. Gas limits apply.'
    await remember_enabled(db,user.id)
    db.add(ActivityEvent(user_id=user.id,event_type='free_list_approved',label='Free drops automation enabled',detail=row.note,is_demo=False,icon_name='gem'))
    await db.commit();return public(row)


async def enable_for_today_wallet(db,user,req):
    from app.models import FeedWalletSelection
    from app.services.parser import format_wei_to_eth
    from types import SimpleNamespace
    if not req.consent:raise HTTPException(422,'Tap Turn on to approve free mints at your wallet maximum using saved gas limits.')
    await automatic.require_running(db,user.id)
    selection=await db.get(FeedWalletSelection,user.id)
    wallet_id=req.wallet_id or (selection.wallet_id if selection else None)
    query=select(Wallet).where(Wallet.user_id==user.id,Wallet.archived_at.is_(None),Wallet.is_demo.is_(False))
    wallet=await db.scalar(query.where(Wallet.id==wallet_id)) if wallet_id else await db.scalar(query.order_by(Wallet.is_default.desc(),Wallet.id).limit(1))
    if not wallet:raise HTTPException(409,'Choose a signing wallet on Today first.')
    now=datetime.now(timezone.utc)
    grants=(await db.scalars(select(AutomaticGrant).where(AutomaticGrant.user_id==user.id,
        AutomaticGrant.wallet_id==wallet.id,AutomaticGrant.status=='enabled',AutomaticGrant.expires_at>now)
        .order_by(AutomaticGrant.expires_at.desc(),AutomaticGrant.id))).all()
    by_chain={}
    for grant in grants:
        if grant.chain_id not in by_chain:by_chain[grant.chain_id]=grant
    if not by_chain:raise HTTPException(409,'Set up or renew this wallet’s signing approval in Wallet first.')
    enabled=[];errors=[]
    for chain,grant in by_chain.items():
        try:
            existing=await db.scalar(select(FeedMintApproval).where(FeedMintApproval.user_id==user.id,
                FeedMintApproval.wallet_id==wallet.id,FeedMintApproval.status.in_(('active','registering','revoking')),
                FeedMintApproval.expires_at>now,FeedMintApproval.snapshot['chain_id'].as_integer()==chain))
            if existing:
                if existing.snapshot.get('quantity_mode')!='wallet_max':
                    raise HTTPException(409,'Auto-Arming already has a saved fixed quantity. Turn that approval off before changing its limits.')
                if existing.status=='revoking':raise HTTPException(409,'Finish turning off the previous approval before enabling again.')
                grant=await automatic.grant_for(db,existing.grant_id,user.id)
                if existing.status=='active':
                    await remember_enabled(db,user.id);await db.commit();enabled.append(public(existing));continue
                s=existing.snapshot
                key=existing.id;fee=s['fee_cap_wei'];expiry=aware(existing.expires_at)
            else:
                key=str(uuid.uuid5(uuid.UUID(req.request_id),grant.id))
                from app.services.auto_arm_funding import fee_ceiling
                fee=fee_ceiling(chain,int(grant.scope['max_task_wei']))
                expiry=min(aware(grant.expires_at),now+timedelta(days=60))
            enabled.append(await create(db,user,SimpleNamespace(request_id=key,grant_id=grant.id,
                quantity=MAX_WALLET_QUANTITY,quantity_mode='wallet_max',fee_cap=format_wei_to_eth(fee),
                expires_at=expiry,native_symbol=symbol(chain),consent=True)))
        except HTTPException as error:
            await db.rollback();errors.append((error.status_code,str(error.detail)));break
    if errors:
        prefix='Auto-Arming is on for some networks. ' if enabled else ''
        raise HTTPException(503 if enabled else errors[0][0],prefix+errors[0][1])
    return {'approvals':enabled,'enabled_once':True,'wallet_id':wallet.id}


async def revoke(db,row,vault):
    row.status='revoked';row.note='Free-drop automation is off.'
    tasks=(await db.scalars(select(MintTask).join(MintAuthorization,MintTask.authorization_id==MintAuthorization.id)
        .where(MintAuthorization.snapshot['feed_approval_id'].as_string()==row.id,
            MintTask.status.not_in(automatic.TERMINAL)))).all()
    journal=vault.journal()
    try:
        tables(journal)
        journal.execute('UPDATE feed_approvals SET revoked=1 WHERE id=?',(row.id,));journal.commit()
        for task in tasks:
            signed=journal.execute('SELECT * FROM signed WHERE task=?',(task.id,)).fetchone()
            if signed or task.signed_tx_raw:
                # Lost DB commit: retain the original bytes/nonce and liabilities,
                # disable new broadcasts, and continue receipt tracking.
                if signed:
                    task.signed_tx_raw=signed['raw'];task.transaction_hash=signed['hash'];task.assigned_nonce=signed['nonce']
                from app.services.auto_arm_funding import fund,signed_quantity
                auth=await db.get(MintAuthorization,task.authorization_id)
                grant=await db.get(AutomaticGrant,auth.grant_id)
                await fund(db,task,auth,grant,restore=True,journal=journal)
                task.prepared_calldata=json.dumps({'quantity':signed_quantity(task.signed_tx_raw,auth.quantity)})
                task.status='uncertain';task.broadcast_disabled_at=datetime.now(timezone.utc)
                task.failure_reason='Automation disabled. An existing signed transaction remains tracked.'
            else:
                if task.status not in ('armed','preparing'):raise ValueError('An in-flight task needs receipt reconciliation before cancellation.')
                task.status='disarmed';task.failure_reason='Free-drop standing approval was turned off.'
                await automatic.release_reservation(db,task)
    finally:journal.close()


async def arm(db,row,group,check,user,wallet):
    from app.api.drops import prepare_card,SetupCard
    from app.api.tasks import arm_mint_task
    from app.schemas.task import ArmTaskRequest
    from app.models import MintPlan
    from app.services.mint_stage_choice import select_stage
    from app.services.phase_identity import stage_kind
    from app.services.parser import format_wei_to_eth
    from types import SimpleNamespace
    r=row.snapshot
    if not isinstance(check.result,dict) or not check.result.get('contract_address'):
        row.note='Wallet eligibility is not verified yet. Waiting for collection details; no mint was armed.'
        return
    list_day=group.get('list_date') or datetime.now(timezone.utc).astimezone(ZoneInfo('Africa/Lagos')).date()
    # A cancelled or failed opportunity must not be silently recreated on every
    # feed refresh. Explicit per-collection review remains available to the user.
    previous=await db.scalar(select(MintTask.id).join(MintAuthorization,MintTask.authorization_id==MintAuthorization.id).where(
        MintAuthorization.snapshot['feed_approval_id'].as_string()==row.id,
        func.lower(MintAuthorization.snapshot['contract'].as_string())==check.result['contract_address'].lower()))
    if previous:return
    grant=await automatic.grant_for(db,row.grant_id,user.id)
    if grant.budget_wei-grant.spent_wei-grant.reserved_wei<=0:
        row.note=('Waiting for pending mint reservations to settle.' if grant.budget_wei-grant.spent_wei>0
            else 'The signing allowance is used up. Renew the wallet spending approval.')
        return
    if row.note in ('The remaining signing allowance is below your chosen gas cap. Review the wallet spending approval or gas cap.',
        'Waiting for pending mint reservations to settle.'):
        row.note='Watching Today for eligible free phases. Gas limits apply.'
    display=feed_checks.presentation(check)
    from app.services.free_phase_selection import eligible_phases
    phases=eligible_phases(display,r,grant.scope['mint_kinds'])
    if not phases:return
    phase=phases[0]
    s={'chain_id':r['chain_id'],'account':r['account'],'contract':check.result['contract_address'],'feed_approval_id':row.id}
    from app.services.copy_mints import no_mixed_stage_copy
    await automatic.lock_execution(db);await no_mixed_stage_copy(db,s)
    await db.commit()
    saved=await prepare_card(group['drop'].id,SetupCard(wallet_id=wallet.id,stage_uuid=phase['id']),user,db)
    plan=await db.get(MintPlan,saved['id'])
    quantity=r['quantity']
    if r.get('quantity_mode')=='wallet_max':
        # Refresh OpenSea and on-chain wallet consumption rather than using a
        # collection-wide default or the cached feed allowance.
        from app.services.mint_stage_choice import stages
        fresh,_=await stages(db,plan,user.id)
        selected=next((p for p in fresh['stages'] if p['id']==phase['id']),None)
        if not selected or selected['eligibility']!='eligible' or selected.get('price_wei')!='0':return
        quantity=selected.get('remaining')
        if not isinstance(quantity,int) or not quantity_allowed(r,quantity):return
    # No active task exists (checked above). Refresh even an unchanged UUID:
    # a budget wait may have outlived the saved plan's original schedule.
    await select_stage(db,plan,SimpleNamespace(stage_uuid=phase['id'],quantity=quantity),user.id)
    from app.api.mint_plans import automatic_context
    await automatic_context(plan.id,user,db)
    grant=await automatic.grant_for(db,row.grant_id,user.id)
    # A gas cap is a maximum, not a minimum transaction price. Use only the
    # remaining already-approved authority and unreserved native balance.
    from web3 import AsyncWeb3
    web3=AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(automatic.rpc_for(grant.chain_id),request_kwargs={'timeout':15}))
    try:
        balance=await web3.eth.get_balance(AsyncWeb3.to_checksum_address(grant.account))
    finally:
        await web3.provider.disconnect()
    from app.services.auto_arm_funding import fee_ceiling
    fee_cap=min(fee_ceiling(grant.chain_id,r['fee_cap_wei']),grant.scope['max_task_wei'],
        grant.budget_wei-grant.spent_wei,max(0,balance))
    if fee_cap<=0:
        row.note='Not enough available native tokens for gas.'
        return
    now=datetime.now(timezone.utc)
    req=ArmTaskRequest(native_symbol=symbol(r['chain_id']),
        guided=True,plan_id=plan.id,wallet_id=wallet.id,grant_id=grant.id,drop_id=plan.automatic_drop_id,
        stage_id=plan.automatic_stage_id,quantity=quantity,mint_kind=stage_kind(phase['type']),
        price_cap_eth='0',fee_cap_eth=format_wei_to_eth(fee_cap),total_cap_eth=format_wei_to_eth(fee_cap),
        expires_at=min(aware(plan.ends_at),aware(row.expires_at)),scheduled_for_utc=max(aware(plan.starts_at),now+timedelta(seconds=1)),
        conditional_eligibility=stage_kind(phase['type'])!='public' and aware(plan.starts_at)>now,
        schedule_mode='phase_open',user_consent_confirmed=True,
        idempotency_key='free-list-'+automatic.digest([row.id,r['chain_id'],s['contract'].lower()]),
        feed_approval_id=row.id,feed_source={'drop_id':group['drop'].id,'list_date':list_day.isoformat(),'post_id':next(p.id for p,_ in group['mentions'] if (p.author_username or '').lower() in r['sources'])})
    await arm_mint_task(req,user,db)
    return phase


async def step(factory):
    now=datetime.now(timezone.utc)
    async with factory() as db:
        row=await db.scalar(select(FeedMintApproval).where(FeedMintApproval.status=='active',FeedMintApproval.expires_at>now,
            (FeedMintApproval.last_checked_at.is_(None)) | (FeedMintApproval.last_checked_at<now-timedelta(seconds=30)))
            .order_by(FeedMintApproval.last_checked_at).limit(1))
        if not row:return False
        user=await db.get(User,row.user_id);wallet=await db.get(Wallet,row.wallet_id)
        row.last_checked_at=now;await db.commit()
        if not user or not user.is_active or user.deleted_at or user.automation_paused or not wallet or wallet.archived_at:return True
        grant=await db.get(AutomaticGrant,row.grant_id)
        if (grant and grant.status=='enabled' and aware(grant.expires_at)>now
            and grant.budget_wei-grant.spent_wei-grant.reserved_wei>0
            and row.note=='The remaining signing allowance is below your chosen gas cap. Review the wallet spending approval or gas cap.'):
            row.note='Watching Today for eligible free phases. Gas limits apply.'
        groups=await daily_collections(db,now.astimezone(ZoneInfo('Africa/Lagos')).date(),user.id)
        groups=[g for g in groups if g['drop'].chain_id==row.snapshot['chain_id'] and any((p.author_username or '').lower() in row.snapshot['sources'] for p,_ in g['mentions'])]
        await feed_checks.queue_checks(db,user,wallet,[g['drop'] for g in groups])
        from types import SimpleNamespace
        candidates=[{'drop':SimpleNamespace(id=g['drop'].id,name=g['drop'].name),'list_date':now.astimezone(ZoneInfo('Africa/Lagos')).date(),'mentions':[(SimpleNamespace(id=p.id,author_username=p.author_username),None) for p,_ in g['mentions']]} for g in groups]
        approval_id=row.id
    for group in candidates:
        async with factory() as db:
            try:
                row=await db.get(FeedMintApproval,approval_id)
                if not row or row.status!='active' or aware(row.expires_at)<=datetime.now(timezone.utc):continue
                user=await db.get(User,row.user_id);wallet=await db.get(Wallet,row.wallet_id)
                if not user or user.automation_paused or not user.is_active or user.deleted_at or not wallet or wallet.archived_at:continue
                check=await db.get(FeedWalletCheck,(user.id,wallet.id,group['drop'].id),populate_existing=True)
                if not check:continue
                phase=await arm(db,row,group,check,user,wallet)
                if phase:
                    row.note=f"Automatically armed — {group['drop'].name}: {phase['name']}. Gas limits apply."
                await db.commit()
                # Publish the task first; observations have their own bounded transaction.
                from app.services.reliability import observe,best_effort
                await best_effort(observe,factory,approval_id,group['drop'].id)
                if phase:
                    from app.services.reliability import arm_result
                    await best_effort(arm_result,factory,approval_id,group['drop'].id)
            except Exception as error:
                logging.getLogger('mintly.free_drops').warning('Preparation deferred approval_id=%s collection_id=%s reason=%s detail=%s',approval_id,group['drop'].id,type(error).__name__,preparation_error(error))
                await db.rollback()
                row=await db.get(FeedMintApproval,approval_id)
                if not row:continue
                row.note=f"{group['drop'].name}: {preparation_error(error)}"
                await db.commit()
                from app.services.reliability import observe,arm_result,best_effort
                await best_effort(observe,factory,approval_id,group['drop'].id)
                await best_effort(arm_result,factory,approval_id,group['drop'].id,error)
    return True


def preparation_error(error):
    from app.services.opensea import OpenSeaUnavailable
    from app.services.mint_diagnostics import PREPARATION_REASONS
    if isinstance(error,OpenSeaUnavailable):
        return PREPARATION_REASONS.get(error.mint_reason,str(error))
    if isinstance(error,HTTPException):return str(error.detail)
    if isinstance(error,KeyError):return 'Collection details are incomplete. Waiting for a verified eligibility check; no mint was armed.'
    return 'Auto-Arming preparation failed. No transaction was sent. The error was recorded for support.'


async def loop(factory):
    while True:
        worked=False
        try:worked=await step(factory)
        except Exception as error:logging.getLogger('mintly.free_drops').warning('Free-drop checks deferred (%s).',type(error).__name__)
        # Drain due wallets without adding five seconds per account. Provider
        # calls still pass through the shared pacing and eligibility queues.
        await asyncio.sleep(0.1 if worked else 5)
