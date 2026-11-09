"""Verified Auto-Arming opportunity evidence; never a mint authorization."""
from datetime import datetime
from sqlalchemy import String,ForeignKey,DateTime,Integer
from sqlalchemy.orm import Mapped,mapped_column
from app.database import Base


class MintOpportunity(Base):
    __tablename__='mint_opportunities'
    id:Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),index=True)
    wallet_id:Mapped[str]=mapped_column(ForeignKey('wallets.id'))
    drop_id:Mapped[str]=mapped_column(ForeignKey('drops.id'))
    chain_id:Mapped[int]=mapped_column(Integer)
    contract:Mapped[str]=mapped_column(String(42))
    phase_id:Mapped[str]=mapped_column(String(128))
    opens_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    closes_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    eligible_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    last_seen_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    last_error_code:Mapped[str|None]=mapped_column(String(40))
    last_error_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
