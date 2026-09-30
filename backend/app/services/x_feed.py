"""Persist only @lakzonevn posts and administrator-imported lists."""

import logging
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from app.models import Drop, MintStage, SourceConnection, SourcePost
from app.services.parser import DropPostParser
from app.services.twikit_adapter import SourceUnavailable, TwikitSourceAdapter
from app.services.url_validator import URLSecurityError, validate_safe_url

logger = logging.getLogger("mintly.x_feed")


async def sync_x_drops(db, adapter=None):
    source = (await db.execute(select(SourceConnection).where(
        SourceConnection.source_name == "lakzonevn"))).scalar_one_or_none()
    if source is None:
        source = SourceConnection(source_name="lakzonevn", source_type="twikit",
                                  status="needs_attention", is_monitoring=True)
        db.add(source)
        await db.flush()
    if not source.is_monitoring:
        source.status = "monitoring_paused"
        await db.commit()
        return 0

    try:
        posts = await (adapter or TwikitSourceAdapter()).fetch_posts()
    except SourceUnavailable as error:
        source.status = "needs_attention"
        source.last_error = str(error)
        source.consecutive_failures += 1
        await db.commit()
        return 0
    except Exception as error:
        logger.warning("X sync failed: %s", type(error).__name__)
        source.status = "error"
        source.last_error = f"X polling failed ({type(error).__name__})."
        source.consecutive_failures += 1
        await db.commit()
        return 0

    new_drops = 0
    for item in posts:
        if not re.fullmatch(r"\d{1,30}", item["post_id"]):
            continue
        exists = (await db.execute(select(SourcePost.id).where(
            SourcePost.post_id == item["post_id"]))).scalar_one_or_none()
        if exists:
            continue
        parsed = DropPostParser.parse(item["text"], item["posted_at"])
        safe = []
        for drop_data in parsed:
            url = drop_data["mint_page_url"]
            if not url.startswith("https://") or urlparse(url).hostname in {"x.com", "twitter.com"}:
                continue
            try:
                drop_data["mint_page_url"] = validate_safe_url(url)
            except URLSecurityError:
                continue
            safe.append(drop_data)
        post = SourcePost(post_id=item["post_id"], author_username="lakzonevn",
                          full_text=item["text"], posted_at=item["posted_at"],
                          extracted_urls=[d["mint_page_url"] for d in safe],
                          is_daily_list=True, is_manual_import=False)
        db.add(post)
        await db.flush()
        for data in safe:
            drop_id = f"x_{uuid.uuid4().hex[:12]}"
            db.add(Drop(id=drop_id, source_post_id=post.id,
                        name=data["name"][:150], chain=data["chain"],
                        chain_id=data["chain_id"], mint_page_url=data["mint_page_url"],
                        site_label=data["site_label"], icon_name=data["icon_name"],
                        status_label="Manual check", status_kind="manual",
                        is_supported_integration=False,
                        manual_notice=f"From @lakzonevn: {item['post_url']}. Check the official mint page and MetaMask before signing.",
                        is_demo=False))
            for index, stage in enumerate(data["stages"]):
                db.add(MintStage(id=f"{drop_id}_st_{index}", drop_id=drop_id, **stage))
            new_drops += 1
    source.status = "healthy"
    source.last_sync_at = datetime.now(timezone.utc)
    source.last_error = None
    source.consecutive_failures = 0
    await db.commit()
    return new_drops
