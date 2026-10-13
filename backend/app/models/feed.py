"""Owner-scoped display checks, never mint approvals."""
from datetime import datetime
from sqlalchemy import String,ForeignKey,JSON,DateTime,Integer
from sqlalchemy.orm import Mapped,mapped_column
from app.database import Base

class FeedWalletSelection(Base):
    __tablename__='feed_wallet_selections'
    user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
    wallet_id:Mapped[str]=mapped_column(ForeignKey('wallets.id'))

class FeedWalletCheck(Base):
    __tablename__='feed_wallet_checks'
    user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
    wallet_id:Mapped[str]=mapped_column(ForeignKey('wallets.id'),primary_key=True)
    drop_id:Mapped[str]=mapped_column(ForeignKey('drops.id'),primary_key=True)
    status:Mapped[str]=mapped_column(String(24),default='queued')
    result:Mapped[dict]=mapped_column(JSON,default=dict)
    checked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    expires_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    next_attempt_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    lease_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    attempts:Mapped[int]=mapped_column(Integer,default=0)
