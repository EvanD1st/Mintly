"""Only verified @lakzonevn posts or admin imports may reach the feed."""

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_db
from app.main import app
from app.models import Drop, SourceConnection, SourcePost
from app.services import x_feed
from app.services.twikit_adapter import SourceUnavailable, _expanded_text


class FakeAdapter:
    def __init__(self, posts=None, error=None):
        self.posts = posts or []
        self.error = error

    async def fetch_posts(self):
        if self.error:
            raise self.error
        return self.posts


@pytest.mark.asyncio
async def test_x_posts_are_persisted_once_with_provenance(test_db, monkeypatch):
    monkeypatch.setattr(x_feed, "validate_safe_url", lambda url: url)
    post = {
        "post_id": "1234567890123456789",
        "posted_at": datetime(2026, 9, 30, 14, tzinfo=timezone.utc),
        "post_url": "https://x.com/lakzonevn/status/1234567890123456789",
        "text": "Daily mint drops\n1. Real Project\nChain: Base\nTime: 18:00 WAT\n"
                "Price: 0.01 ETH\nLink: https://example.org/mint",
    }
    adapter = FakeAdapter([post])
    assert await x_feed.sync_x_drops(test_db, adapter) == 1
    assert await x_feed.sync_x_drops(test_db, adapter) == 0
    stored = (await test_db.execute(select(SourcePost))).scalar_one()
    drop = (await test_db.execute(select(Drop))).scalar_one()
    assert stored.post_id == post["post_id"]
    assert stored.author_username == "lakzonevn"
    assert not stored.is_manual_import
    assert drop.source_post_id == stored.id
    assert drop.status_kind == "manual"
    assert not drop.is_supported_integration


@pytest.mark.asyncio
async def test_missing_x_session_does_not_create_drop(test_db):
    assert await x_feed.sync_x_drops(test_db, FakeAdapter(error=SourceUnavailable("Authenticated X session required"))) == 0
    source = (await test_db.execute(select(SourceConnection))).scalar_one()
    assert source.status == "needs_attention"
    assert (await test_db.execute(select(Drop))).scalars().all() == []


def test_tco_expands_to_posted_destination():
    class Tweet:
        full_text = "Mint https://t.co/example"
        urls = [{"url": "https://t.co/example", "expanded_url": "https://example.org/mint"}]

    assert _expanded_text(Tweet()) == "Mint https://example.org/mint"


@pytest.mark.asyncio
async def test_unattributed_drop_is_hidden_from_feed_and_detail(test_db):
    test_db.add(Drop(id="os_unattributed", name="Other feed", mint_page_url="https://example.org",
                     is_demo=False))
    await test_db.commit()

    async def get_test_db():
        yield test_db

    app.dependency_overrides[get_db] = get_test_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post("/api/auth/login", json={
                "username": "admin", "password": "Admin test password 123"})
            headers = {"Authorization": "Bearer " + login.json()["token"]}
            feed = await client.get("/api/drops", headers=headers)
            assert feed.status_code == 200
            assert feed.json()["drops"] == []
            assert (await client.get("/api/drops/os_unattributed", headers=headers)).status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
