"""Tests for @lakzonevn post parser, WAT time conversion, and exact integer math."""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.services.parser import DropPostParser, parse_eth_to_wei, format_wei_to_eth


def test_integer_wei_conversion_accuracy():
    """Verifies that ETH strings are converted to integer Wei without float inaccuracies."""
    # 0.0002 ETH is exactly 200,000,000,000,000 Wei
    assert parse_eth_to_wei("0.0002") == 200_000_000_000_000
    assert parse_eth_to_wei("0.0008") == 800_000_000_000_000
    assert parse_eth_to_wei("0.000000000000000001") == 1  # 1 Wei
    assert parse_eth_to_wei("1.5 ETH") == 1_500_000_000_000_000_000
    assert parse_eth_to_wei("Free") == 0
    assert parse_eth_to_wei("0") == 0

    assert format_wei_to_eth(200_000_000_000_000) == "0.0002"
    assert format_wei_to_eth(0) == "0"


def test_wat_time_parsing():
    """Verifies that Lagos time (WAT, UTC+1) is accurately converted to UTC."""
    base_date = datetime(2026, 9, 29, 12, 0, tzinfo=ZoneInfo("Africa/Lagos"))
    
    # 18:00 WAT should be 17:00 UTC
    utc_time = DropPostParser.parse_time_wat("18:00 WAT", base_date)
    assert utc_time is not None
    assert utc_time.hour == 17
    assert utc_time.minute == 0
    assert utc_time.tzinfo == timezone.utc

    # 19:30 PM WAT should be 18:30 UTC
    utc_12hr = DropPostParser.parse_time_wat("7:30 PM", base_date)
    assert utc_12hr is not None
    assert utc_12hr.hour == 18
    assert utc_12hr.minute == 30


def test_daily_list_parsing_full():
    """Verifies parsing of a multi-drop daily post."""
    post_text = """
    Daily Mint Drops - September 29
    
    1. Orbit Bloom
    Chain: Base
    Time: 18:00 WAT
    WL: 0.0002 ETH (18:00 WAT)
    Public: 0.0004 ETH (20:00 WAT)
    Link: https://opensea.io/collection/orbit-bloom

    2. Paper Planets
    Chain: ETH
    Time: 19:00 WAT
    Price: 0.0008 ETH
    Link: https://opensea.io/collection/paper-planets

    3. Midnight Club
    Chain: Base
    Time: 20:00 WAT
    Price: 0.0004 ETH
    Link: https://midnightclub.xyz/mint
    """
    
    posted_at = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)
    drops = DropPostParser.parse(post_text, posted_at)
    
    assert len(drops) == 3

    # Check Drop 1 (Orbit Bloom)
    d1 = drops[0]
    assert d1["name"] == "Orbit Bloom"
    assert d1["chain"] == "Base"
    assert d1["chain_id"] == 8453
    assert d1["is_supported_integration"] is False
    assert d1["status_kind"] == "manual"
    assert len(d1["stages"]) == 2
    assert d1["stages"][0]["stage_name"] == "Allowlist"
    assert d1["stages"][0]["price_wei"] == 200_000_000_000_000
    assert d1["stages"][0]["eligibility_status"] == "unknown"
    assert d1["stages"][1]["stage_name"] == "Public"

    # Check Drop 2 (Paper Planets)
    d2 = drops[1]
    assert d2["name"] == "Paper Planets"
    assert d2["chain"] == "Ethereum"
    assert d2["chain_id"] == 1
    assert d2["is_supported_integration"] is False
    assert d2["stages"][0]["price_wei"] == 800_000_000_000_000

    # Check Drop 3 (Midnight Club - independent site)
    d3 = drops[2]
    assert d3["name"] == "Midnight Club"
    assert d3["is_supported_integration"] is False
    assert d3["status_kind"] == "manual"
    assert "verified" in d3["manual_notice"].lower()
