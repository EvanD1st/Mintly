"""Real drop feed with truthful, account-scoped wallet status."""

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db
from app.models import Drop, DismissedDrop, SourceConnection, SourcePost, User, Wallet
from app.schemas.drop import DropListResponse, DropSchema

router = APIRouter(prefix="/drops", tags=["drops"])


@router.get("", response_model=DropListResponse)
async def list_drops(
    filter_kind: Optional[str] = "all", user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    approved = or_(SourcePost.is_manual_import.is_(True), and_(
        SourcePost.author_username == "lakzonevn", SourcePost.is_manual_import.is_(False)))
    stmt = select(Drop).join(SourcePost, Drop.source_post_id == SourcePost.id).options(selectinload(Drop.stages)).where(
        Drop.is_demo.is_(False),
        approved,
        ~select(DismissedDrop.drop_id).where(DismissedDrop.user_id == user.id,
            DismissedDrop.drop_id == Drop.id).exists(),
    ).order_by(Drop.updated_at.desc()).limit(100)
    drops = (await db.execute(stmt)).scalars().all()
    if filter_kind and filter_kind != "all":
        drops = [drop for drop in drops if drop.status_kind == filter_kind]
    source = (await db.execute(select(SourceConnection).where(
        SourceConnection.source_name == "lakzonevn",
    ))).scalar_one_or_none()
    if user.role != 'admin':
        source_text = ''
    elif source and source.last_sync_at:
        synced = source.last_sync_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Africa/Lagos"))
        source_text = f"@lakzonevn checked {synced:%d %b %H:%M} WAT"
    else:
        source_text = "@lakzonevn feed awaiting an X session; admin imports are available"
    wallet = (await db.execute(select(Wallet).where(Wallet.user_id == user.id, Wallet.archived_at.is_(None)).order_by(
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
    drop = (await db.execute(select(Drop).join(SourcePost, Drop.source_post_id == SourcePost.id)
        .options(selectinload(Drop.stages)).where(
        Drop.id == drop_id, Drop.is_demo.is_(False),
        or_(SourcePost.is_manual_import.is_(True), and_(
            SourcePost.author_username == "lakzonevn", SourcePost.is_manual_import.is_(False))),
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
