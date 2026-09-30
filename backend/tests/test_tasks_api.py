"""MetaMask accounts cannot create unattended mint tasks."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.main import app


@pytest.mark.asyncio
async def test_task_writes_require_login_and_never_arm(test_db):
    async def get_test_db():
        yield test_db
    app.dependency_overrides[get_db] = get_test_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            request = {"wallet_id": "w", "drop_id": "d", "stage_id": "s",
                       "quantity": 1, "fee_cap_eth": "0.01", "user_consent_confirmed": True,
                       "idempotency_key": "a-valid-key-123456789"}
            assert (await client.post("/api/tasks/arm", json=request)).status_code == 401
            login = await client.post("/api/auth/login", json={
                "username": "member", "password": "Member test password 123",
            })
            assert login.status_code == 200
            client.headers["Authorization"] = "Bearer " + login.json()["token"]
            armed = await client.post("/api/tasks/arm", json=request)
            assert armed.status_code == 409
            assert "MetaMask" in armed.json()["detail"]
            queue = await client.get("/api/tasks/queue")
            assert queue.status_code == 200
            assert queue.json()["tasks"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)
