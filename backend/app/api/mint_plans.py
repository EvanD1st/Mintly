"""Personal OpenSea mint plans. Importing never authorizes a transaction."""

from decimal import Decimal
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import MintPlan, MintPlanRecord, MintPermission, MintTask, Drop, MintStage, User, Wallet
from fastapi.encoders import jsonable_encoder
from app.schemas.drop import DropSchema
from app.services import automatic
from app.services.opensea import stage_schedule
from app.services.mint_plans import aware, refresh_mint_plan
from app.services.opensea import CHAINS, OpenSeaClient, OpenSeaUnavailable, collection_slug

router = APIRouter(prefix="/mint-plans", tags=["mint-plans"])


class ImportMintPlanRequest(BaseModel):
    url: str = Field(min_length=20, max_length=300)
    wallet_id: str | None = None
    quantity: int = Field(default=1, ge=1, le=100, strict=True)


def eth_amount(value: int | None) -> str | None:
    if value is None:
        return None
    amount = format(Decimal(value) / Decimal(10**18), "f")
    return amount.rstrip("0").rstrip(".") if "." in amount else amount


def response(plan: MintPlan, wallet: Wallet) -> dict:
    mint_value = plan.mint_value_wei
    if mint_value is None and plan.price_wei is not None:
        mint_value = plan.price_wei * plan.quantity
    total = mint_value + plan.estimated_network_fee_wei if mint_value is not None and plan.estimated_network_fee_wei is not None else None
    rate_fresh = plan.rate_checked_at and aware(plan.rate_checked_at) > datetime.now(timezone.utc) - timedelta(minutes=5)
    total_usdt = format(Decimal(eth_amount(total)) * Decimal(plan.eth_usdt_rate), '.4f') if total is not None and plan.eth_usdt_rate and rate_fresh else None
    return {
        "created_at": plan.created_at, "archived_at": plan.archived_at,
        "quantity": plan.quantity, "estimated_total_eth": eth_amount(total),
        "estimated_total_usdt": total_usdt, "eth_usdt_rate": plan.eth_usdt_rate if rate_fresh else None,
        "rate_checked_at": plan.rate_checked_at, "rate_source": "Coinbase ETH-USDT",
        "id": plan.id, "wallet_id": plan.wallet_id,
        "wallet_address": wallet.address,
        "collection_name": plan.collection_name,
        "opensea_url": plan.opensea_url, "chain": plan.chain,
        "contract_address": plan.contract_address,
        "stage_name": plan.stage_name, "stage_type": plan.stage_type,
        "starts_at": plan.starts_at, "ends_at": plan.ends_at,
        "price_eth": eth_amount(plan.price_wei),
        "mint_value_eth": eth_amount(plan.mint_value_wei),
        "estimated_network_fee_eth": eth_amount(plan.estimated_network_fee_wei),
        "status": plan.status, "status_note": plan.status_note,
        "last_checked_at": plan.last_checked_at,
    }


def api_error(error: OpenSeaUnavailable) -> HTTPException:
    return HTTPException(status_code=error.status, detail=str(error))


