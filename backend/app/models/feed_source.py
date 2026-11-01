"""Raw source revisions, canonical collection mentions and account read state."""
from datetime import datetime
from sqlalchemy import String, ForeignKey, Text, JSON, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SourceRevision(Base):
    __tablename__ = 'source_revisions'
    post_id: Mapped[str] = mapped_column(ForeignKey('source_posts.id'), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    raw_text: Mapped[str] = mapped_column(Text)
    expanded_text: Mapped[str] = mapped_column(Text)


class FeedMention(Base):
    __tablename__ = 'feed_mentions'
    post_id: Mapped[str] = mapped_column(ForeignKey('source_posts.id'), primary_key=True)
    entry_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    drop_id: Mapped[str] = mapped_column(ForeignKey('drops.id'), index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class FeedSeen(Base):
    __tablename__ = 'feed_seen'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    post_id: Mapped[str] = mapped_column(ForeignKey('source_posts.id'), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))


class SourceAlert(Base):
    __tablename__ = 'source_alerts'
    id: Mapped[str] = mapped_column(String(64),primary_key=True)
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24),default='pending')
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
