"""Live source health and account-scoped activity."""

from datetime import timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models import ActivityEvent, Drop, SourceConnection, SourcePost, User
from app.schemas.activity import ActivityEventSchema, SourceStatusResponse
from app.services.feed_sources import SOURCE_NAMES,approved,health

router = APIRouter(tags=["source_and_activity"])


@router.get("/source/status", response_model=SourceStatusResponse)
async def get_source_status(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    sources=await health(db)
    count = (await db.execute(select(func.count()).select_from(Drop).join(SourcePost).where(
        Drop.is_demo.is_(False), approved(),
        SourcePost.is_manual_import.is_(False),
    ))).scalar_one()
    active = any(s['is_monitoring'] for s in sources)
    last_sync = max((s['last_sync_at'] for s in sources if s['last_sync_at']),default=None)
    status = 'healthy' if all(s['status']=='healthy' and not s['delayed'] for s in sources) else 'needs_attention'
    errors=[s['last_error'] for s in sources if s['last_error']]
    pending=(await db.scalars(select(SourcePost).where(approved(),SourcePost.processing_error.is_not(None))
        .order_by(SourcePost.updated_at.desc()).limit(20))).all()
    if not active:
        summary = "Discovery monitoring paused by admin"
    elif status == "needs_attention":
        summary = ' · '.join('@'+s['name']+(' refresh delayed' if s['status']!='healthy' or s['delayed'] else ' connected') for s in sources)
    elif last_sync:
        summary = f"Both sources connected · {count} saved collections"
    else:
        summary = "Waiting for source posts"
    return SourceStatusResponse(
        source_name="Mint sources on X", status=status, is_monitoring=active,
        last_sync_at=last_sync, last_error='; '.join(errors) or None,
        drops_count=count, summary_text=summary,sources=sources,
        pending_posts=[{'id':p.id,'author':p.author_username,'note':p.processing_error} for p in pending],
    )


@router.post("/source/toggle")
async def toggle_monitoring(
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db), source_name: str='lakzonevn',
):
    source_name=source_name.lower()
    if source_name not in SOURCE_NAMES:raise HTTPException(422,'Choose an approved source.')
    source = (await db.execute(select(SourceConnection).where(
        SourceConnection.source_name == source_name,
    ))).scalar_one_or_none()
    if source is None:
        source = SourceConnection(source_name=source_name, source_type="twscrape", status="needs_attention",
                                  is_monitoring=False)
        db.add(source)
    else:
        source.is_monitoring = not source.is_monitoring
    await db.commit()
    return {"is_monitoring": source.is_monitoring}


@router.post('/source/posts/{post_id}/retry')
async def retry_saved_post(post_id:str,admin=Depends(require_admin),db=Depends(get_db)):
    post=await db.scalar(select(SourcePost).where(SourcePost.id==post_id,approved()))
    if not post:raise HTTPException(404,'Saved source post not found.')
    post.processed_hash=None;post.next_process_at=None
    await db.commit();return {'queued':True}


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
