"""SQLAlchemy models for Mint Authorizations and Queue Tasks."""

import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, Integer, BigInteger, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class MintAuthorization(Base):
    __tablename__ = "mint_authorizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    wallet_id: Mapped[str] = mapped_column(String(36), ForeignKey("wallets.id"), nullable=False)
    drop_id: Mapped[str] = mapped_column(String(64), ForeignKey("drops.id"), nullable=False)
    stage_id: Mapped[str] = mapped_column(String(64), ForeignKey("mint_stages.id"), nullable=False)
    
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Exact integer caps in Wei
    max_price_per_token_wei: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_fee_wei: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_spend_cap_wei: Mapped[int] = mapped_column(BigInteger, nullable=False)
    
    # Recipient address (must equal authorized wallet or explicitly approved recipient)
    recipient_address: Mapped[str] = mapped_column(String(42), nullable=False)
    user_consent_text: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class MintTask(Base):
    __tablename__ = "mint_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    authorization_id: Mapped[str] = mapped_column(String(36), ForeignKey("mint_authorizations.id"), nullable=False)
    wallet_id: Mapped[str] = mapped_column(String(36), ForeignKey("wallets.id"), nullable=False)
    drop_id: Mapped[str] = mapped_column(String(64), ForeignKey("drops.id"), nullable=False)
    stage_id: Mapped[str] = mapped_column(String(64), ForeignKey("mint_stages.id"), nullable=False)
    
    # Task status: 'armed', 'preparing', 'submitting', 'submitted', 'confirmed', 'failed', 'expired', 'disarmed'
    status: Mapped[str] = mapped_column(String(30), default="armed", index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    
    # Timing
    scheduled_for_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    # Worker lease coordination
    worker_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Nonce coordination
    assigned_nonce: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Transaction lifecycle
    prepared_calldata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signed_tx_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transaction_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True, index=True)
    broadcast_attempts: Mapped[int] = mapped_column(Integer, default=0)
    
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    block_number: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    
    # Exact accounting
    actual_gas_used: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    actual_effective_gas_price: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    actual_total_cost_wei: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explorer_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
