"""Real drop feed with truthful, account-scoped wallet status."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db
from app.models import Drop, SourceConnection, User, Wallet
from app.schemas.drop import DropListResponse, DropSchema

router = APIRouter(prefix="/drops", tags=["drops"])


@router.get("", response_model=DropListResponse)
async def list_drops(
    filter_kind: Optional[str] = "all", user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stmt = select(Drop).options(selectinload(Drop.stages)).where(
        Drop.is_demo.is_(False),
        or_(~Drop.id.like("os_%"), Drop.updated_at >= cutoff),
    ).order_by(Drop.updated_at.desc()).limit(100)
    drops = (await db.execute(stmt)).scalars().all()
    if filter_kind and filter_kind != "all":
        drops = [drop for drop in drops if drop.status_kind == filter_kind]
    source = (await db.execute(select(SourceConnection).where(
        SourceConnection.source_name == "opensea",
    ))).scalar_one_or_none()
    if source and source.last_sync_at:
        synced = source.last_sync_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Africa/Lagos"))
        source_text = f"OpenSea updated {synced:%d %b %H:%M} WAT"
    else:
        source_text = "Waiting for live OpenSea data"
    wallet = (await db.execute(select(Wallet).where(Wallet.user_id == user.id).order_by(
        Wallet.is_default.desc(), Wallet.created_at.asc(),
    ).limit(1))).scalar_one_or_none()
    return DropListResponse(
        date_label=datetime.now(timezone.utc).astimezone(ZoneInfo("Africa/Lagos")).strftime("%A, %d %B").upper(),
        source_status_text=source_text,
        drops=drops,
        checked_wallet_label=wallet.address if wallet else "No wallet connected",
        last_checked_text="Wallet-specific eligibility is unverified",
    )


@router.get("/{drop_id}", response_model=DropSchema)
async def get_drop_detail(drop_id: str, db: AsyncSession = Depends(get_db)):
    drop = (await db.execute(select(Drop).options(selectinload(Drop.stages)).where(
        Drop.id == drop_id, Drop.is_demo.is_(False),
    ))).scalar_one_or_none()
    if drop is None:
        raise HTTPException(status_code=404, detail="Drop not found.")
    return drop


@router.post("/{drop_id}/recheck")
async def recheck_drop_eligibility(
    drop_id: str, wallet_id: Optional[str] = None,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if wallet_id:
        wallet = (await db.execute(select(Wallet).where(
            Wallet.id == wallet_id, Wallet.user_id == user.id,
        ))).scalar_one_or_none()
        if wallet is None:
            raise HTTPException(status_code=404, detail="Wallet not found.")
    raise HTTPException(status_code=409, detail=(
        "Wallet-specific eligibility cannot be verified by this source. "
        "Check the official mint page with MetaMask before signing anything."
    ))
