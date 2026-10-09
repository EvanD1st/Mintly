"""SQLAlchemy models for Drops and Mint Stages."""

import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Boolean, Integer, BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class DismissedDrop(Base):
    __tablename__ = 'dismissed_drops'
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), primary_key=True)
    drop_id: Mapped[str] = mapped_column(String(64), ForeignKey('drops.id'), primary_key=True)


class Drop(Base):
    __tablename__ = "drops"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_post_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("source_posts.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    chain: Mapped[str] = mapped_column(String(50), default="Base", nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, default=8453, nullable=False)
    contract_address: Mapped[Optional[str]] = mapped_column(String(42), nullable=True)
    mint_page_url: Mapped[str] = mapped_column(Text, nullable=False)
    site_label: Mapped[str] = mapped_column(String(50), default="Project website")
    icon_name: Mapped[str] = mapped_column(String(30), default="gem")
    
    # Drop-level summary status: 'eligible', 'manual', 'ineligible', 'unknown'
    status_label: Mapped[str] = mapped_column(String(50), default="Unverified")
    status_kind: Mapped[str] = mapped_column(String(20), default="unknown")
    
    # Verified execution support: True only if verified EVM SeaDrop contract exists
    is_supported_integration: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_notice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    stages: Mapped[List["MintStage"]] = relationship("MintStage", back_populates="drop", cascade="all, delete-orphan", lazy="selectin")


class MintStage(Base):
    __tablename__ = "mint_stages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    drop_id: Mapped[str] = mapped_column(String(64), ForeignKey("drops.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_name: Mapped[str] = mapped_column(String(50), nullable=False)  # 'Allowlist', 'Public', etc.
    start_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time_utc: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Exact financial storage in integer Wei
    price_wei: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    price_eth_str: Mapped[str] = mapped_column(String(30), default="0", nullable=False)
    limit_per_wallet: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    
    # Eligibility per stage
    # 'eligible', 'ineligible', 'unknown', 'manual_check'
    eligibility_status: Mapped[str] = mapped_column(String(30), default="unknown")
    eligibility_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    eligibility_wallet_address: Mapped[Optional[str]] = mapped_column(String(42), nullable=True)
    eligibility_evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    drop: Mapped["Drop"] = relationship("Drop", back_populates="stages")
