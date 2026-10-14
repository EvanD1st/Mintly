"""Durable daily-list delivery, scoped to the registered account and device."""
from datetime import datetime, date
from sqlalchemy import String, ForeignKey, Date, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class DailyListNotice(Base):
    __tablename__ = 'daily_list_notices'
    __table_args__ = (UniqueConstraint('list_date','device_id','user_id',name='uq_daily_notice_owner_device'),)
    id: Mapped[str] = mapped_column(String(64),primary_key=True)
    list_date: Mapped[date] = mapped_column(Date,index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey('notification_devices.id'))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    source_post_id: Mapped[str] = mapped_column(ForeignKey('source_posts.id'))
    status: Mapped[str] = mapped_column(String(24),default='pending')
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
