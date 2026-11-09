"""Real drop feed with truthful, account-scoped wallet status."""

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db
from app.models import Drop, DismissedDrop, SourceConnection, SourcePost, User, Wallet, FeedWalletCheck, FeedWalletSelection, MintPlan
from app.schemas.drop import DropListResponse, DropSchema
from app.services.feed_checks import supported, presentation, queue_checks, existing_mints
from app.services.feed_sources import approved, daily_collections, source_metadata, health, SOURCE_NAMES
from pydantic import BaseModel, Field

router = APIRouter(prefix="/drops", tags=["drops"])


@router.get("", response_model=DropListResponse)
async def list_drops(
    filter_kind: Optional[str] = "all", user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    wallet_id: Optional[str] = None, daily_only: bool = False, execution_states:bool=False,
):
    now = datetime.now(timezone.utc)
    wallets = (await db.scalars(select(Wallet).where(Wallet.user_id == user.id,
        Wallet.archived_at.is_(None), Wallet.is_demo.is_(False)).order_by(Wallet.is_default.desc(), Wallet.created_at))).all()
    selection = await db.get(FeedWalletSelection, user.id) if daily_only else None
    preferred = wallet_id or (selection.wallet_id if selection else None)
    wallet = next((w for w in wallets if w.id == preferred), None) if preferred else next(iter(wallets), None)
    if wallet_id and wallet is None:
        raise HTTPException(404, 'Wallet not found.')
    if wallet is None and not wallet_id:
        wallet = next(iter(wallets), None)
    if daily_only and wallet and (not selection or selection.wallet_id != wallet.id):
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        insert = pg_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
        await db.execute(insert(FeedWalletSelection).values(user_id=user.id,wallet_id=wallet.id,
            created_at=now,updated_at=now).on_conflict_do_update(index_elements=['user_id'],
            set_={'wallet_id':wallet.id,'updated_at':now}))
    source_filter = approved()
    stmt = select(Drop).join(SourcePost, Drop.source_post_id == SourcePost.id).options(selectinload(Drop.stages)).where(
        Drop.is_demo.is_(False),
        source_filter,
        ~select(DismissedDrop.drop_id).where(DismissedDrop.user_id == user.id,
            DismissedDrop.drop_id == Drop.id).exists(),
    ).order_by(Drop.updated_at.desc()).limit(100)
    if daily_only:
        day = now.astimezone(ZoneInfo('Africa/Lagos')).date()
    groups = await daily_collections(db,day,user.id) if daily_only else []
    drops = [g['drop'] for g in groups] if daily_only else (await db.execute(stmt)).scalars().all()
    if not daily_only and filter_kind and filter_kind != "all":
        drops = [drop for drop in drops if drop.status_kind == filter_kind]
    sources = await health(db)
    source_text = ' · '.join('@'+s['name']+(' monitoring paused' if not s['is_monitoring'] else
        ' refresh delayed' if s['delayed'] or s['status']!='healthy' else
        ' list available' if s['today_posted'] else " awaiting today's list") for s in sources)
    if any(s['processing_pending'] for s in sources):source_text+=' · Some saved entries are waiting for link verification.'
    admin_source_text = source_text
    if user.role == 'admin':
        admin_source_text += ' · Operator X session details are available in Mint sources.'
    metadata,editions=await source_metadata(db,groups,user.id,day) if daily_only else ({},[])
    cards = []
    checks = {c.drop_id:c for c in (await db.scalars(select(FeedWalletCheck).where(
        FeedWalletCheck.user_id==user.id,FeedWalletCheck.wallet_id==wallet.id,
        FeedWalletCheck.drop_id.in_([d.id for d in drops])))).all()} if daily_only and wallet else {}
    existing = await existing_mints(db, user, wallet, drops,include_terminal=execution_states) if daily_only else {}
    for drop in drops:
        card = DropSchema.model_validate(drop)
        if daily_only:
            card.sources=metadata[drop.id]['sources'];card.additions=metadata[drop.id]['additions']
            card.list_context=metadata[drop.id]['list_context'];card.today_schedule=metadata[drop.id]['today_schedule']
            if card.today_schedule:card.source_time_text=card.today_schedule
            check = checks.get(drop.id)
            card.wallet_check = presentation(check, now) if wallet else dict(status='unverified',
                setup_enabled=False, stages=[], note='Link a wallet to check eligibility.')
            if check and check.result.get('collection_slug'):
                from app.services.opensea import collection_slug
                if check.result['collection_slug'] != collection_slug(drop.mint_page_url) or (drop.contract_address and
                        check.result.get('contract_address', '').lower() != drop.contract_address.lower()):
                    card.wallet_check = dict(status='unverified', setup_enabled=False, stages=[], note='Collection terms changed. Check again.')
            if drop.id in existing:
                card.automatic_mint = existing[drop.id]
                minted = existing[drop.id]['status'] in ('confirmed','already_minted')
                lifecycle=existing[drop.id]['lifecycle']
                card.wallet_check = dict(status=existing[drop.id]['status'], setup_enabled=False,
                    stages=[], note='This wallet already minted this collection. View its mint history.' if minted
                    else (lifecycle['detail'] or lifecycle['label']) if lifecycle['terminal']
                    else 'An automatic mint is already active for this wallet. View it in Mint plans.')
            elif not supported(drop):
                card.wallet_check=dict(status='unsupported',setup_enabled=False,stages=[],
                    note='Source information only. Automatic minting is not available for this collection.')
        cards.append(card)
    if daily_only and filter_kind and filter_kind != 'all':
        wanted={'unknown':'unverified','manual':'not_eligible'}.get(filter_kind,filter_kind)
        cards=[c for c in cards if c.wallet_check['status']==wanted]
    return DropListResponse(
        date_label=datetime.now(timezone.utc).astimezone(ZoneInfo("Africa/Lagos")).strftime("%A, %d %B").upper(),
        source_status_text=admin_source_text if user.role == 'admin' else '',
        drops=cards,
        checked_wallet_label=wallet.address if wallet else "No wallet connected",
        last_checked_text="Wallet-specific eligibility is unverified",
        selected_wallet_id=wallet.id if wallet else None,
        wallets=[dict(id=w.id, label=w.label, address=w.address) for w in wallets],
        feed_status_text=source_text,
        editions=editions,
    )


