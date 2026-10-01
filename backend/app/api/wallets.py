"""Per-user wallets verified by a short-lived MetaMask message signature."""

import re
import secrets
from datetime import datetime, timedelta, timezone

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address, is_address
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.models import MintPlan, MintPermission, MintTask, User, Wallet, WalletPairing
from app.schemas.wallet import WalletSchema
from app.services.auth import token_digest
from app.services.opensea import CHAINS

router = APIRouter(prefix="/wallets", tags=["wallets"])
public_router = APIRouter(prefix="/wallet-link", tags=["wallet-link"])
CODE_PATTERN = re.compile(r"^[0-9a-f]{16}$")


class PairRequest(BaseModel):
    code: str = Field(min_length=16, max_length=19)
    address: str = Field(min_length=42, max_length=42)


class CompleteRequest(PairRequest):
    signature: str = Field(min_length=130, max_length=132)


def normalize_code(code: str) -> str:
    clean = code.replace("-", "").lower()
    if not CODE_PATTERN.fullmatch(clean):
        raise HTTPException(status_code=400, detail="Invalid pairing code.")
    return clean


def normalize_address(address: str) -> str:
    if not is_address(address):
        raise HTTPException(status_code=400, detail="Invalid Ethereum address.")
    return to_checksum_address(address)


async def active_pairing(db: AsyncSession, code: str, *, lock: bool = False) -> WalletPairing:
    stmt = select(WalletPairing).where(WalletPairing.code_hash == token_digest(normalize_code(code)))
    if lock:
        stmt = stmt.with_for_update()
    pairing = (await db.execute(stmt)).scalar_one_or_none()
    if pairing is None or pairing.used_at is not None or pairing.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Pairing code expired or unavailable.")
    user = (await db.execute(select(User).where(User.id == pairing.user_id))).scalar_one_or_none()
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Pairing code expired or unavailable.")
    return pairing


@router.get("", response_model=list[WalletSchema])
async def list_wallets(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Wallet).where(Wallet.user_id == user.id).order_by(
        Wallet.is_default.desc(), Wallet.created_at.asc(),
    ))).scalars().all()


@router.post("/pairings")
async def start_pairing(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    code = secrets.token_hex(8)
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    pairing = WalletPairing(user_id=user.id, code_hash=token_digest(code),
                            nonce=secrets.token_hex(8), expires_at=expires)
    db.add(pairing)
    await db.commit()
    return {"pairing_id": pairing.id, "code": "-".join(code[i:i+4] for i in range(0, 16, 4)),
            "expires_at": expires, "connect_url": f"{settings.PUBLIC_URL.rstrip('/')}/connect"}


@router.get("/pairings/{pairing_id}")
async def pairing_status(pairing_id: str, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    pairing = (await db.execute(select(WalletPairing).where(
        WalletPairing.id == pairing_id, WalletPairing.user_id == user.id,
    ))).scalar_one_or_none()
    if pairing is None:
        raise HTTPException(status_code=404, detail="Pairing not found.")
    return {"status": "linked" if pairing.linked_wallet_id else (
        "expired" if pairing.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc) else "pending"),
        "wallet_id": pairing.linked_wallet_id}


@public_router.post("/challenge")
async def pairing_challenge(req: PairRequest, db: AsyncSession = Depends(get_db)):
    pairing = await active_pairing(db, req.code, lock=True)
    address = normalize_address(req.address)
    if pairing.challenge_address and pairing.challenge_address != address:
        raise HTTPException(status_code=409, detail="A different address began this pairing. Start again in the app.")
    now = datetime.now(timezone.utc)
    expires = pairing.expires_at.replace(tzinfo=timezone.utc)
    base = settings.PUBLIC_URL.rstrip("/")
    domain = base.removeprefix("https://")
    if not base.startswith("https://"):
        raise HTTPException(status_code=503, detail="Secure wallet linking is unavailable.")
    message = (
        f"{domain} wants you to sign in with your Ethereum account:\n"
        f"{address}\n\n"
        "Link this address to your Mintly account. This signature does not authorize transactions.\n\n"
        f"URI: {base}/connect\n"
        "Version: 1\n"
        "Chain ID: 1\n"
        f"Nonce: {pairing.nonce}\n"
        f"Issued At: {now.isoformat().replace('+00:00', 'Z')}\n"
        f"Expiration Time: {expires.isoformat().replace('+00:00', 'Z')}\n"
        f"Request ID: {pairing.id}"
    )
    pairing.challenge_address = address
    pairing.challenge_message = message
    await db.commit()
    return {"message": message, "expires_at": expires}


@public_router.post("/complete")
async def complete_pairing(req: CompleteRequest, db: AsyncSession = Depends(get_db)):
    pairing = await active_pairing(db, req.code, lock=True)
    address = normalize_address(req.address)
    if pairing.challenge_address != address or not pairing.challenge_message:
        raise HTTPException(status_code=400, detail="Request a challenge for this address first.")
    try:
        recovered = Account.recover_message(
            encode_defunct(text=pairing.challenge_message), signature=req.signature,
        )
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid wallet signature.")
    if recovered != address:
        raise HTTPException(status_code=400, detail="Signature does not match the requested address.")
    existing = (await db.execute(select(Wallet).join(User, User.id == Wallet.user_id).where(
        func.lower(Wallet.address) == address.lower(), User.is_active.is_(True),
        User.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if existing and existing.user_id != pairing.user_id:
        raise HTTPException(status_code=409, detail="This address is already linked to another account.")
    if existing is None:
        count = (await db.execute(select(func.count()).select_from(Wallet).where(
            Wallet.user_id == pairing.user_id,
        ))).scalar_one()
        existing = Wallet(user_id=pairing.user_id, label="MetaMask", address=address,
                          signing_capability="interactive", supported_chains=[label for _, label in CHAINS.values()],
                          is_default=count == 0, is_demo=False)
        db.add(existing)
        await db.flush()
    pairing.used_at = datetime.now(timezone.utc)
    pairing.linked_wallet_id = existing.id
    await db.commit()
    return {"status": "linked", "address": address}


@router.delete("/{wallet_id}")
async def unlink_wallet(wallet_id: str, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    wallet = (await db.execute(select(Wallet).where(
        Wallet.id == wallet_id, Wallet.user_id == user.id,
    ))).scalar_one_or_none()
    if wallet is None:
        raise HTTPException(status_code=404, detail="Wallet not found.")
    if (await db.execute(select(MintTask.id).where(MintTask.wallet_id == wallet.id).limit(1))).first():
        raise HTTPException(status_code=409, detail="Wallet has transaction history and cannot be unlinked here.")
    if (await db.execute(select(MintPermission.id).join(MintPlan,MintPlan.id==MintPermission.plan_id).where(MintPlan.wallet_id==wallet.id).limit(1))).first():
        raise HTTPException(409,'Wallet has mint permission history and must be retained for tracking.')
    await db.execute(delete(MintPlan).where(MintPlan.wallet_id == wallet.id))
    await db.execute(delete(WalletPairing).where(WalletPairing.linked_wallet_id == wallet.id))
    await db.delete(wallet)
    await db.commit()
    return {"status": "ok"}
