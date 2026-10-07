"""SQLAlchemy models for Wallets and Address Book."""

import uuid
from datetime import datetime
from typing import List
from sqlalchemy import String, Boolean, JSON, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str] = mapped_column(String(42), nullable=False, index=True)
    # signing_capability: 'watch_only', 'interactive', 'isolated_server_signer', 'demo'
    signing_capability: Mapped[str] = mapped_column(String(30), default="watch_only", nullable=False)
    # Supported network names/IDs
    supported_chains: Mapped[list] = mapped_column(JSON, default=lambda: ["Ethereum", "Base", "Sepolia", "Base Sepolia"])
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
