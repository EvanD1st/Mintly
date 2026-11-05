"""A finite standing approval for free drops; separate from watched-wallet copying."""
from datetime import datetime
from sqlalchemy import String,ForeignKey,JSON,DateTime,Text
from sqlalchemy.orm import Mapped,mapped_column
from app.database import Base


class FeedMintApproval(Base):
    __tablename__='feed_mint_approvals'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),index=True)
    wallet_id:Mapped[str]=mapped_column(ForeignKey('wallets.id'),index=True)
    grant_id:Mapped[str]=mapped_column(ForeignKey('automatic_grants.id'))
    status:Mapped[str]=mapped_column(String(24),default='registering')
    snapshot:Mapped[dict]=mapped_column(JSON)
    context_hash:Mapped[str]=mapped_column(String(64))
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    last_checked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    note:Mapped[str|None]=mapped_column(Text)
