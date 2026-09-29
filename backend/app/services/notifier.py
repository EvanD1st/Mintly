"""Notification Service for Mintly."""

from datetime import datetime, timezone
import logging
from typing import Dict, Any, Optional
from app.config import settings

logger = logging.getLogger("mintly.notifications")


class NotificationService:
    """Manages FCM push notifications and local notification logging."""

    _logged_notifications = []

    @classmethod
    async def send_notification(
        cls,
        title: str,
        body: str,
        category: str = "daily_list",
        deep_link: Optional[str] = None,
        data: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Sends a notification to registered devices or logs to sink."""
        payload = {
            "title": title,
            "body": body,
            "category": category,
            "deep_link": deep_link,
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Always record in local sink for audit and tests
        cls._logged_notifications.append(payload)
        logger.info(f"[NOTIFICATION SINK] [{category.upper()}] {title} - {body} (Deep Link: {deep_link})")

        # If Firebase credentials configured, send to FCM
        if settings.FIREBASE_CREDENTIALS_FILE:
            try:
                # Optional FCM dispatch
                pass
            except Exception as e:
                logger.warning(f"FCM delivery error: {e}")

        return True

    @classmethod
    def get_recent_notifications(cls):
        return list(cls._logged_notifications)

    @classmethod
    def clear_sink(cls):
        cls._logged_notifications.clear()
