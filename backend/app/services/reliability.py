"""Observation-only reliability measurements. Never calls a signer or provider."""
import asyncio,hashlib,json,logging,math
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func,or_,tuple_,case
from app.models import (MintOpportunity,FeedMintApproval,FeedWalletCheck,AutomaticGrant,
    User,Wallet,Drop,MintTask,MintAuthorization,MintAttemptDiagnostic,CopyEvent,CopyWatch)
from app.services.mint_plans import aware
from app.services.mint_lifecycle import ACTIVE,MARKET_REASONS,OPERATOR_REASONS,SERVICE_REASONS,reason_from_note,reason_text


async def best_effort(operation,*args):
    """Called after execution commits. Reporting must not hold the next mint up."""
    try:
        async with asyncio.timeout(.1):await operation(*args)
    except TimeoutError:
        logging.getLogger('mintly.reliability').warning('Observation deadline reached; execution continues.')
    except Exception:
        logging.getLogger('mintly.reliability').warning('Observation unavailable; execution continues.')


def arming_reason(error):
    from fastapi import HTTPException
    from app.services.opensea import OpenSeaUnavailable
    from app.services.mint_diagnostics import PREPARATION_REASONS
    if isinstance(error,OpenSeaUnavailable):
        return error.mint_reason if error.mint_reason in PREPARATION_REASONS else 'eligibility_provider_unavailable'
    if isinstance(error,HTTPException):
        if error.detail=='The isolated signer has not confirmed this policy and keystore are ready. No task was armed.':return 'wallet_approval_changed'
        if error.detail=='Automatic policy budget is insufficient, including pending reservations.':return 'budget_wait'
        if error.status_code==429:return 'daily_budget_wait'
        if error.status_code==503:return 'arming_unavailable'
        return 'arming_rejected'
    return 'incomplete_check' if isinstance(error,KeyError) else 'arming_error'


async def arm_result(factory,approval_id,drop_id,error=None):
    """Record a safe category after execution's transaction has committed/rolled back."""
    try:
        async with factory() as db:
            approval=await db.get(FeedMintApproval,approval_id)
            if not approval:return
            rows=(await db.scalars(select(MintOpportunity).where(MintOpportunity.user_id==approval.user_id,
                MintOpportunity.wallet_id==approval.wallet_id,MintOpportunity.drop_id==drop_id))).all()
            for row in rows:
                row.last_error_code=arming_reason(error) if error else None
                row.last_error_at=datetime.now(timezone.utc) if error else None
            await db.commit()
    except Exception:
        logging.getLogger('mintly.reliability').warning('Arming observation unavailable; execution continues.')


async def observe(factory,approval_id,drop_id,*,now=None):
    """Only fresh verified eligible collections count; repeated polls are one row."""
    now=now or datetime.now(timezone.utc)
    try:
        async with factory() as db:
            approval=await db.get(FeedMintApproval,approval_id)
            if not approval or approval.status!='active' or aware(approval.expires_at)<=now:return
            user=await db.get(User,approval.user_id);wallet=await db.get(Wallet,approval.wallet_id)
            grant=await db.get(AutomaticGrant,approval.grant_id);drop=await db.get(Drop,drop_id)
            if (not user or not user.is_active or user.deleted_at or user.automation_paused or not wallet
                or wallet.archived_at or wallet.user_id!=user.id or not grant or grant.status!='enabled'
                or grant.user_id!=user.id or grant.wallet_id!=wallet.id
                or aware(grant.expires_at)<=now or not drop or drop.chain_id!=grant.chain_id):return
            check=await db.get(FeedWalletCheck,(user.id,wallet.id,drop_id))
            if not check or check.status!='complete' or not check.expires_at or aware(check.expires_at)<=now:return
            contract=(check.result or {}).get('contract_address')
            if not contract or not drop.contract_address or contract.lower()!=drop.contract_address.lower():return
            from app.services.feed_checks import presentation
            from app.services.free_phase_selection import eligible_phases
            phases=eligible_phases(presentation(check,now),approval.snapshot,grant.scope['mint_kinds'])
            if not phases:return
            phase=phases[0]
            opens=datetime.fromisoformat(phase['starts_at']);closes=datetime.fromisoformat(phase['ends_at'])
            if opens.tzinfo is None or closes.tzinfo is None or opens>=closes:return
            key=hashlib.sha256(json.dumps([user.id,wallet.id,grant.chain_id,contract.lower()]).encode()).hexdigest()
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            insert=pg_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
            values=dict(id=key,user_id=user.id,wallet_id=wallet.id,drop_id=drop.id,chain_id=grant.chain_id,
                contract=contract.lower(),phase_id=phase['id'],opens_at=opens,
                closes_at=closes,eligible_at=now,last_seen_at=now,created_at=now,updated_at=now)
            await db.execute(insert(MintOpportunity).values(**values).on_conflict_do_update(index_elements=['id'],
                set_={k:values[k] for k in ('drop_id','phase_id','opens_at','closes_at','last_seen_at','updated_at')}))
            await db.commit()
    except Exception:
        logging.getLogger('mintly.reliability').warning('Opportunity observation unavailable; execution continues.')


