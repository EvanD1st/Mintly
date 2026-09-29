"""Pydantic schemas for Wallets."""

from typing import List
from pydantic import BaseModel, ConfigDict, Field


class WalletSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    address: str
    signing_capability: str
    supported_chains: List[str]
    is_default: bool
    is_demo: bool


class CreateWalletRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    address: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    signing_capability: str = Field(default="watch_only")
    supported_chains: List[str] = ["Ethereum", "Base", "Sepolia", "Base Sepolia"]
    is_default: bool = False
