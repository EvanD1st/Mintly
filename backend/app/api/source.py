"""Source connection health, preferences, and activity endpoints."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, verify_owner_authorization
from app.models import SourceConnection, ActivityEvent, Drop
from app.schemas.activity import SourceStatusResponse, ActivityEventSchema
from app.twikit_diag import run_twikit_diagnostic

router = APIRouter(tags=["source_and_activity"])


@router.get("/source/status", response_model=SourceStatusResponse)
async def get_source_status(db: AsyncSession = Depends(get_db)):
    """Returns the current status of the X/Twikit connection."""
    stmt = select(SourceConnection).where(SourceConnection.source_name == "lakzonevn")
    src = (await db.execute(stmt)).scalar_one_or_none()

    drops_count = len((await db.execute(select(Drop))).scalars().all())

    is_monitoring = src.is_monitoring if src else True
    last_sync = src.last_sync_at if src else None

    # Check whether live credentials exist or whether connection needs attention
    diag = await run_twikit_diagnostic()
    if diag["status"] == "missing_credentials":
        status_text = "needs_attention"
        summary_text = "Monitoring paused · saved list" if not is_monitoring else "Connection needs attention · credentials required"
    elif diag["status"] == "success":
        status_text = "healthy"
        summary_text = f"Last synced 17:02 · {drops_count} drops"
    else:
        status_text = "error"
        summary_text = f"Connection error: {diag.get('error_type')}"

    return SourceStatusResponse(
        source_name="@lakzonevn",
        status=status_text,
        is_monitoring=is_monitoring,
        last_sync_at=last_sync,
        last_error=src.last_error if src else None,
        drops_count=drops_count,
        summary_text=summary_text,
    )


@router.post("/source/toggle")
async def toggle_monitoring(
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(verify_owner_authorization),
):
    """Toggles active background monitoring on or off."""
    stmt = select(SourceConnection).where(SourceConnection.source_name == "lakzonevn")
    src = (await db.execute(stmt)).scalar_one_or_none()
    if src:
        src.is_monitoring = not src.is_monitoring
        is_mon = src.is_monitoring
        await db.commit()
    else:
        is_mon = False

    return {"is_monitoring": is_mon, "message": "Monitoring enabled" if is_mon else "Monitoring paused"}


@router.get("/activity", response_model=List[ActivityEventSchema])
async def list_activity(db: AsyncSession = Depends(get_db)):
    """Returns activity journal events."""
    stmt = select(ActivityEvent).order_by(ActivityEvent.event_time.desc()).limit(50)
    events = (await db.execute(stmt)).scalars().all()

    results = []
    lagos_tz = ZoneInfo("Africa/Lagos")
    for ev in events:
        t_lagos = ev.event_time.astimezone(lagos_tz)
        results.append(ActivityEventSchema(
            id=ev.id,
            event_type=ev.event_type,
            label=ev.label,
            detail=ev.detail,
            icon_name=ev.icon_name,
            is_demo=ev.is_demo,
            event_time=ev.event_time,
            formatted_time=t_lagos.strftime("%H:%M"),
        ))
    return results
