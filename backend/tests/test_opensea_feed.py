"""Live-source ingestion does not duplicate listings or invent eligibility."""

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Drop
from app.services import opensea_feed


class Response:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    def raise_for_status(self):
        pass
    async def json(self):
        return {"drops": [{
            "collection_slug": "real-collection", "collection_name": "Real collection",
            "chain": "ethereum", "contract_address": "0x" + "a" * 40,
            "opensea_url": "https://opensea.io/collection/real-collection",
            "is_minting": True,
            "active_stage": {"uuid": "stage-1", "label": "Allowlist",
                "start_time": "2026-10-01T12:00:00Z", "price": "1000000000000000",
                "price_currency_address": opensea_feed.NATIVE_TOKEN,
                "stage_type": "allowlist", "max_per_wallet": 2},
        }]}


class Client:
    def __init__(self, *args, **kwargs):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    def get(self, *args, **kwargs):
        return Response()


@pytest.mark.asyncio
async def test_duplicate_calendars_create_one_unverified_drop(test_db, monkeypatch):
    monkeypatch.setattr(settings, "OPENSEA_API_KEY", "test-key")
    monkeypatch.setattr(opensea_feed.aiohttp, "ClientSession", Client)
    assert await opensea_feed.sync_opensea_drops(test_db) == 1
    drop = (await test_db.execute(select(Drop))).scalar_one()
    assert drop.name == "Real collection"
    assert drop.status_kind == "unknown"
    assert not drop.is_supported_integration
    assert len(drop.stages) == 1
    assert drop.stages[0].eligibility_status == "manual_check"
    assert await opensea_feed.sync_opensea_drops(test_db) == 0
