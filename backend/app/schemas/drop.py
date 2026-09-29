"""Pydantic schemas for Drops and Mint Stages."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class MintStageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    drop_id: str
    stage_name: str
    start_time_utc: datetime
    end_time_utc: Optional[datetime] = None
    price_wei: int
    price_eth_str: str
    limit_per_wallet: int
    eligibility_status: str
    eligibility_checked_at: Optional[datetime] = None
    eligibility_wallet_address: Optional[str] = None
    eligibility_evidence: Optional[str] = None


class DropSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    chain: str
    chain_id: int
    contract_address: Optional[str] = None
    mint_page_url: str
    site_label: str
    icon_name: str
    status_label: str
    status_kind: str
    is_supported_integration: bool
    manual_notice: Optional[str] = None
    is_demo: bool
    stages: List[MintStageSchema] = []


class DropListResponse(BaseModel):
    date_label: str
    source_status_text: str
    drops: List[DropSchema]
    checked_wallet_label: str
    last_checked_text: str


class EligibilityRecheckRequest(BaseModel):
    wallet_id: Optional[str] = None


class EligibilityRecheckResponse(BaseModel):
    drop_id: str
    status_label: str
    status_kind: str
    stages: List[MintStageSchema]
    checked_at: datetime
