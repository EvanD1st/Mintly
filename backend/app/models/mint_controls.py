"""Owner-scoped accounting, non-spending checks and notification state."""
from datetime import datetime
from sqlalchemy import String, ForeignKey, BigInteger, JSON, DateTime, Text, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class DailyDebit(Base):
    __tablename__ = 'daily_debits'
    task_id: Mapped[str] = mapped_column(ForeignKey('mint_tasks.id'), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    maximum_wei: Mapped[int] = mapped_column(BigInteger)
    actual_wei: Mapped[int | None] = mapped_column(BigInteger)


class CopyCheck(Base):
    __tablename__ = 'copy_checks'
    watch_id: Mapped[str] = mapped_column(ForeignKey('copy_watches.id'), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey('wallets.id'))
    version: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CopyCheckResult(Base):
    __tablename__ = 'copy_check_results'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    watch_id: Mapped[str] = mapped_column(ForeignKey('copy_watches.id'))
    wallet_id: Mapped[str] = mapped_column(ForeignKey('wallets.id'))
    event_id: Mapped[str] = mapped_column(ForeignKey('copy_events.id'))
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int | None] = mapped_column(Integer)
    estimated_fee_wei: Mapped[int | None] = mapped_column(BigInteger)


class WalletAlert(Base):
    __tablename__ = 'wallet_alerts'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey('wallets.id'))
    chain_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    fingerprint: Mapped[str] = mapped_column(String(64), default='')
    version: Mapped[int] = mapped_column(Integer, default=0)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(120), default='')
    detail: Mapped[str] = mapped_column(Text, default='')
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
