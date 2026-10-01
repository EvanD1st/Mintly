import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class MintPermission(Base):
    __tablename__ = 'mint_permissions'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36),ForeignKey('users.id'),index=True)
    plan_id: Mapped[str] = mapped_column(String(36),ForeignKey('mint_plans.id'),index=True)
    code_hash: Mapped[str] = mapped_column(String(64),unique=True,index=True)
    typed_data: Mapped[dict] = mapped_column(JSON)
    execution: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30),default='awaiting_signature',index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    execute_after: Mapped[datetime] = mapped_column(DateTime(timezone=True),index=True)
    signature_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tx_hash: Mapped[str | None] = mapped_column(String(66))
    raw_transaction: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text,default='Awaiting MetaMask permission signature.')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
