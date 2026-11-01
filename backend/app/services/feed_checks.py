"""Background display eligibility; no signatures, approvals or personal plans."""
import asyncio
from datetime import datetime,timezone,timedelta
from sqlalchemy import select,or_,case
from app.config import settings
from app.models import FeedWalletCheck,Wallet,Drop,User
from app.services.opensea import OpenSeaClient,collection_slug,CHAINS,OpenSeaUnavailable
from app.services.mint_plans import aware
from app.services.networks import advertised

async def existing_mints(db, user, wallet, drops):
    """Match confirmed or live tasks using the selected owner's collection identity."""
    if not wallet or not drops:
        return {}
    from app.models import MintTask, MintAuthorization, MintStage
    from app.services.automatic import TERMINAL
    rows = (await db.execute(select(
        MintTask.id, MintTask.plan_id, MintTask.status, MintTask.scheduled_for_utc, MintTask.confirmed_at,
        MintAuthorization.quantity, MintAuthorization.snapshot,
        Drop.chain_id, Drop.contract_address, Drop.mint_page_url, MintStage.stage_name,
    ).join(MintAuthorization, MintTask.authorization_id == MintAuthorization.id)
        .join(Drop, MintTask.drop_id == Drop.id)
        .join(MintStage, MintTask.stage_id == MintStage.id)
        .join(Wallet, MintTask.wallet_id == Wallet.id)
        .where(Wallet.user_id == user.id, Wallet.id == wallet.id,
            MintTask.is_demo.is_(False), or_(MintTask.status == 'confirmed', MintTask.status.not_in(TERMINAL)))
        # A successful mint remains visible even after archiving or a later failed attempt.
        .order_by(case((MintTask.status == 'confirmed', 0), else_=1),
            MintTask.confirmed_at.desc(), MintTask.scheduled_for_utc, MintTask.id))).mappings().all()
    result = {}
    for drop in drops:
        for row in rows:
            scope = row['snapshot'] or {}
            if scope.get('chain_id', row['chain_id']) != drop.chain_id:
                continue
            contract = scope.get('contract') or row['contract_address'] or ''
            if drop.contract_address:
                matches = contract.lower() == drop.contract_address.lower()
            else:
                try:
                    matches = collection_slug(scope.get('mint_page_url') or row['mint_page_url']) == collection_slug(drop.mint_page_url)
                except OpenSeaUnavailable:
                    matches = False
            if matches:
                result[drop.id] = dict(id=row['id'], plan_id=row['plan_id'], wallet_id=wallet.id,
                    status=row['status'], quantity=row['quantity'],
                    stage_name=scope.get('stage_name') or row['stage_name'],
                    scheduled_for_utc=aware(row['scheduled_for_utc']),
                    confirmed_at=aware(row['confirmed_at']) if row['confirmed_at'] else None)
                break
    return result


def supported(drop):
    if drop.chain_id not in {n['chain_id'] for n in advertised(native_currencies=True)}:return False
    try:collection_slug(drop.mint_page_url);return drop.status_kind!='unsupported'
    except OpenSeaUnavailable:return False

def presentation(check,now=None):
    now=now or datetime.now(timezone.utc)
    if not check:return dict(status='unverified',setup_enabled=False,stages=[],note='Checking wallet eligibility.')
    result=dict(check.result or {})
    stages=[dict(s) for s in result.get('stages',[])]
    for stage in stages:
        begin=datetime.fromisoformat(stage['starts_at']);end=datetime.fromisoformat(stage['ends_at'])
        stage['timing']='ended' if end<=now else 'upcoming' if begin>now else 'open'
    result['stages']=stages;result['checked_at']=check.checked_at
    fresh=bool(check.expires_at and aware(check.expires_at)>now and check.status in ('complete','queued','checking'))
    available=[s for s in stages if s['timing']!='ended']
    eligible=[s for s in available if s.get('remaining')!=0 and s.get('wallet_total_limit')!=0
        and s['eligibility']=='eligible' and s.get('price_wei') is not None
        and 0<=int(s['price_wei'])<2**63]
    eligible.sort(key=lambda s:(s['timing']!='open',s['starts_at'],s['id']))
    result['recommended_stage']=eligible[0] if fresh and eligible else None
    result['setup_enabled']=bool(fresh and eligible)
    # Historical summaries are display-only. Never authorize setup from stale data.
    result['last_status']='eligible' if eligible else ('not_eligible' if available
        and all(s['eligibility']=='not_eligible' or s.get('remaining')==0 or s.get('wallet_total_limit')==0 for s in available) else 'unverified')
    result['last_recommended_stage']=eligible[0] if eligible else None
    result['refreshing']=check.status in ('queued','checking')
    result['status']='eligible' if result['setup_enabled'] else ('not_eligible' if fresh and available
        and all(s['eligibility']=='not_eligible' or s.get('remaining')==0 or s.get('wallet_total_limit')==0 for s in available) else 'unverified')
    if not fresh:result['note']='Checking wallet eligibility.' if check.status in ('queued','checking') else 'Eligibility could not be verified. Retry the check.'
    return result