@router.post("")
async def import_open_sea_plan(req: ImportMintPlanRequest,
                               user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    try:
        slug = collection_slug(req.url)
    except OpenSeaUnavailable as error:
        raise api_error(error) from error
    await automatic.lock_execution(db)
    wallet_stmt = select(Wallet).where(Wallet.user_id == user.id, Wallet.is_demo.is_(False))
    if req.wallet_id:
        wallet_stmt = wallet_stmt.where(Wallet.id == req.wallet_id)
    else:
        wallet_stmt = wallet_stmt.order_by(Wallet.is_default.desc(), Wallet.id.asc())
    wallet = (await db.execute(wallet_stmt.limit(1))).scalar_one_or_none()
    if wallet is None:
        raise HTTPException(status_code=409, detail="Link your MetaMask wallet before importing a mint.")
    client = OpenSeaClient()
    try:
        detail = await client.get_drop(slug)
        chain_id, chain_label = CHAINS[detail["chain"]]
        # A verified MetaMask EVM address is usable across these networks.
        # Old pairings list only Ethereum/Base; that list is not network permission.
        if wallet.signing_capability != "interactive" and chain_label not in (wallet.supported_chains or []):
            raise OpenSeaUnavailable("This wallet is not linked for the drop's chain.", 400)
        plan = (await db.execute(select(MintPlan).where(
            MintPlan.wallet_id == wallet.id, MintPlan.collection_slug == slug,
        ))).scalar_one_or_none()
        if plan is None:
            plan = MintPlan(user_id=user.id, wallet_id=wallet.id, collection_slug=slug,
                            collection_name=str(detail.get("collection_name") or slug)[:150],
                            chain=chain_label, chain_id=chain_id,
                            contract_address=detail["contract_address"],
                            opensea_url=detail["opensea_url"],
                            status="unverified", status_note="Checking OpenSea drop")
            db.add(plan)
        if plan.id and plan.quantity != req.quantity:
            pending=(await db.execute(select(MintPermission.id).where(MintPermission.plan_id==plan.id,MintPermission.status.in_(['awaiting_signature','armed','prepared','submitted'])))).first()
            if pending: raise OpenSeaUnavailable('Cancel the pending mint permission before changing quantity.',409)
        plan.archived_at = None
        plan.quantity = req.quantity
        plan.notified_stage_uuid = None
        await refresh_mint_plan(plan, wallet, client, detail=detail)
        await db.flush()
        record_plan(db, plan, wallet, "saved")
        await db.commit()
        await db.refresh(plan)
        return response(plan, wallet)
    except OpenSeaUnavailable as error:
        await db.rollback()
        raise api_error(error) from error


@router.get("")
async def list_mint_plans(user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    plans = (await db.execute(select(MintPlan, Wallet).join(Wallet, Wallet.id == MintPlan.wallet_id).where(
        MintPlan.user_id == user.id, Wallet.user_id == user.id, MintPlan.archived_at.is_(None),
    ).order_by(MintPlan.created_at.desc()))).all()
    return [response(plan, wallet) for plan, wallet in plans]


@router.post("/{plan_id}/refresh")
async def refresh_open_sea_plan(plan_id: str, user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    await automatic.lock_execution(db)
    plan = (await db.execute(select(MintPlan).where(
        MintPlan.id == plan_id, MintPlan.user_id == user.id, MintPlan.archived_at.is_(None),
    ))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Mint plan not found.")
    wallet = (await db.execute(select(Wallet).where(
        Wallet.id == plan.wallet_id, Wallet.user_id == user.id,
    ))).scalar_one_or_none()
    if wallet is None:
        raise HTTPException(status_code=409, detail="The linked wallet is unavailable.")
    if plan.last_checked_at and aware(plan.last_checked_at) > datetime.now(timezone.utc) - timedelta(seconds=15):
        return response(plan, wallet)
    try:
        before = jsonable_encoder(response(plan, wallet))
        await refresh_mint_plan(plan, wallet)
        after = jsonable_encoder(response(plan, wallet))
        keys = ("stage_name", "starts_at", "ends_at", "price_eth", "status", "quantity")
        if any(before[k] != after[k] for k in keys):
            record_plan(db, plan, wallet, "updated")
        await db.commit()
        return response(plan, wallet)
    except OpenSeaUnavailable as error:
        await db.rollback()
        raise api_error(error) from error


def record_plan(db, plan, wallet, event):
    db.add(MintPlanRecord(user_id=plan.user_id, plan_id=plan.id, event=event,
                         snapshot=jsonable_encoder(response(plan, wallet))))


@router.post("/{plan_id}/automatic-context")
async def automatic_context(plan_id: str, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """Materialize the exact selected OpenSea stage; this never arms or signs."""
    automatic.enabled()
    await automatic.lock_execution(db)
    plan = (await db.execute(select(MintPlan).where(
        MintPlan.id == plan_id, MintPlan.user_id == user.id, MintPlan.archived_at.is_(None),
    ))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(404, 'Mint plan not found.')
    wallet = await db.get(Wallet, plan.wallet_id)
    client = OpenSeaClient()
    try:
        detail = await client.get_drop(plan.collection_slug)
        before = jsonable_encoder(response(plan, wallet))
        transaction = {}
        await refresh_mint_plan(plan, wallet, client, detail=detail, transaction_out=transaction)
        selected = next((s for s in stage_schedule(detail) if s['uuid'] == plan.stage_uuid), None)
        kinds = {'public_sale': 'public', 'allowlist': 'allowlist', 'signed': 'signed',
                 'allowlist_sale': 'allowlist', 'signed_sale': 'signed'}
        if not selected or selected['price_wei'] is None or selected['max_per_wallet'] < plan.quantity:
            raise HTTPException(409, 'No mint stage with sufficient quantity is available.')
        # OpenSea stage types vary; unknown methods require explicit review rather than guessing.
        kind = kinds.get(selected['type'])
        if transaction:
            from app.services.seadrop_mint import decode_mint
            kind = decode_mint(transaction, plan.contract_address, wallet.address, plan.quantity)['kind']
        if kind is None:
            raise HTTPException(409, 'This stage type is not supported for automatic minting.')
        automatic.enabled(plan.chain_id)
        drop_id = automatic.digest(['plan', plan.id, plan.chain_id, plan.contract_address.lower(),
                                    plan.collection_name, jsonable_encoder(selected)])
        stage_id = automatic.digest(['stage', drop_id])
        drop = await db.get(Drop, drop_id)
        if drop is None:
            drop = Drop(id=drop_id, name=plan.collection_name, chain=plan.chain, chain_id=plan.chain_id,
                contract_address=plan.contract_address, mint_page_url=plan.opensea_url,
                site_label='OpenSea', icon_name='gem', status_label='Review automatic mint',
                status_kind='unknown', is_supported_integration=True, is_demo=False)
            drop.stages = [MintStage(id=stage_id, drop_id=drop_id, stage_name=selected['name'][:50],
                start_time_utc=selected['starts_at'], end_time_utc=selected['ends_at'],
                price_wei=selected['price_wei'], price_eth_str=eth_amount(selected['price_wei']),
                limit_per_wallet=selected['max_per_wallet'], eligibility_status='unknown')]
            db.add(drop)
        plan.automatic_drop_id, plan.automatic_stage_id = drop_id, stage_id
        if any(before[k] != jsonable_encoder(response(plan, wallet))[k]
               for k in ('stage_name', 'starts_at', 'ends_at', 'price_eth', 'status')):
            record_plan(db, plan, wallet, 'updated')
        await db.commit()
        return {'drop': DropSchema.model_validate(drop), 'plan': response(plan, wallet), 'mint_kind': kind}
    except OpenSeaUnavailable as error:
        await db.rollback()
        raise api_error(error) from error


@router.delete("/{plan_id}")
async def remove_mint_plan(plan_id: str, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    # Same cross-process lock as the signer: cancellation wins before signing or observes in-flight bytes.
    await automatic.lock_execution(db)
    plan = (await db.execute(select(MintPlan).where(
        MintPlan.id == plan_id, MintPlan.user_id == user.id,
    ))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(404, 'Mint plan not found.')
    if plan.archived_at:
        pending = await db.scalar(select(MintTask.id).where(MintTask.plan_id == plan.id,
            MintTask.status.not_in(automatic.TERMINAL)).limit(1))
        return {'status': 'removed', 'in_flight': pending is not None, 'history_retained': True}
    now = datetime.now(timezone.utc)
    tasks = (await db.execute(select(MintTask).where(MintTask.plan_id == plan.id))).scalars().all()
    from app.api.tasks import archive_task
    in_flight = False
    for task in tasks:
        in_flight = await archive_task(db, task, user.id, now) or in_flight
    permissions = (await db.execute(select(MintPermission).where(MintPermission.plan_id == plan.id).with_for_update())).scalars().all()
    for permission in permissions:
        if permission.status in ('awaiting_signature', 'armed'):
            permission.status = 'cancelled'
            permission.note = 'Plan removed; permission canceled before execution.'
    plan.archived_at, plan.next_check_at = now, None
    record_plan(db, plan, await db.get(Wallet, plan.wallet_id), 'removed')
    await db.commit()
    return {'status': 'removed', 'in_flight': in_flight, 'history_retained': True}
