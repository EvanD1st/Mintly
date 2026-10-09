"""Deterministic parser for @lakzonevn daily NFT drop posts."""

import re
from datetime import datetime, time, timezone, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo

LAGOS_TZ = ZoneInfo("Africa/Lagos")


def parse_eth_to_wei(amount_str: str) -> int:
    """Safely converts an ETH string to exact integer Wei without floating point error."""
    clean = amount_str.strip().lower().replace("eth", "").replace("$", "").strip()
    if clean in ("free", "0", "0.0", "0.00"):
        return 0
    dec = Decimal(clean)
    wei = int(dec * Decimal(10**18))
    return wei


def format_wei_to_eth(wei: int) -> str:
    """Formats exact integer Wei to a clean ETH string."""
    if wei == 0:
        return "0"
    dec = Decimal(wei) / Decimal(10**18)
    formatted = f"{dec:.18f}".rstrip("0").rstrip(".")
    return formatted if formatted else "0"


class DropPostParser:
    """Parses raw text posts from @lakzonevn into structured Drop and Stage records."""

    @classmethod
    def parse_time_wat(cls, time_str: str, base_date: Optional[datetime] = None) -> Optional[datetime]:
        """Parses a time string in WAT (UTC+1) and returns a UTC datetime."""
        if not base_date:
            base_date = datetime.now(LAGOS_TZ)
        else:
            base_date = base_date.astimezone(LAGOS_TZ)

        clean = time_str.strip().upper().replace("WAT", "").replace("UTC+1", "").strip()

        # Try 12-hour first: 7:30 PM, 6 PM, 6:30 PM
        m12 = re.search(r"(\b[0-1]?[0-9])(?::([0-5][0-9]))?\s*(AM|PM)\b", clean)
        if m12:
            hour = int(m12.group(1))
            minute = int(m12.group(2)) if m12.group(2) else 0
            meridiem = m12.group(3)
            if meridiem == "PM" and hour < 12:
                hour += 12
            elif meridiem == "AM" and hour == 12:
                hour = 0
            dt_lagos = datetime(
                year=base_date.year,
                month=base_date.month,
                day=base_date.day,
                hour=hour,
                minute=minute,
                tzinfo=LAGOS_TZ
            )
            return dt_lagos.astimezone(timezone.utc)

        # Try HH:MM (24-hour)
        m24 = re.search(r"(\b[0-2]?[0-9]):([0-5][0-9])\b", clean)
        if m24:
            hour = int(m24.group(1))
            minute = int(m24.group(2))
            if hour > 23:
                return None
            dt_lagos = datetime(
                year=base_date.year,
                month=base_date.month,
                day=base_date.day,
                hour=hour,
                minute=minute,
                tzinfo=LAGOS_TZ
            )
            return dt_lagos.astimezone(timezone.utc)

        return None

    @classmethod
    def parse(cls, post_text: str, posted_at: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Parses full post text into a list of structured drop dictionaries."""
        if not posted_at:
            posted_at = datetime.now(timezone.utc)

        # Check if this post is a correction or daily list
        is_daily_list = any(kw in post_text.lower() for kw in ["daily", "drops", "today's drops", "mint list", "mints"])
        
        # Split text into sections by numbered list or double line breaks
        # Pattern like "1. ", "1)", "[1]" or separated blocks
        items = re.split(r"(?:\n\s*(?:[0-9]+[\.\)]|#\d+)\s+|\n\s*---\s*\n)", post_text)
        
        drops = []
        for section in items:
            section = section.strip()
            if not section or len(section) < 15:
                continue

            # Check if this section contains project details
            name_match = re.search(r"^(?:[0-9]+[\.\)]\s*)?([^\n\r]+)", section)
            if not name_match:
                continue

            raw_name = name_match.group(1).strip()
            # Skip header lines like "Daily Mint Drops"
            if any(h in raw_name.lower() for h in ["daily mint drops", "today's drops", "shortlist", "thread"]):
                continue

            # Extract Chain
            chain = "Unknown"
            chain_match = re.search(r"(?:chain|network):\s*([a-zA-Z0-9\s]+)", section, re.IGNORECASE)
            if chain_match:
                c_str = chain_match.group(1).strip().split()[0].capitalize()
                if "Eth" in c_str or "Mainnet" in c_str:
                    chain = "Ethereum"
                elif "Base" in c_str:
                    chain = "Base"
                elif "Sepolia" in c_str:
                    chain = "Sepolia"
                else:
                    chain = c_str
            else:
                # Guess from text keywords if explicitly mentioned
                if "ethereum" in section.lower() or " eth " in section.lower():
                    chain = "Ethereum"
                elif "base" in section.lower():
                    chain = "Base"

            chain_id = 8453 if chain == "Base" else (1 if chain == "Ethereum" else 0)

            # Extract URLs
            urls = re.findall(r"https?://[^\s<>\"']+", section)
            mint_url = urls[0] if urls else ""
            if not mint_url:
                continue
            site_label = "OpenSea" if "opensea.io" in mint_url.lower() else "Project website"

            # Extract Time
            time_match = re.search(r"(?:time|starts?|at):\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:AM|PM|WAT)?)", section, re.IGNORECASE)
            parsed_utc = cls.parse_time_wat(time_match.group(1), posted_at) if time_match else None

            # Extract Stages and Prices
            # Look for Allowlist / Presale / Public
            stages = []
            
            # Check for multiple stage lines
            # Example: "WL: 0.0002 ETH (18:00 WAT)" / "Public: 0.0004 ETH (20:00 WAT)"
            wl_match = re.search(r"(?:wl|presale|allowlist):\s*([0-9\.]+|free)\s*(?:eth)?(?:\s*\(([^\)]+)\))?", section, re.IGNORECASE)
            pub_match = re.search(r"(?:public|pub):\s*([0-9\.]+|free)\s*(?:eth)?(?:\s*\(([^\)]+)\))?", section, re.IGNORECASE)
            
            if wl_match or pub_match:
                if wl_match:
                    wl_price_str = wl_match.group(1)
                    wl_time_sub = wl_match.group(2)
                    wl_utc = cls.parse_time_wat(wl_time_sub, posted_at) if wl_time_sub else parsed_utc
                    wl_wei = parse_eth_to_wei(wl_price_str)
                    if wl_utc:
                        stages.append({
                        "stage_name": "Allowlist",
                        "start_time_utc": wl_utc,
                        "price_wei": wl_wei,
                        "price_eth_str": format_wei_to_eth(wl_wei),
                        "limit_per_wallet": 0,
                        "eligibility_status": "unknown",
                        })
                if pub_match:
                    pub_price_str = pub_match.group(1)
                    pub_time_sub = pub_match.group(2)
                    pub_utc = cls.parse_time_wat(pub_time_sub, posted_at) if pub_time_sub else parsed_utc
                    pub_wei = parse_eth_to_wei(pub_price_str)
                    if pub_utc:
                        stages.append({
                        "stage_name": "Public",
                        "start_time_utc": pub_utc,
                        "price_wei": pub_wei,
                        "price_eth_str": format_wei_to_eth(pub_wei),
                        "limit_per_wallet": 0,
                        "eligibility_status": "unknown",
                        })
            else:
                # Single price pattern: "Price: 0.0008 ETH"
                price_match = re.search(r"(?:price|mint):\s*([0-9\.]+|free|tba)\s*(?:eth)?", section, re.IGNORECASE)
                price_str = price_match.group(1) if price_match else None
                if price_str is None or parsed_utc is None:
                    price_str = None
                if price_str is None:
                    price_wei = None
                    price_display = ""
                elif price_str.lower() == "tba":
                    price_wei = 0
                    price_display = "TBA"
                else:
                    price_wei = parse_eth_to_wei(price_str)
                    price_display = format_wei_to_eth(price_wei)

                if price_wei is not None:
                    stages.append({
                    "stage_name": "Public",
                    "start_time_utc": parsed_utc,
                    "price_wei": price_wei,
                    "price_eth_str": price_display,
                    "limit_per_wallet": 0,
                    "eligibility_status": "unknown",
                    })

            # Determine icon based on name
            icon = "gem"
            name_lower = raw_name.lower()
            if "bloom" in name_lower or "flower" in name_lower:
                icon = "flower-2"
            elif "moon" in name_lower or "night" in name_lower or "club" in name_lower:
                icon = "moon-star"
            elif "planet" in name_lower or "orbit" in name_lower:
                icon = "gem"

            # Determine integration support
            # A URL in a post is not proof of a SeaDrop integration or wallet eligibility.
            is_supported = False
            status_kind = "manual"
            status_label = "Manual check"

            drops.append({
                "name": raw_name,
                "chain": chain,
                "chain_id": chain_id,
                "mint_page_url": mint_url,
                "site_label": site_label,
                "icon_name": icon,
                "status_label": status_label,
                "status_kind": status_kind,
                "is_supported_integration": is_supported,
                "manual_notice": "Imported post has not been verified against contract metadata.",
                "stages": stages,
            })

        return drops