async def queue_checks(db,user,wallet,drops):
    now=datetime.now(timezone.utc)
    existing = await existing_mints(db, user, wallet, drops)
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert=pg_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
    for drop in drops:
        if drop.canonical_id:
            drop=await db.get(Drop,drop.canonical_id)
        if not supported(drop) or drop.id in existing:continue
        await db.execute(insert(FeedWalletCheck).values(user_id=user.id,wallet_id=wallet.id,drop_id=drop.id,
            status='queued',result={},attempts=0,next_attempt_at=now,created_at=now,updated_at=now)
            .on_conflict_do_nothing(index_elements=['user_id','wallet_id','drop_id']))
        row=await db.get(FeedWalletCheck,(user.id,wallet.id,drop.id))
        if row.status in ('queued','checking') and (not row.lease_until or aware(row.lease_until)>now):continue
        if row.expires_at and aware(row.expires_at)>now:continue
        if row.next_attempt_at and aware(row.next_attempt_at)>now:continue
        row.status='queued';row.next_attempt_at=now;row.attempts=0
    await db.commit()

async def step(factory):
    if not settings.FEED_WALLET_CHECKS_ENABLED:return False
    now=datetime.now(timezone.utc)
    async with factory() as db:
        row=await db.scalar(select(FeedWalletCheck).where(
            FeedWalletCheck.status.in_(['queued','checking']),
            or_(FeedWalletCheck.next_attempt_at.is_(None),FeedWalletCheck.next_attempt_at<=now),
            or_(FeedWalletCheck.lease_until.is_(None),FeedWalletCheck.lease_until<=now))
            .order_by(FeedWalletCheck.next_attempt_at,FeedWalletCheck.created_at).with_for_update(skip_locked=True).limit(1))
        if not row:return False
        row.status='checking';row.lease_until=now+timedelta(seconds=90);row.attempts+=1
        lease=row.lease_until
        key=(row.user_id,row.wallet_id,row.drop_id)
        wallet=await db.get(Wallet,row.wallet_id);drop=await db.get(Drop,row.drop_id);user=await db.get(User,row.user_id)
        if drop and drop.canonical_id:
            row.status='unverified';row.lease_until=None
            await db.commit();return True
        if user and wallet and drop and await existing_mints(db, user, wallet, [drop]):
            # Old queued display checks must not poll active or already minted collections.
            row.status='unverified';row.lease_until=None
            await db.commit()
            return True
        await db.commit()  # No row or execution lock across provider IO.
        result={};error=None
        try:
            if not user or not user.is_active or user.deleted_at or not wallet or wallet.archived_at or wallet.user_id!=user.id or not drop or not supported(drop):
                raise ValueError('The wallet or listing is no longer available.')
            async with asyncio.timeout(75):
                slug=collection_slug(drop.mint_page_url);detail=await OpenSeaClient().get_drop(slug)
                chain=CHAINS[detail['chain']][0]
                if chain!=drop.chain_id:raise ValueError('Source network does not match the verified collection.')
                if drop.contract_address and drop.contract_address.lower()!=detail['contract_address'].lower():raise ValueError('Collection contract changed.')
                from app.services.mint_stage_choice import wallet_stages
                result,_=await asyncio.wait_for(wallet_stages(db,wallet,slug,chain,detail['contract_address'],read_only=True,detail=detail),60)
                result.update(collection_slug=slug,contract_address=detail['contract_address'])
                drop.contract_address=detail['contract_address'];drop.is_supported_integration=True
        except OpenSeaUnavailable as e:error=e
        except Exception:error=OpenSeaUnavailable('Eligibility could not be verified.',retry_after_seconds=60)
        await db.rollback()
        row=await db.get(FeedWalletCheck,key,populate_existing=True)
        if not row:return True
        if not row.lease_until or aware(row.lease_until)!=aware(lease):return True
        # Recheck owner state after IO, rather than publishing revoked wallet data.
        wallet=await db.get(Wallet,key[1],populate_existing=True);user=await db.get(User,key[0],populate_existing=True)
        if not wallet or wallet.archived_at or wallet.user_id!=key[0] or not user or not user.is_active or user.deleted_at:
            error=OpenSeaUnavailable('The wallet is no longer available.')
        row.lease_until=None;finished=datetime.now(timezone.utc)
        if error:
            # Keep the last successful check time/result for an explicitly labelled
            # history summary, but invalidate freshness on failure. Retry backoff is
            # independent of cache expiry, so visible polling cannot defeat it.
            row.result={**(row.result or {}),'note':'Eligibility could not be verified. Retry the check.'}
            if not row.checked_at:row.checked_at=finished
            row.status='queued' if row.attempts<3 else 'unverified'
            row.next_attempt_at=finished+timedelta(seconds=max(60,error.retry_after_seconds or 0))
            row.expires_at=finished
            if error.status in (400,404):
                row.status='unverified'
                drop=await db.get(Drop,key[2]);drop.status_kind='unsupported'
        else:
            row.checked_at=finished
            row.status='complete';row.result=result;row.expires_at=row.checked_at+timedelta(seconds=60)
            drop=await db.get(Drop,key[2]);drop.contract_address=result['contract_address'];drop.is_supported_integration=True
        await db.commit()
    return True
