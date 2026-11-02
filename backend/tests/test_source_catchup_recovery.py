"""Recover an exhausted X cursor without losing saved posts or the catch-up boundary."""
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import SourceConnection, SourcePost, SourceRevision
from app.services import x_feed
from app.services.twscrape_adapter import TwscrapeSourceAdapter
from app.services.twikit_adapter import SourceUnavailable


@pytest.fixture
def timeline(monkeypatch):
    monkeypatch.setitem(sys.modules, 'twscrape.models', SimpleNamespace(
        parse_tweets=lambda value: iter(value.get('tweets', []))))
    owner = SimpleNamespace(id=123, username='cassio_sch')
    now = datetime.now(timezone.utc)

    def tweet(pid, date):
        return SimpleNamespace(id=pid, user=owner, date=date, rawContent='Saved public post',
            links=[], retweetedTweet=None, inReplyToTweetId=None, isQuoteStatus=False)

    def page(tweets, cursor=None, pinned=None):
        payload = {'tweets': tweets}
        if cursor:
            payload['cursor'] = {'cursorType': 'Bottom', 'value': cursor}
        if pinned:
            payload['instructions'] = [{'type': 'TimelinePinEntry', 'tweets': [pinned]}]
        return SimpleNamespace(json=lambda: payload)

    return owner, now, tweet, page


async def test_exhausted_cursor_rewalks_original_boundary_and_deduplicates(test_db, monkeypatch, timeline):
    owner, now, tweet, page = timeline
    boundary = now - timedelta(days=16)
    source = await x_feed.ensure_source(test_db, 'cassio_sch')
    source.catchup_cursor = 'exhausted'
    source.catchup_until = boundary
    source.status = 'needs_attention'
    source.consecutive_failures = 20
    source.last_error = 'Previous refresh failed'
    await test_db.commit()
    calls = []

    class API:
        async def user_tweets_raw(self, uid, limit, kv):
            calls.append((limit, kv))
            if kv:
                assert kv == {'cursor': 'exhausted'}
                return
            yield page([tweet(3001, now)], 'new-top')
            if limit == 200:
                yield page([tweet(3001, now), tweet(3000, now-timedelta(days=17))],
                    'older', pinned=tweet(3001, now))
                raise AssertionError('Pinned post must not keep history pagination open')

    async def fetch(self, name, on_post, **kwargs):
        return await self._pages(API(), owner, name, on_post,
            kwargs['cursor'], kwargs['since'], kwargs['on_checkpoint'])

    monkeypatch.setattr(TwscrapeSourceAdapter, 'fetch_posts', fetch)
    await x_feed.sync_x_drops(test_db, source_name='cassio_sch')
    await test_db.refresh(source)
    assert source.status == 'healthy' and source.consecutive_failures == 0
    assert source.last_error is None and source.last_sync_at
    assert source.catchup_cursor is None and source.catchup_until is None
    assert calls == [(40, None), (200, {'cursor': 'exhausted'}), (200, None)]
    assert await test_db.scalar(select(func.count()).select_from(SourcePost)) == 2
    assert await test_db.scalar(select(func.count()).select_from(SourceRevision)) == 2
    other = await test_db.scalar(select(SourceConnection).where(SourceConnection.source_name == 'lakzonevn'))
    assert other.consecutive_failures == 0


async def test_empty_fresh_timeline_keeps_saved_cursor(timeline):
    owner, now, _, _ = timeline
    calls = []

    class API:
        async def user_tweets_raw(self, uid, limit, kv):
            calls.append((limit, kv))
            if False:
                yield

    checkpoint = AsyncMock()
    with pytest.raises(SourceUnavailable, match='no timeline pages'):
        await TwscrapeSourceAdapter()._pages(API(), owner, owner.username, AsyncMock(),
            'saved-cursor', now-timedelta(days=16), checkpoint)
    checkpoint.assert_not_awaited()
    assert calls == [(40, None)]


