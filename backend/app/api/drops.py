"""Drop listing and detail endpoints."""

from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import Drop, MintStage, Wallet, ActivityEvent
from app.schemas.drop import DropSchema, DropListResponse, EligibilityRecheckResponse
from app.services.opensea_client import OpenSeaAdapter

router = APIRouter(prefix="/drops", tags=["drops"])


@router.get("", response_model=DropListResponse)
async def list_drops(
    filter_kind: Optional[str] = "all",  # 'all', 'eligible', 'manual'
    db: AsyncSession = Depends(get_db)
):
    """Returns today's drops with status and wallet eligibility."""
    stmt = select(Drop).options(selectinload(Drop.stages)).order_by(Drop.created_at)
    res = await db.execute(stmt)
    drops = res.scalars().all()

    if filter_kind and filter_kind != "all":
        filtered = [d for d in drops if d.status_kind == filter_kind]
    else:
        filtered = list(drops)

    # Format WAT date
    now_utc = datetime.now(timezone.utc)
    from zoneinfo import ZoneInfo
    now_lagos = now_utc.astimezone(ZoneInfo("Africa/Lagos"))
    date_str = now_lagos.strftime("%A, %d %B").upper()

    return DropListResponse(
        date_label=date_str,
        source_status_text="Last synced 17:02 · 3 drops",
        drops=filtered,
        checked_wallet_label="Jenny · Demo address",
        last_checked_text="Eligibility checked at 17:03",
    )


@router.get("/{drop_id}", response_model=DropSchema)
async def get_drop_detail(drop_id: str, db: AsyncSession = Depends(get_db)):
    """Returns detailed information and stages for a specific drop."""
    stmt = select(Drop).options(selectinload(Drop.stages)).where(Drop.id == drop_id)
    res = await db.execute(stmt)
    drop = res.scalar_one_or_none()
    if not drop:
        raise HTTPException(status_code=404, detail="Drop not found.")
    return drop


@router.post("/{drop_id}/recheck", response_model=EligibilityRecheckResponse)
async def recheck_drop_eligibility(
    drop_id: str,
    wallet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Rechecks eligibility for a drop and updates timestamp."""
    stmt = select(Drop).options(selectinload(Drop.stages)).where(Drop.id == drop_id)
    res = await db.execute(stmt)
    drop = res.scalar_one_or_none()
    if not drop:
        raise HTTPException(status_code=404, detail="Drop not found.")

    wallet = (await db.execute(select(Wallet).where(Wallet.id == wallet_id))).scalar_one_or_none() if wallet_id else None
    if wallet_id and wallet is None:
        raise HTTPException(status_code=404, detail="Wallet not found.")
    if not drop.is_demo and wallet is None:
        raise HTTPException(status_code=400, detail="Select a wallet before checking eligibility.")

    adapter = OpenSeaAdapter()
    now = datetime.now(timezone.utc)

    for stage in drop.stages:
        if drop.is_supported_integration:
            chk = await adapter.check_wallet_eligibility(
                chain=drop.chain,
                collection_slug=drop.id,
                stage_name=stage.stage_name,
                wallet_address=wallet.address if wallet else "",
            )
            stage.eligibility_status = chk["status"]
            stage.eligibility_evidence = chk["evidence"]
            stage.eligibility_wallet_address = wallet.address if wallet else None
        else:
            stage.eligibility_status = "manual_check"
            stage.eligibility_evidence = "Independent project mint page requires manual review."

        stage.eligibility_checked_at = now

    if not drop.is_demo:
        drop.status_kind = "manual" if not drop.is_supported_integration else "unknown"
        drop.status_label = "Manual check" if not drop.is_supported_integration else "Eligibility unverified"

    # Record activity event
    db.add(ActivityEvent(
        event_type="scan",
        label="Eligibility rechecked",
        detail=f"{drop.name} scanned for {wallet.label if wallet else 'demo preview'}",
        icon_name="refresh-cw",
        is_demo=drop.is_demo,
    ))
    await db.commit()

    return EligibilityRecheckResponse(
        drop_id=drop.id,
        status_label=drop.status_label,
        status_kind=drop.status_kind,
        stages=drop.stages,
        checked_at=now,
    )
