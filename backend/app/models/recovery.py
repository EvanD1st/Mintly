"""One explicitly authorized same-nonce recovery per automatic task."""
from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, JSON, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class MintRecovery(Base):
    __tablename__ = 'mint_recoveries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey('mint_tasks.id'), unique=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), index=True)
    authorization_reference: Mapped[str] = mapped_column(String(200))
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_ceiling: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    previous_hash: Mapped[str] = mapped_column(String(66))
    previous_signed_tx_raw: Mapped[str] = mapped_column(Text)
    replacement_hash: Mapped[str | None] = mapped_column(String(66))
    replacement_signed_tx_raw: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default='approved')
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
