"""Persistent sanitized preparation/preflight history, independent of task notes."""
import uuid
from datetime import datetime
from sqlalchemy import String,Integer,DateTime,ForeignKey,JSON
from sqlalchemy.orm import Mapped,mapped_column
from app.database import Base

class MintAttemptDiagnostic(Base):
    __tablename__='mint_attempt_diagnostics'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    task_id:Mapped[str]=mapped_column(String(36),ForeignKey('mint_tasks.id',ondelete='CASCADE'),nullable=False,index=True)
    phase:Mapped[str]=mapped_column(String(20),nullable=False)
    attempt_number:Mapped[int|None]=mapped_column(Integer)
    started_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    finished_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    outcome:Mapped[str]=mapped_column(String(40),nullable=False)
    signer_http_status:Mapped[int|None]=mapped_column(Integer)
    error_category:Mapped[str]=mapped_column(String(40),nullable=False)
    upstream_events:Mapped[list]=mapped_column(JSON,nullable=False)
    next_retry_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