async def test_failed_rewalk_retains_original_boundary_and_reports_degraded(test_db, monkeypatch, timeline):
    owner, now, tweet, page = timeline
    boundary = now-timedelta(days=16)
    source = await x_feed.ensure_source(test_db, owner.username)
    source.catchup_cursor = 'exhausted'
    source.catchup_until = boundary
    await test_db.commit()

    class API:
        async def user_tweets_raw(self, uid, limit, kv):
            if limit == 40:
                yield page([tweet(3010, now)], 'new-top')

    async def fetch(self, name, on_post, **kwargs):
        return await self._pages(API(), owner, name, on_post,
            kwargs['cursor'], kwargs['since'], kwargs['on_checkpoint'])

    monkeypatch.setattr(TwscrapeSourceAdapter, 'fetch_posts', fetch)
    await x_feed.sync_x_drops(test_db, source_name=owner.username)
    await test_db.refresh(source)
    assert source.status == 'needs_attention' and source.consecutive_failures == 1
    assert source.last_sync_at is None and source.next_attempt_at
    assert source.catchup_cursor is None
    assert source.catchup_until.replace(tzinfo=timezone.utc) == boundary
    assert 'no timeline pages' in source.last_error
    assert await test_db.scalar(select(func.count()).select_from(SourcePost)) == 1


async def test_pinned_post_is_saved_but_does_not_prevent_boundary_completion(timeline):
    owner, now, tweet, page = timeline
    pinned = tweet(3020, now)

    class API:
        async def user_tweets_raw(self, uid, limit, kv):
            yield page([pinned, tweet(3019, now-timedelta(days=17))], 'older', pinned=pinned)
            raise AssertionError('The requested history boundary was already reached')

    save, checkpoint = AsyncMock(), AsyncMock()
    await TwscrapeSourceAdapter()._pages(API(), owner, owner.username, save, None,
        now-timedelta(days=16), checkpoint)
    assert [c.args[0]['post_id'] for c in save.await_args_list] == ['3020', '3019']
    checkpoint.assert_awaited_once_with(None, None)


async def test_rewalk_commits_progress_before_interruption(timeline):
    owner, now, tweet, page = timeline
    boundary = now-timedelta(days=16)

    class API:
        async def user_tweets_raw(self, uid, limit, kv):
            if kv:
                return
            yield page([tweet(3030, now)], 'new-top')
            if limit == 200:
                raise TimeoutError('Interrupted after a saved page')

    save, checkpoint = AsyncMock(), AsyncMock()
    with pytest.raises(TimeoutError):
        await TwscrapeSourceAdapter()._pages(API(), owner, owner.username, save,
            'exhausted', boundary, checkpoint)
    assert [c.args for c in checkpoint.await_args_list] == [(None, boundary), ('new-top', boundary)]
    assert save.await_count == 2


async def test_source_unavailable_preserves_reason_and_provider_backoff(monkeypatch, tmp_path):
    path = tmp_path/'accounts.db'
    path.touch(mode=0o600)
    monkeypatch.setattr(settings, 'X_DISCOVERY_ENABLED', True)
    monkeypatch.setattr(settings, 'TWSCRAPE_ACCOUNTS_FILE', str(path))
    adapter = TwscrapeSourceAdapter()
    monkeypatch.setattr(adapter, 'provider_backoff', lambda path: 0)
    error = SourceUnavailable('X returned no timeline pages; saved posts are retained.', 2400)
    monkeypatch.setattr(adapter, '_fetch', AsyncMock(side_effect=error))
    with pytest.raises(SourceUnavailable) as result:
        await adapter.fetch_posts('cassio_sch')
    assert result.value is error and result.value.retry_after_seconds == 2400


async def test_unexpected_provider_exception_does_not_expose_session_details(monkeypatch, tmp_path):
    path = tmp_path/'accounts.db'
    path.touch(mode=0o600)
    monkeypatch.setattr(settings, 'X_DISCOVERY_ENABLED', True)
    monkeypatch.setattr(settings, 'TWSCRAPE_ACCOUNTS_FILE', str(path))
    adapter = TwscrapeSourceAdapter()
    monkeypatch.setattr(adapter, 'provider_backoff', lambda path: 0)
    monkeypatch.setattr(adapter, '_fetch', AsyncMock(side_effect=RuntimeError('secret session cookie')))
    with pytest.raises(SourceUnavailable) as result:
        await adapter.fetch_posts('cassio_sch')
    assert str(result.value) == 'X discovery could not refresh (RuntimeError); saved lists are retained.'
