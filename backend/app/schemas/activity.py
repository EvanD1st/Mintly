"""Pydantic schemas for Manual Import, Source Health, and Activity."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.drop import DropSchema


class ManualImportRequest(BaseModel):
    raw_content: str = Field(..., min_length=5)
    source_author: str = "lakzonevn"


class ManualImportResponse(BaseModel):
    post_id: str
    message: str
    parsed_drops_count: int
    drops: List[DropSchema]


class SourceStatusResponse(BaseModel):
    source_name: str
    status: str
    is_monitoring: bool
    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None
    drops_count: int
    summary_text: str


class ActivityEventSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    label: str
    detail: str
    icon_name: str
    is_demo: bool
    event_time: datetime
    formatted_time: str
