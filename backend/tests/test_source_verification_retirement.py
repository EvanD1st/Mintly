"""Historical verification retires without deleting records or claiming success."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from app.api.source import get_source_status, retry_saved_post
from app.models import Drop, FeedMention, MintStage, SourcePost, SourceRevision
from app.services import x_feed
from app.services.mint_plans import aware
from app.services.source_verification import retire_historical_verification, WAT
from test_today_armed import armed_fixture


async def saved_list(db, pid='4001', *, age=60, published=True, manual=False, source='lakzonevn'):
    now = datetime.now(timezone.utc)
    posted = now-timedelta(days=age)
    text = (f'Daily mint drops {posted:%B %d}\n1. Historical collection\n'
        'Chain: Unknown\nTime: 13:00 UTC\nPrice: Free\nLink: https://opensea.io/collection/history')
    await x_feed.ensure_source(db, source)
    await x_feed.save_raw(db, dict(post_id=pid, text=text, raw_text=text,
        posted_at=posted, author_username=source), source)
    post = await db.scalar(select(SourcePost).where(SourcePost.post_id == pid))
    post.is_daily_list = True
    post.is_manual_import = manual
    post.list_date = posted.astimezone(WAT).date()
    post.published_at = now if published else None
    post.processing_error = 'Some links or networks are waiting for verification.'
    post.next_process_at = now+timedelta(minutes=2)
    drop = Drop(id='drop-'+pid, source_post_id=post.id, name='Historical collection',
        mint_page_url='https://opensea.io/collection/history', chain_id=0, is_demo=False)
    db.add(drop)
    await db.flush()
    db.add(FeedMention(post_id=post.id, entry_key='entry', drop_id=drop.id,
        details={'days': [post.list_date.isoformat()]}))
    await db.commit()
    return post, drop


async def test_retirement_preserves_evidence_collection_and_status_count(test_db, monkeypatch):
    post, drop = await saved_list(test_db)
    original = (post.full_text, post.content_hash, post.processed_hash, post.processing_error, aware(post.published_at))
    assert await retire_historical_verification(test_db) == 1
    await test_db.refresh(post)
    assert post.verification_retired_at and post.next_process_at is None
    assert (post.full_text, post.content_hash, post.processed_hash, post.processing_error, aware(post.published_at)) == original
    for model in (SourcePost, SourceRevision, Drop, FeedMention):
        assert await test_db.scalar(select(func.count()).select_from(model)) == 1
    assert await retire_historical_verification(test_db) == 0
    status = await get_source_status(admin=None, db=test_db)
    assert status.drops_count == 1 and status.pending_posts == []
    process = AsyncMock()
    monkeypatch.setattr(x_feed, 'process_post', process)
    assert await x_feed.process_pending(test_db) == 0
    process.assert_not_awaited()


@pytest.mark.parametrize('reason', ['recent', 'unpublished', 'manual', 'future_report', 'future_stage', 'invalid_report', 'future_raw_revision'])
async def test_recent_unpublished_manual_and_upcoming_lists_remain_active(test_db, reason):
    post, drop = await saved_list(test_db, age=1 if reason == 'recent' else 60,
        published=reason != 'unpublished', manual=reason == 'manual')
    if reason in ('future_report', 'invalid_report'):
        mention = await test_db.get(FeedMention, (post.id, 'entry'))
        mention.details = {'days': [(datetime.now(timezone.utc)+timedelta(days=1)).date().isoformat()
            if reason == 'future_report' else 'unreadable-date']}
    if reason == 'future_stage':
        test_db.add(MintStage(id='upcoming', drop_id=drop.id, stage_name='Upcoming',
            start_time_utc=datetime.now(timezone.utc)+timedelta(days=1)))
    if reason == 'future_raw_revision':
        tomorrow = datetime.now(timezone.utc)+timedelta(days=1)
        post.expanded_text = (f'Mints today – {tomorrow:%B %d}\n1. Corrected collection @project\n'
            'https://opensea.io/collection/history\n1,000 | Free\nPublic 13:00 UTC')
    await test_db.commit()
    assert await retire_historical_verification(test_db) == 0
    await test_db.refresh(post)
    assert post.verification_retired_at is None and post.next_process_at
    assert len((await get_source_status(admin=None, db=test_db)).pending_posts) == 1


@pytest.mark.parametrize('status', ['armed', 'confirmed'])
async def test_linked_task_and_authorization_are_preserved(test_db, monkeypatch, status):
    _, _, _, task, auth = await armed_fixture(test_db, monkeypatch)
    post, _ = await saved_list(test_db)
    mention = await test_db.get(FeedMention, (post.id, 'entry'))
    mention.drop_id = task.drop_id
    stage = await test_db.get(MintStage, task.stage_id)
    stage.start_time_utc = datetime.now(timezone.utc)-timedelta(days=60)
    task.status = status
    await test_db.commit()
    snapshot = (task.status, task.authorization_id, auth.snapshot)
    assert await retire_historical_verification(test_db) == (0 if status == 'armed' else 1)
    await test_db.refresh(task)
    await test_db.refresh(auth)
    assert (task.status, task.authorization_id, auth.snapshot) == snapshot
    assert bool(post.verification_retired_at) == (status == 'confirmed')


async def test_same_post_recheck_keeps_retirement_but_new_revision_can_be_processed(test_db):
    post, _ = await saved_list(test_db)
    await retire_historical_verification(test_db)
    item = dict(post_id=post.post_id, text=post.full_text, raw_text=post.full_text,
        posted_at=post.posted_at.replace(tzinfo=timezone.utc), author_username='lakzonevn')
    await x_feed.save_raw(test_db, item, 'lakzonevn')
    await test_db.refresh(post)
    assert post.verification_retired_at
    assert await x_feed.process_post(test_db, post.id) == 0
    item['text'] += '\nSource corrected this entry'
    item['raw_text'] = item['text']
    await x_feed.save_raw(test_db, item, 'lakzonevn')
    await test_db.refresh(post)
    assert post.verification_retired_at is None and post.processing_error is None
    assert post.next_process_at is None and post.content_hash != post.processed_hash
    assert await retire_historical_verification(test_db) == 0
    assert await test_db.scalar(select(func.count()).select_from(SourceRevision)) == 2


async def test_retry_endpoint_cannot_silently_restart_retired_jobs(test_db):
    post, _ = await saved_list(test_db)
    await retire_historical_verification(test_db)
    with pytest.raises(HTTPException) as error:
        await retry_saved_post(post.id, admin=None, db=test_db)
    assert error.value.status_code == 409
    assert 'history are preserved' in error.value.detail
    assert post.verification_retired_at and post.next_process_at is None


async def test_new_lists_still_process_while_old_retries_are_retired(test_db, monkeypatch):
    old, _ = await saved_list(test_db)
    recent, _ = await saved_list(test_db, pid='4002', age=0)
    recent.next_process_at = None
    await test_db.commit()
    process = AsyncMock(return_value=1)
    monkeypatch.setattr(x_feed, 'process_post', process)
    assert await x_feed.process_pending(test_db) == 1
    process.assert_awaited_once_with(test_db, recent.id)
    await test_db.refresh(old)
    assert old.verification_retired_at
