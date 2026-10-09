"""Public wallet observations and finite, explicitly approved copying rules."""
import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, JSON, DateTime, Integer, BigInteger, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class CopyWatch(Base):
    __tablename__ = 'copy_watches'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    address: Mapped[str] = mapped_column(String(42))
    label: Mapped[str] = mapped_column(String(80))
    chains: Mapped[list] = mapped_column(JSON)
    cursors: Mapped[dict] = mapped_column(JSON, default=dict)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CopyRule(Base):
    __tablename__ = 'copy_rules'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    watch_id: Mapped[str] = mapped_column(ForeignKey('copy_watches.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey('automatic_grants.id'))
    chain_id: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    context_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default='registering')
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resume_after_block: Mapped[int] = mapped_column(BigInteger)
    budget_wei: Mapped[int] = mapped_column(BigInteger)
    reserved_wei: Mapped[int] = mapped_column(BigInteger, default=0)
    spent_wei: Mapped[int] = mapped_column(BigInteger, default=0)


class CopyEvent(Base):
    __tablename__ = 'copy_events'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    watch_id: Mapped[str] = mapped_column(ForeignKey('copy_watches.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    observation: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default='detected')
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey('mint_tasks.id'), nullable=True, unique=True)
