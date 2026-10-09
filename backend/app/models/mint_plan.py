"""Private, per-wallet OpenSea mint preparation; never a signing authorization."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MintPlan(Base):
    __tablename__ = "mint_plans"
    __table_args__ = (
        UniqueConstraint("wallet_id", "collection_slug", name="uq_mint_plan_wallet_slug"),
        Index("ix_mint_plans_next_check", "next_check_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    wallet_id: Mapped[str] = mapped_column(String(36), ForeignKey("wallets.id"), nullable=False, index=True)
    collection_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    eth_usdt_rate: Mapped[str | None] = mapped_column(String(40))
    rate_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collection_name: Mapped[str] = mapped_column(String(150), nullable=False)
    chain: Mapped[str] = mapped_column(String(20), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_address: Mapped[str] = mapped_column(String(42), nullable=False)
    opensea_url: Mapped[str] = mapped_column(Text, nullable=False)
    selected_stage: Mapped[dict | None] = mapped_column(JSON)
    stage_uuid: Mapped[str | None] = mapped_column(String(100))
    stage_name: Mapped[str | None] = mapped_column(String(80))
    stage_type: Mapped[str | None] = mapped_column(String(40))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price_wei: Mapped[int | None] = mapped_column(BigInteger)
    mint_value_wei: Mapped[int | None] = mapped_column(BigInteger)
    estimated_network_fee_wei: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="unverified")
    status_note: Mapped[str] = mapped_column(Text, nullable=False, default="Checking OpenSea drop")
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_stage_uuid: Mapped[str | None] = mapped_column(String(100))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    automatic_drop_id: Mapped[str | None] = mapped_column(String(64))
    automatic_stage_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                                                  onupdate=lambda: datetime.now(timezone.utc))


class MintPlanRecord(Base):
    """Append-only snapshots: editing or reimporting a plan cannot erase its record."""
    __tablename__ = 'mint_plan_records'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), index=True)
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey('mint_plans.id'), index=True)
    event: Mapped[str] = mapped_column(String(30))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
