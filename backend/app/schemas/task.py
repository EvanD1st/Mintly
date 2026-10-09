"""Pydantic schemas for Tasks and Authorizations."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.drop import DropSchema, MintStageSchema


class DraftTaskRequest(BaseModel):
    plan_id: str | None = None
    copy_event_id: str | None = Field(default=None, min_length=64, max_length=64)
    wallet_id: str
    drop_id: str
    stage_id: str
    quantity: int = Field(..., ge=1, le=100, strict=True)
    fee_cap_eth: str = Field(..., pattern=r"^[0-9]+(\.[0-9]+)?$")
    grant_id: str | None = None
    mint_kind: str = Field(default='public', pattern='^(public|allowlist|signed)$')
    price_cap_eth: str | None = Field(default=None, pattern=r'^[0-9]+(\.[0-9]+)?$')
    total_cap_eth: str | None = Field(default=None, pattern=r'^[0-9]+(\.[0-9]+)?$')
    expires_at: datetime | None = None
    scheduled_for_utc: datetime | None = None
    conditional_eligibility: bool = False
    onchain_stage_index: int | None = Field(default=None, ge=1, strict=True)


class DraftTaskResponse(BaseModel):
    drop: DropSchema
    stage: MintStageSchema
    wallet_label: str
    wallet_address: str
    chain: str
    quantity: int
    mint_price_each_eth: str
    fee_cap_eth: str
    total_spend_cap_eth: str
    total_spend_cap_wei: int
    is_signer_ready: bool
    signer_status_note: str


class ArmTaskRequest(DraftTaskRequest):
    review_hash: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    user_consent_confirmed: bool = Field(...)
    idempotency_key: str = Field(..., min_length=8, max_length=128)


class TaskSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    wallet_id: str
    drop_id: str
    stage_id: str
    status: str
    is_demo: bool
    scheduled_for_utc: datetime
    expires_at_utc: datetime
    
    quantity: int
    unit_price_eth: str
    fee_cap_eth: str
    total_cap_eth: str
    
    drop_name: str
    chain: str
    stage_name: str
    time_wat_label: str
    icon_name: str
    
    transaction_hash: Optional[str] = None
    explorer_url: Optional[str] = None
    failure_reason: Optional[str] = None
    submitted_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    actual_total_cost_wei: Optional[int] = None
    execution_mode: Optional[str] = None
    wallet_address: Optional[str] = None
    progress: dict | None = None


class QueueResponse(BaseModel):
    tasks: List[TaskSchema]
    total_count: int
