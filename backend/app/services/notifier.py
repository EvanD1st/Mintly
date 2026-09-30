"""Firebase Cloud Messaging delivery for registered Mintly devices."""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.activity import NotificationDevice
from app.models.user import User

logger = logging.getLogger("mintly.notifications")


class NotificationService:
    _logged_notifications = []
    _firebase_app = None

    @classmethod
    def _get_firebase_app(cls):
        if cls._firebase_app is not None:
            return cls._firebase_app
        path = settings.FIREBASE_CREDENTIALS_FILE
        if not path or not Path(path).is_file():
            logger.warning("FCM is unavailable: Firebase credentials file is not configured.")
            return None
        import firebase_admin
        from firebase_admin import credentials

        cls._firebase_app = firebase_admin.initialize_app(
            credentials.Certificate(path), name="mintly-fcm"
        )
        return cls._firebase_app

    @classmethod
    async def send_notification(
        cls,
        title: str,
        body: str,
        category: str = "daily_list",
        deep_link: Optional[str] = None,
        data: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """Send to opted-in devices; return True only if FCM accepted a message."""
        payload = {
            "title": title,
            "body": body,
            "category": category,
            "deep_link": deep_link,
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "delivered": 0,
        }
        cls._logged_notifications.append(payload)
        cls._logged_notifications = cls._logged_notifications[-100:]

        try:
            app = cls._get_firebase_app()
        except Exception:
            logger.exception("FCM initialization failed")
            return False
        if app is None:
            return False

        from firebase_admin import messaging

        async with AsyncSessionLocal() as session:
            devices = (await session.execute(
                select(NotificationDevice).join(User, User.id == NotificationDevice.user_id).where(
                    NotificationDevice.is_active.is_(True), User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    *((NotificationDevice.user_id == user_id,) if user_id else ()),
                )
            )).scalars().all()
            for device in devices:
                if not (device.preferences or {}).get(category, True):
                    continue
                message = messaging.Message(
                    token=device.device_token,
                    notification=messaging.Notification(title=title, body=body),
                    data={**(data or {}), "category": category, "deep_link": deep_link or ""},
                    android=messaging.AndroidConfig(priority="high"),
                )
                try:
                    await asyncio.to_thread(messaging.send, message, app=app)
                    payload["delivered"] += 1
                except messaging.UnregisteredError:
                    device.is_active = False
                    logger.info("Deactivated an unregistered FCM token")
                except Exception:
                    logger.exception("FCM delivery failed for a registered device")
            await session.commit()
        return payload["delivered"] > 0

    @classmethod
    def get_recent_notifications(cls):
        return list(cls._logged_notifications)

    @classmethod
    def clear_sink(cls):
        cls._logged_notifications.clear()
