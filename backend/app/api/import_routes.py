"""Manual import endpoints for full drop lists or single mint links."""

import uuid
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, require_admin
from app.models import User
from app.models import SourcePost, Drop, MintStage, ActivityEvent
from app.schemas.activity import ManualImportRequest, ManualImportResponse
from app.services.parser import DropPostParser
from app.services.url_validator import validate_safe_url, fetch_safe_url, URLSecurityError
from app.services.notifier import NotificationService

router = APIRouter(prefix="/drops/import", tags=["import"])


@router.post("", response_model=ManualImportResponse)
async def import_drops_manually(
    req: ManualImportRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Manually imports a daily list post or single mint link."""
    content = req.raw_content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Import content cannot be empty.")

    # Check if content is a bare URL
    is_url = bool(re.match(r"^https?://[^\s]+$", content))
    fetched_urls = []
    
    if is_url:
        try:
            # Enforce SSRF protection
            safe_url = validate_safe_url(content)
            fetched_urls.append(safe_url)
            # A link alone is not evidence of a chain, price, time, or eligibility.
            if "opensea.io/collection/" in safe_url:
                slug = safe_url.rstrip("/").split("/")[-1]
                content = f"{slug.replace('-', ' ').title()}\nLink: {safe_url}"
            else:
                fetched_text = await fetch_safe_url(safe_url)
                content = f"Imported drop from {safe_url}\n{fetched_text[:500]}"
        except URLSecurityError as se:
            raise HTTPException(status_code=400, detail=f"Security check failed on imported URL: {str(se)}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch provided URL: {str(e)}")

    # Parse drops from content
    parsed = DropPostParser.parse(content, datetime.now(timezone.utc))
    if not parsed:
        if not is_url:
            raise HTTPException(status_code=400, detail="No mint link was found in the supplied text.")
        # Save a link for review without inventing market or stage metadata.
        parsed = [{
            "name": "Imported mint link",
            "chain": "Unknown",
            "chain_id": 0,
            "mint_page_url": content if is_url else "https://opensea.io",
            "site_label": "OpenSea" if is_url and "opensea.io" in content else "Project website",
            "icon_name": "gem",
            "status_label": "Manual check",
            "status_kind": "manual",
            "is_supported_integration": False,
            "manual_notice": "Imported without verified drop metadata; requires manual review.",
            "stages": []
        }]

    # Save SourcePost
    post_id = f"manual_{uuid.uuid4().hex[:12]}"
    post = SourcePost(
        post_id=post_id,
        author_username=req.source_author,
        full_text=req.raw_content,
        posted_at=datetime.now(timezone.utc),
        extracted_urls=fetched_urls,
        is_daily_list=len(parsed) > 1,
        is_manual_import=True,
    )
    db.add(post)
    await db.flush()

    saved_drops = []
    for item in parsed:
        try:
            item["mint_page_url"] = validate_safe_url(item["mint_page_url"])
        except URLSecurityError as error:
            raise HTTPException(status_code=400, detail=f"Unsafe mint link: {error}")
        drop_id = f"imp_{uuid.uuid4().hex[:8]}"
        drop = Drop(
            id=drop_id,
            source_post_id=post.id,
            name=item["name"],
            chain=item["chain"],
            chain_id=item["chain_id"],
            contract_address=item.get("contract_address"),
            mint_page_url=item["mint_page_url"],
            site_label=item["site_label"],
            icon_name=item["icon_name"],
            status_label=item["status_label"],
            status_kind=item["status_kind"],
            is_supported_integration=item["is_supported_integration"],
            manual_notice=item.get("manual_notice"),
            is_demo=False,
        )
        db.add(drop)
        await db.flush()

        for s_idx, s in enumerate(item["stages"]):
            stage = MintStage(
                id=f"{drop_id}_st_{s_idx}",
                drop_id=drop.id,
                stage_name=s["stage_name"],
                start_time_utc=s["start_time_utc"],
                price_wei=s["price_wei"],
                price_eth_str=s["price_eth_str"],
                limit_per_wallet=s.get("limit_per_wallet", 1),
                eligibility_status=s["eligibility_status"],
            )
            db.add(stage)
        
        saved_drops.append(drop)

    # Activity and Notification
    db.add(ActivityEvent(
        event_type="discovery",
        label="Manual list imported",
        detail=f"Imported {len(saved_drops)} drops from {req.source_author}",
        icon_name="download",
        is_demo=False,
    ))
    await db.commit()

    # Dispatch notification
    await NotificationService.send_notification(
        title="New Drops Imported",
        body=f"Imported {len(saved_drops)} new drops for review.",
        category="daily_list",
        deep_link="mintly://drops",
    )

    # Re-fetch drops with stages
    from sqlalchemy import select
    res = await db.execute(
        select(Drop).options(selectinload(Drop.stages)).where(Drop.source_post_id == post.id)
    )
    all_imported = res.scalars().all()

    return ManualImportResponse(
        post_id=post_id,
        message=f"Successfully imported {len(all_imported)} drops.",
        parsed_drops_count=len(all_imported),
        drops=all_imported,
    )
