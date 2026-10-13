"""Revocable remembered device families; credentials are stored only as digests."""
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class DeviceSession(Base):
    __tablename__='device_sessions'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),index=True)
    origin:Mapped[str]=mapped_column(String(250))
    token_hash:Mapped[str]=mapped_column(String(64),unique=True)
    generation:Mapped[int]=mapped_column(Integer,default=0)
    last_used_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    revoked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    last_request_hash:Mapped[str|None]=mapped_column(String(64))
    rotated_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    access_expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))

class DeviceRefreshUse(Base):
    __tablename__='device_refresh_uses'
    token_hash:Mapped[str]=mapped_column(String(64),primary_key=True)
    family_id:Mapped[str]=mapped_column(ForeignKey('device_sessions.id'),index=True)
    generation:Mapped[int]=mapped_column(Integer)
    used_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
