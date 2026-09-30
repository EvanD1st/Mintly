"""Import real OpenSea drop records without inferring eligibility or mint authority."""

import hashlib
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal

import aiohttp
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import Drop, MintStage, SourceConnection

logger = logging.getLogger("mintly.opensea_feed")
CHAINS = {"ethereum": ("Ethereum", 1), "base": ("Base", 8453)}
NATIVE_TOKEN = "0x0000000000000000000000000000000000000000"


def _stage_time(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clean_stage(stage: dict):
    start = _stage_time(stage.get("start_time"))
    if start is None:
        return None
    try:
        wei = int(stage.get("price") or "0")
        limit = int(stage.get("max_per_wallet") or 1)
    except (ValueError, TypeError):
        return None
    if wei < 0 or wei > 10**25 or limit < 1 or limit > 100000:
        return None
    native = (stage.get("price_currency_address") or "").lower() == NATIVE_TOKEN
    return {
        "id": str(stage.get("uuid") or hashlib.sha256(repr(stage).encode()).hexdigest()[:24]),
        "name": str(stage.get("label") or "Mint stage")[:50],
        "start": start,
        "end": _stage_time(stage.get("end_time")),
        "price_wei": wei if native else 0,
        "price_eth_str": format(Decimal(wei) / Decimal(10**18), "f") if native else "",
        "limit": limit,
        "eligibility": "manual_check" if stage.get("stage_type") != "public_sale" else "unknown",
    }


async def sync_opensea_drops(db) -> int:
    """Refresh source rows. A failed fetch leaves previous real rows, never samples."""
    source = (await db.execute(select(SourceConnection).where(
        SourceConnection.source_name == "opensea",
    ))).scalar_one_or_none()
    if source is None:
        source = SourceConnection(source_name="opensea", source_type="api", status="needs_attention",
                                  is_monitoring=True)
        db.add(source)
        await db.flush()
    if not source.is_monitoring:
        return 0
    if not settings.OPENSEA_API_KEY:
        source.status = "needs_attention"
        source.last_error = "OpenSea API key is not configured."
        await db.commit()
        return 0
    records = []
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        headers = {"x-api-key": settings.OPENSEA_API_KEY, "Accept": "application/json"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as client:
            for calendar in ("upcoming", "featured"):
                async with client.get("https://api.opensea.io/api/v2/drops", params={
                    "type": calendar, "limit": 30, "chains": "ethereum,base",
                }) as response:
                    response.raise_for_status()
                    payload = await response.json()
                    if not isinstance(payload.get("drops"), list):
                        raise ValueError("OpenSea response has no drops array")
                    records.extend(payload["drops"])
    except (aiohttp.ClientError, TimeoutError, ValueError) as error:
        logger.warning("OpenSea sync failed: %s", type(error).__name__)
        source.status = "error"
        source.last_error = f"OpenSea request failed ({type(error).__name__})."
        await db.commit()
        return 0

    added = 0
    now = datetime.now(timezone.utc)
    seen_ids: set[str] = set()
    for raw in records:
        slug = raw.get("collection_slug")
        chain = raw.get("chain")
        address = raw.get("contract_address")
        url = raw.get("opensea_url")
        if not isinstance(slug, str) or not slug or chain not in CHAINS:
            continue
        if not isinstance(url, str) or not url.startswith("https://opensea.io/collection/"):
            continue
        if not isinstance(address, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
            continue
        drop_id = "os_" + hashlib.sha256(f"{chain}:{slug}".encode()).hexdigest()[:28]
        if drop_id in seen_ids:
            continue
        seen_ids.add(drop_id)
        drop = (await db.execute(select(Drop).options(selectinload(Drop.stages)).where(
            Drop.id == drop_id,
        ))).scalar_one_or_none()
        if drop is None:
            drop = Drop(id=drop_id, is_demo=False)
            db.add(drop)
            added += 1
        stage_data = [_clean_stage(s) for s in (raw.get("active_stage"), raw.get("next_stage")) if isinstance(s, dict)]
        stages = [s for s in stage_data if s]
        drop.name = str(raw.get("collection_name") or slug)[:150]
        drop.chain, drop.chain_id = CHAINS[chain]
        drop.contract_address = address
        drop.mint_page_url = url
        drop.site_label = "OpenSea"
        drop.icon_name = "gem"
        drop.status_label = "Live on OpenSea" if raw.get("is_minting") else "Upcoming on OpenSea"
        drop.status_kind = "unknown"
        drop.is_supported_integration = False
        drop.manual_notice = "Live source data. Eligibility and transaction details must be confirmed in MetaMask and on OpenSea."
        drop.updated_at = now
        existing_stages = {stage.id: stage for stage in drop.stages}
        current_ids = set()
        for stage in stages:
            stage_id = f"{drop_id}_{stage['id'][:20]}"
            if stage_id in current_ids:
                continue
            current_ids.add(stage_id)
            row = existing_stages.get(stage_id)
            if row is None:
                row = MintStage(id=stage_id, drop=drop)
                db.add(row)
            row.stage_name = stage["name"]
            row.start_time_utc = stage["start"]
            row.end_time_utc = stage["end"]
            row.price_wei = stage["price_wei"]
            row.price_eth_str = stage["price_eth_str"]
            row.limit_per_wallet = stage["limit"]
            row.eligibility_status = stage["eligibility"]
        for stage_id, row in existing_stages.items():
            if stage_id not in current_ids:
                await db.delete(row)
    source.status = "healthy"
    source.last_error = None
    source.last_sync_at = now
    await db.commit()
    return added
