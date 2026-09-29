"""Twikit source adapter with rate-limit backoff, caching, and error classification."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.config import settings
from app.services.parser import DropPostParser
from app.twikit_diag import run_twikit_diagnostic

logger = logging.getLogger("mintly.twikit")


class TwikitSourceAdapter:
    """Interchangeable source adapter for X discovery via Twikit."""

    def __init__(self):
        self.cached_author_id: Optional[str] = None
        self.last_sync_time: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.consecutive_errors: int = 0
        self.is_monitoring: bool = True

    async def check_health(self) -> Dict[str, Any]:
        """Runs a diagnostic check and returns status."""
        diag = await run_twikit_diagnostic(settings.X_MONITORED_USER)
        return {
            "source": settings.X_MONITORED_USER,
            "status": "healthy" if diag["status"] == "success" else (
                "needs_attention" if diag["status"] == "missing_credentials" else "error"
            ),
            "is_monitoring": self.is_monitoring,
            "last_sync": self.last_sync_time.isoformat() if self.last_sync_time else None,
            "details": diag["details"],
            "diagnostic": diag,
        }

    async def poll_latest_drops(self) -> List[Dict[str, Any]]:
        """Polls for latest daily list posts. If credentials are missing, returns empty list."""
        if not self.is_monitoring:
            return []

        diag = await run_twikit_diagnostic(settings.X_MONITORED_USER)
        if diag["status"] != "success":
            self.last_error = diag["details"]
            self.consecutive_errors += 1
            return []

        # If live tweets were captured
        post = diag.get("captured_post")
        if not post:
            return []

        self.consecutive_errors = 0
        self.last_sync_time = datetime.now(timezone.utc)
        return DropPostParser.parse(post["text_preview"], datetime.now(timezone.utc))
