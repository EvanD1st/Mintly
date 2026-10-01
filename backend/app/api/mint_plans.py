"""Personal OpenSea mint plans. Importing never authorizes a transaction."""

from decimal import Decimal
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import MintPlan, User, Wallet
from app.services.mint_plans import aware, refresh_mint_plan
from app.services.opensea import CHAINS, OpenSeaClient, OpenSeaUnavailable, collection_slug

router = APIRouter(prefix="/mint-plans", tags=["mint-plans"])


class ImportMintPlanRequest(BaseModel):
    url: str = Field(min_length=20, max_length=300)
    wallet_id: str | None = None


def eth_amount(value: int | None) -> str | None:
    if value is None:
        return None
    amount = format(Decimal(value) / Decimal(10**18), "f")
    return amount.rstrip("0").rstrip(".") if "." in amount else amount


def response(plan: MintPlan, wallet: Wallet) -> dict:
    return {
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
        if chain_label not in (wallet.supported_chains or []):
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
        await refresh_mint_plan(plan, wallet, client, detail=detail)
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
        MintPlan.user_id == user.id, Wallet.user_id == user.id,
    ).order_by(MintPlan.created_at.desc()))).all()
    return [response(plan, wallet) for plan, wallet in plans]


@router.post("/{plan_id}/refresh")
async def refresh_open_sea_plan(plan_id: str, user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    plan = (await db.execute(select(MintPlan).where(
        MintPlan.id == plan_id, MintPlan.user_id == user.id,
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
        await refresh_mint_plan(plan, wallet)
        await db.commit()
        return response(plan, wallet)
    except OpenSeaUnavailable as error:
        await db.rollback()
        raise api_error(error) from error


@router.delete("/{plan_id}")
async def remove_mint_plan(plan_id: str, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    plan = (await db.execute(select(MintPlan).where(
        MintPlan.id == plan_id, MintPlan.user_id == user.id,
    ))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Mint plan not found.")
    await db.delete(plan)
    await db.commit()
    return {"status": "removed"}
