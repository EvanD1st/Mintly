"""Persist only @lakzonevn posts and administrator-imported lists."""

import logging
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select,or_

from app.models import Drop, MintStage, SourceConnection, SourcePost
from app.services.parser import DropPostParser
from app.services.twikit_adapter import SourceUnavailable, TwikitSourceAdapter
from app.services.url_validator import URLSecurityError, validate_safe_url,resolve_safe_url
from app.services.daily_list_parser import VERSION,daily_date,is_daily_list
from app.services.twscrape_adapter import TwscrapeSourceAdapter
from app.services.opensea import collection_slug,OpenSeaUnavailable

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
        await db.commit()
        posts = await (adapter or TwscrapeSourceAdapter()).fetch_posts()
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
    await db.refresh(source, with_for_update=True)
    if not source.is_monitoring:
        source.status='monitoring_paused'
        await db.commit()
        return 0
    fetched_ids={item['post_id'] for item in posts}
    stored=(await db.scalars(select(SourcePost).where(SourcePost.parser_version!=VERSION,
        SourcePost.author_username=='lakzonevn',SourcePost.is_manual_import.is_(False)).limit(100))).all()
    posts += [dict(post_id=p.post_id,text=p.full_text,posted_at=p.posted_at.replace(tzinfo=timezone.utc),
        author_username=p.author_username,post_url=f'https://x.com/lakzonevn/status/{p.post_id}')
        for p in stored if p.post_id not in fetched_ids]
    for item in posts:
        if item.get('author_username','lakzonevn').lower()!='lakzonevn' or not is_daily_list(item['text']):continue
        if not re.fullmatch(r"\d{1,30}", item["post_id"]):
            continue
        await db.refresh(source,with_for_update=True)
        if not source.is_monitoring:
            await db.commit()
            return new_drops
        exists = (await db.execute(select(SourcePost.id).where(
            SourcePost.post_id == item["post_id"]))).scalar_one_or_none()
        post=await db.get(SourcePost,exists) if exists else None
        if post and post.parser_version==VERSION:
            continue
        parsed = DropPostParser.parse(item["text"], item["posted_at"])
        safe = [];unresolved=False
        for drop_data in parsed:
            url = drop_data["mint_page_url"]
            if not url.startswith("https://") or urlparse(url).hostname in {"x.com", "twitter.com"}:
                continue
            try:
                if urlparse(url).hostname=='t.co':url=await resolve_safe_url(url)
                try:url=f'https://opensea.io/collection/{collection_slug(url)}'
                except OpenSeaUnavailable:pass
                drop_data["mint_page_url"] = validate_safe_url(url)
            except URLSecurityError:
                continue
            except Exception:
                unresolved=True
                continue
            safe.append(drop_data)
        if not post:post = SourcePost(post_id=item["post_id"], author_username="lakzonevn",
                          full_text=item.get('raw_text',item["text"]), posted_at=item["posted_at"],
                          extracted_urls=[d["mint_page_url"] for d in safe],
                          is_daily_list=True, is_manual_import=False)
        post.list_date=daily_date(item['text'],item['posted_at']);post.parser_version=0 if unresolved else VERSION
        post.extracted_urls=[d['mint_page_url'] for d in safe]
        db.add(post)
        await db.flush()
        for data in safe:
            import hashlib
            key=data.get('source_entry_key') or hashlib.sha256(data['mint_page_url'].encode()).hexdigest()
            previous=await db.scalar(select(Drop).where(Drop.source_post_id==post.id,or_(
                Drop.source_entry_key==key,Drop.source_entry_key.is_(None)&(Drop.mint_page_url==data['mint_page_url']))))
            if previous:
                previous.source_entry_key=key
                previous.source_price_text=data.get('source_price_text')
                previous.source_time_text=data.get('source_time_text')
                continue
            drop_id = f"x_{uuid.uuid4().hex[:12]}"
            db.add(Drop(id=drop_id, source_post_id=post.id,
                        name=data["name"][:150], chain=data["chain"],
                        chain_id=data["chain_id"], mint_page_url=data["mint_page_url"],
                        site_label=data["site_label"], icon_name=data["icon_name"],
                        status_label="Manual check", status_kind="manual",
                        is_supported_integration=False,
                        manual_notice=f"From @lakzonevn: {item['post_url']}. Check the official mint page and MetaMask before signing.",
                        is_demo=False,source_entry_key=key,
                        source_price_text=data.get('source_price_text'),source_time_text=data.get('source_time_text')))
            await db.flush()
            for index, stage in enumerate(data["stages"]):
                db.add(MintStage(id=f"{drop_id}_st_{index}", drop_id=drop_id, **stage))
            new_drops += 1
        await db.commit()  # Publish the newest list before resolving archived lists.
    source.status = "healthy"
    source.last_sync_at = datetime.now(timezone.utc)
    source.last_error = None
    source.consecutive_failures = 0
    await db.commit()
    return new_drops
