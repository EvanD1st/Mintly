"""SQLAlchemy models for X/Twikit sources and raw posts."""

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, Integer, DateTime, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SourceConnection(Base):
    __tablename__ = "source_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_name: Mapped[str] = mapped_column(String(50), default="lakzonevn", unique=True)
    source_type: Mapped[str] = mapped_column(String(20), default="twikit")
    # 'healthy', 'needs_attention', 'monitoring_paused', 'error'
    status: Mapped[str] = mapped_column(String(30), default="healthy")
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    is_monitoring: Mapped[bool] = mapped_column(Boolean, default=True)


class SourcePost(Base):
    __tablename__ = "source_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    post_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    author_username: Mapped[str] = mapped_column(String(50), default="lakzonevn")
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extracted_urls: Mapped[list] = mapped_column(JSON, default=list)
    is_daily_list: Mapped[bool] = mapped_column(Boolean, default=True)
    is_correction: Mapped[bool] = mapped_column(Boolean, default=False)
    replaces_post_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_manual_import: Mapped[bool] = mapped_column(Boolean, default=False)
