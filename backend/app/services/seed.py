"""Seed initial reference data for Mintly."""

from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Wallet, Drop, MintStage, ActivityEvent, SourceConnection
from app.services.parser import parse_eth_to_wei, format_wei_to_eth
from app.services.signer.base import SEADROP_V1_ADDRESS


async def seed_initial_data(session: AsyncSession):
    """Seeds Jenny's default wallet, initial demo drops matching reference, and source status."""
    # 1. Check if wallet exists
    w_stmt = select(Wallet).where(Wallet.label == "Jenny's wallet")
    existing_wallet = (await session.execute(w_stmt)).scalar_one_or_none()
    if not existing_wallet:
        jenny_wallet = Wallet(
            label="Jenny's wallet",
            address="0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
            signing_capability="demo",
            supported_chains=["Ethereum", "Base", "Sepolia", "Base Sepolia"],
            is_default=True,
            is_demo=True,
        )
        session.add(jenny_wallet)

    # 2. Check if source connection exists
    src_stmt = select(SourceConnection).where(SourceConnection.source_name == "lakzonevn")
    existing_src = (await session.execute(src_stmt)).scalar_one_or_none()
    if not existing_src:
        src = SourceConnection(
            source_name="lakzonevn",
            source_type="twikit",
            status="healthy",
            last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=15),
            is_monitoring=True,
        )
        session.add(src)

    # 3. Check if drops exist
    d_stmt = select(Drop)
    drops = (await session.execute(d_stmt)).scalars().all()
    if not drops:
        now = datetime.now(timezone.utc)
        today_18 = now.replace(hour=17, minute=0, second=0, microsecond=0)  # 18:00 WAT is 17:00 UTC
        today_19 = now.replace(hour=18, minute=0, second=0, microsecond=0)
        today_20 = now.replace(hour=19, minute=0, second=0, microsecond=0)

        # Drop 1: Orbit Bloom
        orbit_wei = parse_eth_to_wei("0.0002")
        orbit = Drop(
            id="orbit",
            name="Orbit Bloom",
            chain="Base",
            chain_id=8453,
            contract_address="0x1234567890123456789012345678901234567890",
            mint_page_url="https://opensea.io/collection/orbit-bloom",
            site_label="OpenSea",
            icon_name="flower-2",
            status_label="Presale eligible",
            status_kind="eligible",
            is_supported_integration=True,
            is_demo=True,
        )
        session.add(orbit)
        session.add(MintStage(
            id="orbit-wl",
            drop_id="orbit",
            stage_name="Allowlist",
            start_time_utc=today_18,
            price_wei=orbit_wei,
            price_eth_str="0.0002",
            limit_per_wallet=3,
            eligibility_status="eligible",
            eligibility_checked_at=now,
            eligibility_evidence="Allowlist tier 1 verified for Jenny's wallet.",
        ))
        session.add(MintStage(
            id="orbit-pub",
            drop_id="orbit",
            stage_name="Public",
            start_time_utc=today_20,
            price_wei=parse_eth_to_wei("0.0004"),
            price_eth_str="0.0004",
            limit_per_wallet=5,
            eligibility_status="eligible",
            eligibility_checked_at=now,
            eligibility_evidence="Public mint open to all.",
        ))

        # Drop 2: Paper Planets
        paper_wei = parse_eth_to_wei("0.0008")
        paper = Drop(
            id="paper",
            name="Paper Planets",
            chain="Ethereum",
            chain_id=1,
            contract_address="0x2345678901234567890123456789012345678901",
            mint_page_url="https://opensea.io/collection/paper-planets",
            site_label="OpenSea",
            icon_name="gem",
            status_label="Public stage",
            status_kind="eligible",
            is_supported_integration=True,
            is_demo=True,
        )
        session.add(paper)
        session.add(MintStage(
            id="paper-pub",
            drop_id="paper",
            stage_name="Public",
            start_time_utc=today_19,
            price_wei=paper_wei,
            price_eth_str="0.0008",
            limit_per_wallet=5,
            eligibility_status="eligible",
            eligibility_checked_at=now,
            eligibility_evidence="Public stage active.",
        ))

        # Drop 3: Midnight Club
        midnight_wei = parse_eth_to_wei("0.0004")
        midnight = Drop(
            id="midnight",
            name="Midnight Club",
            chain="Base",
            chain_id=8453,
            contract_address=None,
            mint_page_url="https://midnightclub.xyz/mint",
            site_label="Project website",
            icon_name="moon-star",
            status_label="Manual check",
            status_kind="manual",
            is_supported_integration=False,
            manual_notice="This project's eligibility checker isn't supported yet.",
            is_demo=True,
        )
        session.add(midnight)
        session.add(MintStage(
            id="midnight-unverified",
            drop_id="midnight",
            stage_name="Unverified",
            start_time_utc=today_20,
            price_wei=midnight_wei,
            price_eth_str="0.0004",
            limit_per_wallet=1,
            eligibility_status="manual_check",
            eligibility_checked_at=now,
            eligibility_evidence="Independent contract: requires manual review.",
        ))

        # Initial Activity Events
        session.add(ActivityEvent(
            event_type="scan",
            label="Eligibility scan complete",
            detail="2 drops eligible · 1 needs manual review",
            icon_name="shield-check",
            is_demo=True,
        ))
        session.add(ActivityEvent(
            event_type="discovery",
            label="Daily list imported",
            detail="LAKZONE · 3 sample drops",
            icon_name="download",
            is_demo=True,
        ))

    await session.commit()
