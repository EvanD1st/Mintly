"""Live source health and account-scoped activity."""

import os
from datetime import timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models import ActivityEvent, Drop, SourceConnection, SourcePost, User
from app.schemas.activity import ActivityEventSchema, SourceStatusResponse
from app.config import settings

router = APIRouter(tags=["source_and_activity"])


@router.get("/source/status", response_model=SourceStatusResponse)
async def get_source_status(db: AsyncSession = Depends(get_db)):
    source = (await db.execute(select(SourceConnection).where(
        SourceConnection.source_name == "lakzonevn",
    ))).scalar_one_or_none()
    count = (await db.execute(select(func.count()).select_from(Drop).join(SourcePost).where(
        Drop.is_demo.is_(False), SourcePost.author_username == "lakzonevn",
        SourcePost.is_manual_import.is_(False),
    ))).scalar_one()
    active = source.is_monitoring if source else True
    last_sync = source.last_sync_at if source else None
    status = source.status if source else "needs_attention"
    if not (settings.TWIKIT_USERNAME and settings.TWIKIT_PASSWORD) and not os.path.isfile(settings.TWIKIT_COOKIES_FILE):
        status = "needs_attention"
    if not active:
        summary = "@lakzonevn monitoring paused by admin"
    elif status == "needs_attention":
        summary = "Authenticated X session required for Twikit; admin imports remain available"
    elif last_sync:
        summary = f"@lakzonevn checked {last_sync.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Africa/Lagos')):%d %b %H:%M} WAT · {count} drops"
    else:
        summary = "Waiting for @lakzonevn posts"
    return SourceStatusResponse(
        source_name="@lakzonevn on X", status=status, is_monitoring=active,
        last_sync_at=last_sync, last_error=source.last_error if source else None,
        drops_count=count, summary_text=summary,
    )


@router.post("/source/toggle")
async def toggle_monitoring(
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    source = (await db.execute(select(SourceConnection).where(
        SourceConnection.source_name == "lakzonevn",
    ))).scalar_one_or_none()
    if source is None:
        source = SourceConnection(source_name="lakzonevn", source_type="twikit", status="needs_attention",
                                  is_monitoring=False)
        db.add(source)
    else:
        source.is_monitoring = not source.is_monitoring
    await db.commit()
    return {"is_monitoring": source.is_monitoring}


@router.get("/activity", response_model=list[ActivityEventSchema])
async def list_activity(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    events = (await db.execute(select(ActivityEvent).where(
        ActivityEvent.is_demo.is_(False),
        or_(ActivityEvent.user_id.is_(None), ActivityEvent.user_id == user.id),
    ).order_by(ActivityEvent.event_time.desc()).limit(50))).scalars().all()
    lagos = ZoneInfo("Africa/Lagos")
    return [ActivityEventSchema(
        id=event.id, event_type=event.event_type, label=event.label,
        detail=event.detail, icon_name=event.icon_name, is_demo=False,
        event_time=event.event_time,
        formatted_time=event.event_time.replace(tzinfo=timezone.utc).astimezone(lagos).strftime("%H:%M"),
    ) for event in events]