def latency(values):
    values=sorted(values)
    def percentile(p):return round(values[max(0,math.ceil(len(values)*p)-1)],3) if values else None
    return {'samples':len(values),'p50_seconds':percentile(.5),'p95_seconds':percentile(.95)}


async def report(db,*,hours=24,now=None):
    now=now or datetime.now(timezone.utc);since=now-timedelta(hours=hours)
    # Scalars deliberately exclude signed bytes, calldata, proofs and authorization snapshots.
    rows=(await db.execute(select(MintTask.id,MintTask.wallet_id,MintTask.status,MintTask.scheduled_for_utc,
        MintTask.preparation_started_at,MintTask.submitted_at,MintTask.expires_at_utc,MintTask.failure_reason,
        MintTask.copy_rule_id,MintAuthorization.snapshot['feed_approval_id'].as_string().label('feed_id'),
        CopyEvent.created_at.label('copy_observed_at'),
        User.username,func.coalesce(MintAuthorization.snapshot['drop_name'].as_string(),Drop.name,'Unknown collection').label('collection'),
        MintAuthorization.snapshot['chain_id'].as_integer().label('chain_id'),
        func.lower(MintAuthorization.snapshot['contract'].as_string()).label('contract'))
        .join(MintAuthorization,MintTask.authorization_id==MintAuthorization.id)
        .outerjoin(CopyEvent,CopyEvent.task_id==MintTask.id)
        .join(Wallet,MintTask.wallet_id==Wallet.id).join(User,Wallet.user_id==User.id).outerjoin(Drop,MintTask.drop_id==Drop.id)
        .where(MintTask.is_demo.is_(False),func.coalesce(CopyEvent.created_at,MintTask.scheduled_for_utc)>=since,
            func.coalesce(CopyEvent.created_at,MintTask.scheduled_for_utc)<now)
        .order_by(func.coalesce(CopyEvent.created_at,MintTask.scheduled_for_utc).desc(),MintTask.id))).mappings().all()
    ids=[r['id'] for r in rows]
    diagnostics=(await db.execute(select(MintAttemptDiagnostic.task_id,MintAttemptDiagnostic.error_category,
        MintAttemptDiagnostic.started_at,MintAttemptDiagnostic.outcome).where(
        MintAttemptDiagnostic.task_id.in_(ids),MintAttemptDiagnostic.phase.in_(('preparation','schedule')))
        .order_by(MintAttemptDiagnostic.started_at.desc(),MintAttemptDiagnostic.finished_at.desc(),MintAttemptDiagnostic.id.desc()))).mappings().all() if ids else []
    latest={}
    for d in diagnostics:latest.setdefault(d['task_id'],d)
    outcomes=Counter();groups=defaultdict(lambda:{'tasks':set(),'opportunities':set(),'copy_events':set(),'examples':[],'last_seen':since})
    by_mode=defaultdict(lambda:{'tasks':0,'submitted':0,'confirmed':0,'latency':[],'invalid_time_samples':0})
    task_keys=set();needs_review=0;recent_failures=[]
    for r in rows:
        mode='copy' if r['copy_rule_id'] or r['copy_observed_at'] else 'auto_arm' if r['feed_id'] else 'scheduled'
        entry=by_mode[mode];entry['tasks']+=1
        if r['submitted_at']:
            entry['submitted']+=1
            baseline=r['copy_observed_at'] if mode=='copy' else r['scheduled_for_utc']
            seconds=(aware(r['submitted_at'])-aware(baseline)).total_seconds() if baseline else None
            if seconds is not None and seconds>=0:entry['latency'].append(seconds)
            else:entry['invalid_time_samples']+=1
        if r['status']=='confirmed':entry['confirmed']+=1
        if r['feed_id']:task_keys.add((r['wallet_id'],r['chain_id'],r['contract']))
        d=latest.get(r['id']);reason=(d['error_category'] if d else None) or reason_from_note(r['failure_reason'])
        if r['status'] in ('confirmed','already_minted','disarmed'):outcome=r['status']
        elif r['status'] in ACTIVE and aware(r['expires_at_utc'])>now:outcome='pending'
        elif r['status']=='reverted':outcome='reverted'
        elif reason=='supply_exhausted':outcome='sold_out'
        elif reason in MARKET_REASONS:outcome='wallet_or_stage_constraint'
        elif reason in SERVICE_REASONS:outcome='service_failure_needs_review';needs_review+=1
        elif reason in OPERATOR_REASONS:outcome='approval_needs_review';needs_review+=1
        else:outcome='unknown_needs_review';needs_review+=1
        outcomes[outcome]+=1
        if outcome not in ('confirmed','already_minted','disarmed','pending') and len(recent_failures)<20:
            recent_failures.append({'task_id':r['id'],'username':r['username'],'collection':r['collection'],
                'outcome':outcome,'reason_code':reason,'reason_text':reason_text(reason),'chain_id':r['chain_id']})
    # Warnings are independent of the opening cohort: tomorrow's failed preflight
    # must be visible today. Use the task-id diagnostic index, not provider calls.
    cutoff=now-timedelta(minutes=30)
    warning_tasks=(await db.execute(select(MintTask.id,MintAuthorization.snapshot['chain_id'].as_integer().label('chain_id'),
        User.username,func.coalesce(MintAuthorization.snapshot['drop_name'].as_string(),Drop.name,'Unknown collection').label('collection'))
        .join(MintAuthorization,MintTask.authorization_id==MintAuthorization.id).join(Wallet,MintTask.wallet_id==Wallet.id)
        .join(User,Wallet.user_id==User.id).outerjoin(Drop,MintTask.drop_id==Drop.id).where(MintTask.is_demo.is_(False),
            MintTask.status.in_(('armed','preparing','failed','expired')),Wallet.archived_at.is_(None),
            User.is_active.is_(True),User.deleted_at.is_(None),User.automation_paused.is_(False),
            or_(MintTask.updated_at>=cutoff,MintTask.preflight_checked_at>=cutoff,MintTask.preparation_started_at>=cutoff)))).mappings().all()
    warning_details={r['id']:r for r in warning_tasks};warning_chains={r['id']:r['chain_id'] for r in warning_tasks}
    recent=(await db.execute(select(MintAttemptDiagnostic.task_id,MintAttemptDiagnostic.error_category,
        MintAttemptDiagnostic.started_at,MintAttemptDiagnostic.outcome).where(MintAttemptDiagnostic.task_id.in_(warning_chains),
        MintAttemptDiagnostic.started_at>=cutoff).order_by(MintAttemptDiagnostic.started_at.desc(),
            MintAttemptDiagnostic.finished_at.desc(),MintAttemptDiagnostic.id.desc()))).mappings().all() if warning_chains else []
    seen=set()
    for d in recent:
        if d['task_id'] in seen:continue
        seen.add(d['task_id']);reason=d['error_category']
        if reason in (None,'none') or reason in MARKET_REASONS:continue
        group=groups[(warning_chains[d['task_id']],reason)];group['tasks'].add(d['task_id'])
        if len(group['examples'])<5:
            r=warning_details[d['task_id']];group['examples'].append({'task_id':r['id'],'username':r['username'],'collection':r['collection']})
        group['last_seen']=max(group['last_seen'],aware(d['started_at']))
    opportunities=(await db.scalars(select(MintOpportunity).where(or_(
        (MintOpportunity.opens_at>=since)&(MintOpportunity.opens_at<now),
        MintOpportunity.last_error_at>=since,
        tuple_(MintOpportunity.wallet_id,MintOpportunity.chain_id,MintOpportunity.contract).in_(task_keys))))).all()
    effective={}
    if opportunities:
        # Arming may predate the report window, or the tracked opening may move.
        linked=(await db.execute(select(MintTask.wallet_id,
            MintAuthorization.snapshot['chain_id'].as_integer().label('chain_id'),
            func.lower(MintAuthorization.snapshot['contract'].as_string()).label('contract'),
            MintTask.scheduled_for_utc,MintTask.expires_at_utc).join(MintAuthorization,
            MintTask.authorization_id==MintAuthorization.id).where(MintTask.is_demo.is_(False),
            MintTask.wallet_id.in_({o.wallet_id for o in opportunities}),
            MintAuthorization.snapshot['feed_approval_id'].as_string().is_not(None))
            .order_by(case((MintTask.status.in_(('confirmed','already_minted')),0),(MintTask.status.in_(ACTIVE),1),else_=2),
                MintTask.created_at.desc(),MintTask.id))).mappings().all()
        for r in linked:
            key=(r['wallet_id'],r['chain_id'],r['contract'])
            task_keys.add(key);effective.setdefault(key,(aware(r['scheduled_for_utc']),aware(r['expires_at_utc'])))
    observed=opportunities
    opportunities=[o for o in observed if since<=effective.get((o.wallet_id,o.chain_id,o.contract),(aware(o.opens_at),None))[0]<now]
    matched=sum((o.wallet_id,o.chain_id,o.contract) in task_keys for o in opportunities)
    unmatched=[o for o in opportunities if (o.wallet_id,o.chain_id,o.contract) not in task_keys]
    blocked=Counter()
    context=(await db.execute(select(MintOpportunity.id,User.username,Drop.name,
        User.is_active,User.automation_paused,User.deleted_at,Wallet.archived_at)
        .join(User,MintOpportunity.user_id==User.id).join(Drop,MintOpportunity.drop_id==Drop.id)
        .join(Wallet,MintOpportunity.wallet_id==Wallet.id).where(MintOpportunity.id.in_([o.id for o in observed])))).mappings().all() if observed else []
    context={r['id']:r for r in context}
    for o in observed:
        if (o.wallet_id,o.chain_id,o.contract) not in task_keys and o.last_error_code and o.last_error_at and aware(o.last_error_at)>=since:
            blocked[o.last_error_code]+=1
            c=context.get(o.id)
            if (c and c['is_active'] and not c['automation_paused'] and not c['deleted_at'] and not c['archived_at']
                and aware(o.last_error_at)>=now-timedelta(minutes=30) and o.last_error_code not in ('budget_wait','daily_budget_wait')):
                group=groups[(o.chain_id,o.last_error_code)];group['opportunities'].add(o.id)
                if len(group['examples'])<5:group['examples'].append({'opportunity_id':o.id,'username':c['username'],'collection':c['name']})
                group['last_seen']=max(group['last_seen'],aware(o.last_error_at))
    # Copy already persists pre-task failures. Reuse that evidence instead of
    # inventing eligible opportunities from unverified followed-wallet signals.
    copy_unarmed=Counter()
    copy_errors=(await db.execute(select(CopyEvent.id,CopyEvent.last_error_category,CopyEvent.last_checked_at,
        CopyEvent.observation['chain_id'].as_integer().label('chain_id'),
        CopyEvent.observation['name'].as_string().label('collection'),User.username)
        .join(CopyWatch,CopyEvent.watch_id==CopyWatch.id).join(User,CopyEvent.user_id==User.id)
        .where(CopyEvent.created_at>=since,CopyEvent.created_at<now,CopyEvent.task_id.is_(None),
            CopyEvent.last_error_category.is_not(None),CopyWatch.archived_at.is_(None),
            User.is_active.is_(True),User.deleted_at.is_(None),User.automation_paused.is_(False)))).mappings().all()
    from app.services.mint_diagnostics import PREPARATION_REASONS
    copy_failures=set(PREPARATION_REASONS)|SERVICE_REASONS|MARKET_REASONS|OPERATOR_REASONS|{'temporary_checks_unavailable','temporary_preparation_error','validation_rejected',
        'mint_instructions_unavailable','signer_validation_rejected','preparation_unavailable'}
    for r in copy_errors:
        reason=r['last_error_category']
        if reason not in copy_failures:continue  # Paused, watch-only and budget waits are intentional controls.
        copy_unarmed[reason]+=1
        if len(recent_failures)<20:recent_failures.append({'event_id':r['id'],'username':r['username'],
            'collection':r['collection'],'outcome':'copy_not_armed','reason_code':reason,'reason_text':reason_text(reason),'chain_id':r['chain_id']})
        if reason in MARKET_REASONS or not r['last_checked_at'] or aware(r['last_checked_at'])<cutoff:continue
        group=groups[(r['chain_id'],reason)];group['copy_events'].add(r['id'])
        group['last_seen']=max(group['last_seen'],aware(r['last_checked_at']))
        if len(group['examples'])<5:group['examples'].append({'event_id':r['id'],'username':r['username'],'collection':r['collection']})
    incidents=[]
    for (chain,reason),g in groups.items():
        if len(g['tasks'])+len(g['opportunities'])+len(g['copy_events'])>=3 or reason in OPERATOR_REASONS:
            incidents.append({'chain_id':chain,'reason_code':reason,'affected_tasks':len(g['tasks']),
                'reason_text':reason_text(reason),
                'affected_opportunities':len(g['opportunities']),
                'affected_copy_events':len(g['copy_events']),
                'examples':g['examples'],
                'severity':'action_required' if reason in OPERATOR_REASONS else 'warning','last_seen':g['last_seen']})
    coverage=await db.scalar(select(func.min(MintOpportunity.eligible_at)))
    for mode,entry in by_mode.items():
        entry['activity_to_submission' if mode=='copy' else 'opening_to_submission']=latency(entry.pop('latency'))
    copy_seen=await db.scalar(select(func.count()).select_from(CopyEvent).where(CopyEvent.created_at>=since,CopyEvent.created_at<now))
    checks=(await db.execute(select(FeedWalletCheck.status,func.count()).join(User,FeedWalletCheck.user_id==User.id)
        .join(Wallet,FeedWalletCheck.wallet_id==Wallet.id).where(User.is_active.is_(True),User.deleted_at.is_(None),
        Wallet.archived_at.is_(None)).group_by(FeedWalletCheck.status))).all()
    waiting=Counter()
    approvals=(await db.execute(select(FeedMintApproval.expires_at,FeedMintApproval.note,AutomaticGrant.status,
        AutomaticGrant.expires_at.label('grant_expiry')).join(AutomaticGrant,FeedMintApproval.grant_id==AutomaticGrant.id)
        .join(User,FeedMintApproval.user_id==User.id).join(Wallet,FeedMintApproval.wallet_id==Wallet.id)
        .where(FeedMintApproval.status=='active',User.is_active.is_(True),User.deleted_at.is_(None),
            User.automation_paused.is_(False),Wallet.archived_at.is_(None)))).mappings().all()
    for a in approvals:
        note=a['note'] or ''
        if aware(a['expires_at'])<=now or a['status']!='enabled' or aware(a['grant_expiry'])<=now:waiting['signing_approval_unavailable']+=1
        elif 'Wallet eligibility is not verified yet.' in note:waiting['eligibility_not_verified']+=1
        elif 'Waiting for pending mint reservations to settle.' in note:waiting['budget_wait']+=1
        elif 'Not enough available native tokens for gas.' in note:waiting['insufficient_balance']+=1
        elif 'signing allowance is used up.' in note:waiting['budget_exhausted']+=1
    return {'since':since,'until':now,'timezone':'Africa/Lagos','outcomes':dict(outcomes),'modes':dict(by_mode),
        'eligible_auto_arm_collections':len(opportunities),'eligible_with_task':matched,
        'eligible_without_task':len(opportunities)-matched,'observation_started_at':coverage,
        'eligible_closed_without_task':sum(aware(o.closes_at)<=now for o in unmatched),
        'eligibility_checks':dict(checks),'auto_arm_waiting':dict(waiting),
        'unarmed_reasons':dict(blocked),
        'arming_failures_needing_review':sum(v for reason,v in blocked.items() if reason not in MARKET_REASONS and reason not in ('budget_wait','daily_budget_wait')),
        'copy_unarmed_reasons':dict(copy_unarmed),
        'copy_failures_needing_review':sum(v for reason,v in copy_unarmed.items() if reason not in MARKET_REASONS),
        'copy_events_observed':copy_seen,'failures_needing_review':needs_review,
        'recent_failures':recent_failures,
        'incidents':sorted(incidents,key=lambda g:(g['severity']!='action_required',-(g['affected_tasks']+g['affected_opportunities']+g['affected_copy_events']),str(g['chain_id']),g['reason_code'])),
        'notes':['Eligibility counts start with verified observations after this rollout; older opportunities are not reconstructed.',
            'One Auto-Arming collection per wallet is counted. Repeated polls and phases do not inflate the count.',
            'A failure needing review is not proof that a miss was preventable. Sold-out and wallet constraints are separate.',
            'Copy latency starts when Mintly records the followed activity. Missing or reversed timestamps are excluded.']}
