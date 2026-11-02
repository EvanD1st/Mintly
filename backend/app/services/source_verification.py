"""Retire old public-list verification jobs, preserving all source and mint records."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import or_, select
from app.models import Drop, FeedMention, MintStage, MintTask, SourcePost
from app.services.automatic import TERMINAL
from app.services.feed_sources import SOURCE_NAMES
from app.services.daily_list_parser import parse
from app.services.mint_plans import aware

VERIFICATION_DAYS = 14
WAT = ZoneInfo('Africa/Lagos')


async def retire_historical_verification(db, *, now=None, limit=100):
    now = now or datetime.now(timezone.utc)
    cutoff = now.astimezone(WAT).date() - timedelta(days=VERIFICATION_DAYS)
    cutoff_at = datetime.combine(cutoff, time.min, WAT).astimezone(timezone.utc)
    posts = (await db.scalars(select(SourcePost).where(
        SourcePost.author_username.in_(SOURCE_NAMES), SourcePost.is_manual_import.is_(False),
        SourcePost.is_daily_list.is_(True), SourcePost.published_at.is_not(None),
        SourcePost.processing_error.is_not(None), SourcePost.verification_retired_at.is_(None),
        SourcePost.list_date < cutoff, SourcePost.posted_at < cutoff_at,
    ).order_by(SourcePost.posted_at).limit(limit).with_for_update(skip_locked=True))).all()
    retired = 0
    for post in posts:
        mentions = (await db.execute(select(FeedMention.drop_id, FeedMention.details)
            .where(FeedMention.post_id == post.id))).all()
        # A list can mention stages on another day. Malformed dates stay visible
        # for review instead of being treated as proof that the list is old.
        try:
            reported_days = [date.fromisoformat(day) for _, details in mentions for day in details.get('days', [])]
            # A correction may not have reached the published mentions yet.
            # Check current saved text locally before retiring another retry.
            reported_days.extend(datetime.fromisoformat(stage['starts_at']).astimezone(WAT).date()
                for entry in parse(post.expanded_text or post.full_text, aware(post.posted_at))
                for stage in entry.get('source_reported_stages', []))
        except (TypeError, ValueError, AttributeError):
            continue
        if any(day >= cutoff for day in reported_days):
            continue
        drop_ids = select(Drop.id).where(Drop.source_post_id == post.id).union(
            select(FeedMention.drop_id).where(FeedMention.post_id == post.id))
        recent_stage = await db.scalar(select(MintStage.id).where(MintStage.drop_id.in_(drop_ids),
            or_(MintStage.start_time_utc >= cutoff_at, MintStage.end_time_utc >= cutoff_at)).limit(1))
        if recent_stage:
            continue
        active_task = await db.scalar(select(MintTask.id).where(MintTask.drop_id.in_(drop_ids),
            MintTask.status.not_in(TERMINAL)).limit(1))
        if active_task:
            continue
        post.verification_retired_at = now
        post.next_process_at = None
        retired += 1
    await db.commit()
    return retired
