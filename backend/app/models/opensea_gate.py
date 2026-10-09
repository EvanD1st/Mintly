"""Shared request permits and provider cooldowns; no keys or wallet data."""
from datetime import datetime
from sqlalchemy import String,DateTime
from sqlalchemy.orm import Mapped,mapped_column
from app.database import Base

class OpenSeaRequestGate(Base):
    __tablename__='opensea_request_gates'
    name:Mapped[str]=mapped_column(String(24),primary_key=True)
    next_request_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    blocked_until:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
