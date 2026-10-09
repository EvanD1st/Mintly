"""Explicit eligibility-only consent; credentials never live in the API database."""
from datetime import datetime
from sqlalchemy import String,ForeignKey,Integer,Boolean,DateTime,JSON
from sqlalchemy.orm import Mapped,mapped_column
from app.database import Base

class OpenSeaAccess(Base):
    __tablename__='opensea_access'
    wallet_id:Mapped[str]=mapped_column(ForeignKey('wallets.id'),primary_key=True)
    user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),index=True)
    revision:Mapped[int]=mapped_column(Integer,default=0)
    enabled:Mapped[bool]=mapped_column(Boolean,default=False)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    terms_version:Mapped[str]=mapped_column(String(64))
    status:Mapped[str]=mapped_column(String(24),default='registering')
    consented_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
