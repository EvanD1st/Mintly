"""Active wallet list and history-preserving unlink; phrase setup uses isolated ingress."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.api.deps import get_current_user, get_db
from app.models import Wallet, WalletPairing
from app.schemas.wallet import WalletSchema
from app.services import automatic
from eth_utils import is_address, to_checksum_address
import uuid

router = APIRouter(prefix='/wallets', tags=['wallets'])
public_router = APIRouter(prefix='/wallet-link', tags=['wallet-link'])

class PairRequest(BaseModel):
    code: str = Field(min_length=16, max_length=19)
    address: str = Field(min_length=42, max_length=42)
class CompleteRequest(PairRequest):
    signature: str = Field(min_length=130, max_length=132)


class WatchWalletRequest(BaseModel):
    label:str=Field(min_length=1,max_length=80)
    address:str=Field(min_length=42,max_length=42)


@router.post('/watch')
async def add_watch_wallet(req:WatchWalletRequest,user=Depends(get_current_user),db=Depends(get_db)):
    if not is_address(req.address) or int(req.address,16)==0:
        raise HTTPException(422,'Enter a valid wallet address.')
    from sqlalchemy import func
    await automatic.lock_execution(db)
    wallet=await db.scalar(select(Wallet).where(Wallet.user_id==user.id,Wallet.archived_at.is_(None),
        func.lower(Wallet.address)==req.address.lower()))
    if wallet:
        return WalletSchema.model_validate(wallet)
    wallet=Wallet(id=str(uuid.uuid4()),user_id=user.id,address=to_checksum_address(req.address),label=req.label.strip(),
        signing_capability='watch_only',is_demo=False)
    db.add(wallet);await db.commit()
    return WalletSchema.model_validate(wallet)

@router.get('', response_model=list[WalletSchema])
async def list_wallets(user=Depends(get_current_user), db=Depends(get_db)):
    return (await db.scalars(select(Wallet).where(Wallet.user_id == user.id, Wallet.archived_at.is_(None))
        .order_by(Wallet.is_default.desc(), Wallet.created_at))).all()

@router.post('/pairings')
async def start_pairing(user=Depends(get_current_user)):
    raise HTTPException(410, 'Open Set up wallet in Mintly to add an address or explicitly enable automatic signing.')


@router.get('/readiness')
async def wallet_readiness(user=Depends(get_current_user), db=Depends(get_db)):
    from app.services.wallet_readiness import readiness
    return await readiness(db, user)

@router.get('/pairings/{pairing_id}')
async def pairing_status(pairing_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    pairing = await db.scalar(select(WalletPairing).where(WalletPairing.id == pairing_id, WalletPairing.user_id == user.id))
    if not pairing: raise HTTPException(404, 'Pairing not found.')
    return {'status': 'linked' if pairing.linked_wallet_id else 'expired', 'wallet_id': pairing.linked_wallet_id}

@public_router.post('/challenge')
async def pairing_challenge(req: PairRequest):
    raise HTTPException(410, 'Web wallet linking has ended. Add your wallet in the Mintly app.')

@public_router.post('/complete')
async def complete_pairing(req: CompleteRequest):
    raise HTTPException(410, 'Web wallet linking has ended. Add your wallet in the Mintly app.')

@router.delete('/{wallet_id}')
async def unlink_wallet(wallet_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    await automatic.lock_execution(db)
    wallet = await db.scalar(select(Wallet).where(Wallet.id == wallet_id, Wallet.user_id == user.id))
    if not wallet: raise HTTPException(404, 'Wallet not found.')
    from app.services.wallet_lifecycle import unlink
    await unlink(db, wallet)
    await db.commit()
    return {'status': 'unlinked', 'history_retained': True, 'automatic_actions_disabled': True}
