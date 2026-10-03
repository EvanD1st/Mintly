"""Explicit custodial policies and durable submission coordination. No private keys."""
import uuid
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AutomaticGrant(Base):
    __tablename__ = 'automatic_grants'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey('wallets.id'), index=True)
    adapter: Mapped[str] = mapped_column(String(40), default='custodial_v1')
    chain_id: Mapped[int] = mapped_column(Integer)
    account: Mapped[str] = mapped_column(String(42))
    # SHA256 of the independently provisioned signer policy file.
    context_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scope: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default='enabled')
    budget_wei: Mapped[int] = mapped_column(BigInteger)
    reserved_wei: Mapped[int] = mapped_column(BigInteger, default=0)
    spent_wei: Mapped[int] = mapped_column(BigInteger, default=0)


class AutomaticNonce(Base):
    __tablename__ = 'automatic_nonces'
    __table_args__ = (UniqueConstraint('chain_id', 'address', 'nonce', name='uq_automatic_nonce'),)
    task_id: Mapped[str] = mapped_column(ForeignKey('mint_tasks.id'), primary_key=True)
    chain_id: Mapped[int] = mapped_column(Integer)
    address: Mapped[str] = mapped_column(String(42))
    nonce: Mapped[int] = mapped_column(BigInteger)


class AutomaticLock(Base):
    __tablename__ = 'automatic_locks'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
