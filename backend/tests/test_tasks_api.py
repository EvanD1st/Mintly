"""Tests for Task APIs, draft review, arming, disarming, and race condition protection."""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.api.deps import get_db
from app.models import Drop, MintStage, Wallet, MintTask
from sqlalchemy import select


@pytest.fixture(autouse=True)
def override_db(test_db):
    async def _get_test_db():
        yield test_db
    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_draft_task_recalculation(test_db):
    """Verifies fee recalculation and spending limit itemization."""
    transport = ASGITransport(app=app)
    wallet_id = (await test_db.execute(select(Wallet.id))).scalar_one()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/tasks/draft", json={
            "wallet_id": wallet_id,
            "drop_id": "orbit",
            "stage_id": "orbit-pub",
            "quantity": 2,
            "fee_cap_eth": "0.0001",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["quantity"] == 2
        assert data["mint_price_each_eth"] == "0.0004"
        assert data["fee_cap_eth"] == "0.0001"
        assert data["total_spend_cap_eth"] == "0.0009"
        assert data["total_spend_cap_wei"] == 900_000_000_000_000
        assert data["is_signer_ready"] is True


@pytest.mark.asyncio
async def test_arm_and_disarm_task_lifecycle(test_db):
    """Verifies that arming creates a durable task and disarming safely cancels it."""
    transport = ASGITransport(app=app)
    wallet_id = (await test_db.execute(select(Wallet.id))).scalar_one()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Arm task
        arm_res = await ac.post("/api/tasks/arm", json={
            "wallet_id": wallet_id,
            "drop_id": "orbit",
            "stage_id": "orbit-pub",
            "quantity": 1,
            "fee_cap_eth": "0.0001",
            "user_consent_confirmed": True,
            "idempotency_key": "idempotency_key_test_12345",
        })
        assert arm_res.status_code == 200
        task_data = arm_res.json()
        assert task_data["status"] == "armed"
        task_id = task_data["id"]

        # Check queue
        q_res = await ac.get("/api/tasks/queue")
        assert q_res.status_code == 200
        q_data = q_res.json()
        assert any(t["id"] == task_id and t["status"] == "armed" for t in q_data["tasks"])

        # Disarm task
        disarm_res = await ac.post(f"/api/tasks/{task_id}/disarm")
        assert disarm_res.status_code == 200
        assert disarm_res.json()["status"] == "disarmed"


@pytest.mark.asyncio
async def test_disarm_race_protection_on_submitted_task(test_db):
    """Verifies that an in-flight submitted transaction cannot be canceled by disarming."""
    # Create an in-flight task directly in DB
    task = MintTask(
        authorization_id="dummy_auth",
        wallet_id="dummy_wallet",
        drop_id="orbit",
        stage_id="orbit-wl",
        status="submitted",
        idempotency_key="submitted_key_123",
        scheduled_for_utc=datetime.now(timezone.utc),
        expires_at_utc=datetime.now(timezone.utc),
        transaction_hash="0x" + "a" * 64,
    )
    test_db.add(task)
    await test_db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(f"/api/tasks/{task.id}/disarm")
        assert res.status_code == 409
        assert "cannot be canceled" in res.json()["detail"]
