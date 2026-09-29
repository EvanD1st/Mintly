"""Wallet management endpoints."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, verify_owner_authorization
from app.models import Wallet
from app.schemas.wallet import WalletSchema, CreateWalletRequest

router = APIRouter(prefix="/wallets", tags=["wallets"])


@router.get("", response_model=List[WalletSchema])
async def list_wallets(db: AsyncSession = Depends(get_db)):
    """Lists configured wallets in address book."""
    stmt = select(Wallet).order_by(Wallet.is_default.desc(), Wallet.created_at.asc())
    wallets = (await db.execute(stmt)).scalars().all()
    return wallets


@router.post("", response_model=WalletSchema)
async def create_wallet(
    req: CreateWalletRequest,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(verify_owner_authorization),
):
    """Adds a new address to the address book."""
    wallet = Wallet(
        label=req.label,
        address=req.address,
        signing_capability=req.signing_capability,
        supported_chains=req.supported_chains,
        is_default=req.is_default,
        is_demo=False,
    )
    db.add(wallet)
    await db.commit()
    await db.refresh(wallet)
    return wallet