class CheckCards(BaseModel):
    wallet_id: str
    drop_ids: list[str] = Field(min_length=1, max_length=20)


@router.post('/wallet-checks', status_code=202)
async def check_cards(body: CheckCards, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.config import settings
    if not settings.FEED_WALLET_CHECKS_ENABLED:
        raise HTTPException(503, 'Wallet checks are temporarily paused.')
    wallet = await db.scalar(select(Wallet).where(Wallet.id == body.wallet_id, Wallet.user_id == user.id,
        Wallet.archived_at.is_(None), Wallet.is_demo.is_(False)))
    if not wallet:
        raise HTTPException(404, 'Wallet not found.')
    day = datetime.now(timezone.utc).astimezone(ZoneInfo('Africa/Lagos')).date()
    groups=await daily_collections(db,day,user.id)
    drops=[g['drop'] for g in groups if g['ids']&set(body.drop_ids)]
    await queue_checks(db, user, wallet, drops)
    return {'queued': len([d for d in drops if supported(d)])}


class SeenEditions(BaseModel):
    editions: list[dict[str,str]] = Field(max_length=100)


@router.post('/seen')
async def seen_editions(body: SeenEditions,user=Depends(get_current_user),db=Depends(get_db)):
    from app.models import FeedSeen
    from app.services.x_feed import insert_for
    now=datetime.now(timezone.utc)
    for edition in body.editions:
        post=await db.scalar(select(SourcePost).where(SourcePost.id==edition.get('id'),approved()))
        # Acknowledging an older screen cannot clear a newly arrived revision.
        if not post or not post.content_hash or post.content_hash!=edition.get('content_hash'):continue
        await db.execute(insert_for(db)(FeedSeen).values(user_id=user.id,post_id=post.id,content_hash=post.content_hash,
            created_at=now,updated_at=now).on_conflict_do_update(index_elements=['user_id','post_id'],
                set_={'content_hash':post.content_hash,'updated_at':now}))
    await db.commit();return {'seen':True}


class SetupCard(BaseModel):
    wallet_id: str
    stage_uuid: str = Field(max_length=200)


@router.post('/{drop_id}/prepare-plan')
async def prepare_card(drop_id: str, body: SetupCard, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    drop = await get_drop_detail(drop_id, db)
    wallet = await db.scalar(select(Wallet).where(Wallet.id == body.wallet_id, Wallet.user_id == user.id,
        Wallet.archived_at.is_(None), Wallet.is_demo.is_(False)))
    if not wallet or not supported(drop):
        raise HTTPException(409, 'The selected wallet or collection is unavailable.')
    from app.services.opensea import collection_slug
    slug = collection_slug(drop.mint_page_url)
    from app.api.mint_plans import response, import_open_sea_plan, ImportMintPlanRequest
    existing = await db.scalar(select(MintPlan).where(MintPlan.user_id == user.id,
        MintPlan.wallet_id == wallet.id, MintPlan.collection_slug == slug, MintPlan.archived_at.is_(None)))
    # Opening an existing plan must never change its selected stage or approvals.
    if existing:
        return response(existing, wallet)
    check = await db.get(FeedWalletCheck, (user.id, wallet.id, drop.id))
    card = presentation(check)
    selected = next((s for s in card.get('stages', []) if s['id'] == body.stage_uuid), None)
    if not (card['setup_enabled'] or card.get('review_enabled')) or not selected or selected['eligibility'] != 'eligible' or selected['timing'] == 'ended':
        raise HTTPException(409, 'Check this wallet’s qualifying stage again before setup.')
    if not card['setup_enabled']:
        from app.services.mint_stage_choice import wallet_stages
        live_result,_=await wallet_stages(db,wallet,slug,drop.chain_id,drop.contract_address,read_only=True)
        verified=next((s for s in live_result.get('stages',[]) if s['id']==body.stage_uuid),None)
        if not verified or verified['eligibility']!='eligible' or verified['timing']=='ended' or verified.get('remaining')==0 or verified.get('price_wei') is None:
            raise HTTPException(409,'This wallet’s stage changed. Refresh eligibility before setup.')
    saved = await import_open_sea_plan(ImportMintPlanRequest(url=drop.mint_page_url, wallet_id=wallet.id), user, db)
    plan = await db.get(MintPlan, saved['id'])
    from app.services.mint_stage_choice import stages, select_stage
    result, _ = await stages(db, plan, user.id)
    live = next((s for s in result['stages'] if s['id'] == body.stage_uuid), None)
    if not live or live['eligibility'] != 'eligible' or live['timing'] == 'ended' or live.get('remaining') == 0 or live.get('price_wei') is None:
        raise HTTPException(409, 'This wallet’s stage or mint terms changed. Review the saved plan.')
    from types import SimpleNamespace
    plan, wallet = await select_stage(db, plan, SimpleNamespace(stage_uuid=body.stage_uuid, quantity=1), user.id)
    return response(plan, wallet)


@router.get("/{drop_id}", response_model=DropSchema)
async def get_drop_detail(drop_id: str, db: AsyncSession = Depends(get_db)):
    drop = (await db.execute(select(Drop).join(SourcePost, Drop.source_post_id == SourcePost.id)
        .options(selectinload(Drop.stages)).where(
        Drop.id == drop_id, Drop.is_demo.is_(False),
        approved(),
    ))).scalar_one_or_none()
    if drop is None:
        raise HTTPException(status_code=404, detail="Drop not found.")
    return drop


@router.delete('/{drop_id}')
async def remove_drop(drop_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_drop_detail(drop_id, db)
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert = pg_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
    now = datetime.now(timezone.utc)
    await db.execute(insert(DismissedDrop).values(user_id=user.id, drop_id=drop_id,
        created_at=now, updated_at=now).on_conflict_do_nothing(index_elements=['user_id', 'drop_id']))
    await db.commit()
    return {'removed': True, 'plans_and_history_retained': True}


@router.post("/{drop_id}/recheck")
async def recheck_drop_eligibility(
    drop_id: str, wallet_id: Optional[str] = None,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if wallet_id:
        wallet = (await db.execute(select(Wallet).where(
            Wallet.id == wallet_id, Wallet.user_id == user.id, Wallet.archived_at.is_(None),
        ))).scalar_one_or_none()
        if wallet is None:
            raise HTTPException(status_code=404, detail="Wallet not found.")
    raise HTTPException(status_code=409, detail=(
        "Wallet-specific eligibility cannot be verified by this source. "
        "Check the official mint page with MetaMask before signing anything."
    ))
