"""Device registration, owner authorization, and FCM preference delivery."""

import pytest
from firebase_admin import messaging
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.deps import get_db
from app.config import settings
from app.main import app
from app.services import notifier
from app.services.notifier import NotificationService


@pytest.mark.asyncio
async def test_fcm_delivery_respects_saved_preferences(test_db, monkeypatch):
    async def get_test_db():
        yield test_db

    app.dependency_overrides[get_db] = get_test_db
    monkeypatch.setattr(notifier, "AsyncSessionLocal", async_sessionmaker(
        test_db.bind, expire_on_commit=False))
    monkeypatch.setattr(NotificationService, "_get_firebase_app", classmethod(lambda cls: object()))
    sent = []
    monkeypatch.setattr(messaging, "send", lambda message, app: sent.append(message))
    token = "mintly-test-fcm-token-123456"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post("/api/auth/login", json={
                "username": "member", "password": "Member test password 123",
            })
            assert login.status_code == 200
            client.headers["Authorization"] = "Bearer " + login.json()["token"]
            owner = login.json()['user']['id']
            registered = await client.post("/api/notifications/register", json={"token": token})
            assert registered.status_code == 200
            assert registered.json()["preferences"]["daily_list"] is True
            assert await NotificationService.send_notification("New drops", "One drop", "daily_list")
            assert len(sent) == 1

            saved = await client.post("/api/notifications/preferences", json={
                "token": token, "daily_list": False, "mint_status": True,
            })
            assert saved.status_code == 200
            reconnected = await client.post("/api/notifications/register", json={"token": token})
            assert reconnected.json()["preferences"]["daily_list"] is False
            assert not await NotificationService.send_notification("New drops", "Two drops", "daily_list")
            assert len(sent) == 1
            assert await NotificationService.send_notification("Confirmed", "Confirmed", "mint_status", user_id=owner)
            assert len(sent) == 2

            unregistered = await client.post("/api/notifications/unregister", json={"token": token})
            assert unregistered.status_code == 200
            assert not await NotificationService.send_notification("Confirmed", "Again", "mint_status", user_id=owner)
            assert len(sent) == 2
    finally:
        app.dependency_overrides.pop(get_db, None)
        NotificationService.clear_sink()


@pytest.mark.asyncio
async def test_notification_registration_requires_owner_token(test_db, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "APP_SECRET_KEY", "test-owner-secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/notifications/register", json={
            "token": "mintly-test-fcm-token-123456"
        })
    assert response.status_code == 401
