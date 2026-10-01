"""Personal OpenSea plans must never become unattended mint authorizations."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_db
from app.main import app
from app.models import MintPlan, User, Wallet
from app.services.opensea import OpenSeaUnavailable, collection_slug, stage_schedule
from app.services.signer.base import SEADROP_V1_ADDRESS


@pytest.mark.parametrize("url", [
    "http://opensea.io/collection/example",
    "https://opensea.io.evil.test/collection/example",
    "https://opensea.io/collection/example?redirect=evil",
    "https://opensea.io:bad/collection/example",
    "https://opensea.io/collection/../../private",
])
def test_only_direct_opensea_collection_urls(url):
    with pytest.raises(OpenSeaUnavailable):
        collection_slug(url)


def test_stage_schedule_is_sorted_and_uses_native_price():
    now = datetime.now(timezone.utc)
    def stage(index, minutes):
        return {"uuid": str(index), "stage_type": "public_sale", "label": "Public",
                "start_time": (now + timedelta(minutes=minutes)).isoformat(),
                "end_time": (now + timedelta(minutes=minutes + 30)).isoformat(),
                "price": "1000000000000000", "max_per_wallet": "2",
                "price_currency_address": "0x" + "0" * 40}
    sorted_stages = stage_schedule({"stages": [stage(2, 60), stage(1, 10)]})
    assert [s["uuid"] for s in sorted_stages] == ["1", "2"]


@pytest.mark.asyncio
async def test_member_import_checks_wallet_and_never_creates_mint_task(test_db, monkeypatch):
    user = (await test_db.execute(select(User).where(User.username == "member"))).scalar_one()
    wallet = Wallet(user_id=user.id, label="MetaMask", address="0x" + "1" * 40,
                    signing_capability="interactive", supported_chains=["Base"], is_default=True)
    test_db.add(wallet)
    await test_db.commit()

    now = datetime.now(timezone.utc)
    detail = {
        "collection_slug": "example", "collection_name": "Example",
        "opensea_url": "https://opensea.io/collection/example",
        "drop_type": "seadrop_v1_erc721", "chain": "base",
        "contract_address": "0x" + "2" * 40,
        "stages": [{"uuid": "public-1", "stage_type": "public_sale", "label": "Public",
                    "start_time": (now - timedelta(minutes=1)).isoformat(),
                    "end_time": (now + timedelta(hours=1)).isoformat(),
                    "price": "1000000000000000", "max_per_wallet": "2",
                    "price_currency_address": "0x" + "0" * 40}],
    }
    transaction = {"chain": "base", "to": SEADROP_V1_ADDRESS,
                   "data": "0x12345678", "value": hex(10**15)}
    fake = type("FakeOpenSea", (), {"get_drop": AsyncMock(return_value=detail),
                                    "build_mint": AsyncMock(return_value=(200, transaction))})()
    monkeypatch.setattr("app.api.mint_plans.OpenSeaClient", lambda: fake)
    monkeypatch.setattr("app.services.mint_plans.OpenSeaClient", lambda: fake)
    monkeypatch.setattr("app.services.mint_plans.estimate_network_fee", AsyncMock(return_value=10**13))

    async def get_test_db():
        yield test_db
    app.dependency_overrides[get_db] = get_test_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/api/mint-plans", json={
                "url": "https://opensea.io/collection/example"})).status_code == 401
            login = await client.post("/api/auth/login", json={
                "username": "member", "password": "Member test password 123"})
            client.headers["Authorization"] = "Bearer " + login.json()["token"]
            imported = await client.post("/api/mint-plans", json={
                "url": "https://opensea.io/collection/example"})
            assert imported.status_code == 200, imported.text
            assert imported.json()["status"] == "ready_for_approval"
            assert imported.json()["estimated_network_fee_eth"] == "0.00001"
            assert len((await client.get("/api/mint-plans")).json()) == 1
            assert (await client.get("/api/tasks/queue")).json()["tasks"] == []
            stored_plan = (await test_db.execute(select(MintPlan))).scalar_one()
            assert stored_plan.wallet_id == wallet.id
            stored_plan.last_checked_at = now - timedelta(minutes=1)
            await test_db.commit()

            fake.build_mint.return_value = (422, None)
            refreshed = await client.post(f"/api/mint-plans/{imported.json()['id']}/refresh")
            assert refreshed.status_code == 200, refreshed.text
            assert refreshed.json()["status"] == "not_ready"
            assert refreshed.json()["mint_value_eth"] is None
            admin_login = await client.post("/api/auth/login", json={
                "username": "admin", "password": "Admin test password 123"})
            client.headers["Authorization"] = "Bearer " + admin_login.json()["token"]
            assert (await client.get("/api/mint-plans")).json() == []
            assert (await client.post(f"/api/mint-plans/{imported.json()['id']}/refresh")).status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
