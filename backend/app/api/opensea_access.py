"""User-owned eligibility consent. No OpenSea credentials returned to the app."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field,StrictBool
from sqlalchemy import select
import httpx
from app.api.deps import get_current_user,get_db
from app.models import Wallet,OpenSeaAccess,AutomaticGrant,ActivityEvent
from app.services import automatic
from app.services.mint_plans import aware
from app.services.opensea_identity import TERMS_VERSION,SCOPES
from app.config import settings

router=APIRouter(prefix='/wallets',tags=['eligibility'])
class AccessRequest(BaseModel):
    enabled:StrictBool
    consent:StrictBool=False
    terms_accepted:StrictBool=False

async def owned_wallet(db,wallet_id,user):
    wallet=await db.get(Wallet,wallet_id)
    if not wallet or wallet.user_id!=user.id or wallet.archived_at:raise HTTPException(404,'Wallet not found.')
    return wallet

def public(row,wallet):
    expired=row is not None and aware(row.expires_at)<=datetime.now(timezone.utc)
    return {'wallet_id':wallet.id,'available':wallet.signing_capability=='custodial',
        'enabled':bool(row and row.enabled and not expired),
        'status':'expired' if expired and row.enabled else row.status if row else 'disabled',
        'scopes':SCOPES,'expires_at':row.expires_at if row else None}

async def broker(wallet_id,operation,*,slug=None,key=None):
    token=Path(settings.AUTOMATIC_SIGNER_TOKEN_FILE).read_text().strip()
    if len(token)<32:raise ValueError('Signer control unavailable')
    from urllib.parse import quote
    path=f'/opensea/{quote(wallet_id,safe="")}/'+('register' if operation=='register' else 'stages/'+quote(slug,safe=''))
    async with httpx.AsyncClient(timeout=75,trust_env=False) as client:
        r=await client.post(settings.AUTOMATIC_SIGNER_URL+path,headers={'Authorization':'Bearer '+token},
            json={'api_key':key} if operation!='register' else None)
        if r.status_code==409:raise HTTPException(409,'Reconnect this wallet’s OpenSea eligibility access.')
        if r.status_code!=200:raise HTTPException(503,'OpenSea eligibility access is unavailable. Try again.')
        return r.json()

@router.get('/{wallet_id}/opensea-access')
async def status(wallet_id:str,user=Depends(get_current_user),db=Depends(get_db)):
    wallet=await owned_wallet(db,wallet_id,user)
    return public(await db.get(OpenSeaAccess,wallet_id),wallet)

@router.post('/{wallet_id}/opensea-access')
async def change(wallet_id:str,req:AccessRequest,user=Depends(get_current_user),db=Depends(get_db)):
    await automatic.lock_execution(db)
    wallet=await owned_wallet(db,wallet_id,user)
    if req.enabled:
        if not req.consent or not req.terms_accepted:raise HTTPException(422,'Accept the read-only sign-in consent and OpenSea terms.')
        if wallet.signing_capability!='custodial':raise HTTPException(409,'This address has no signing access. Set up an imported signing wallet first.')
        grants=(await db.scalars(select(AutomaticGrant).where(AutomaticGrant.wallet_id==wallet.id,
            AutomaticGrant.user_id==user.id,AutomaticGrant.status=='enabled'))).all()
        expiries=[aware(g.expires_at) for g in grants if aware(g.expires_at)>datetime.now(timezone.utc)]
        if not expiries:raise HTTPException(409,'Renew this wallet’s signing approval before connecting eligibility access.')
        expiry=min(max(expiries),datetime.now(timezone.utc)+timedelta(days=7))
    else:expiry=datetime.now(timezone.utc)
    row=await db.get(OpenSeaAccess,wallet_id)
    if not row:
        row=OpenSeaAccess(wallet_id=wallet.id,user_id=user.id,revision=0,enabled=False,expires_at=expiry,
            terms_version=TERMS_VERSION,consented_at=datetime.now(timezone.utc),status='disabled');db.add(row)
    if row.user_id!=user.id:raise HTTPException(404,'Wallet consent not found.')
    # Only an identical pending request retries; a reconnect is fresh explicit consent.
    pending=row.status=='registering' and row.enabled==req.enabled
    if not pending:
        row.revision+=1
        row.expires_at=expiry;row.consented_at=datetime.now(timezone.utc)
    revision=row.revision
    row.enabled,row.status=req.enabled,'registering'
    row.terms_version=TERMS_VERSION
    await db.commit()
    try:
        result=await broker(wallet_id,'register')
        if result.get('revision')!=revision or result.get('scopes')!=SCOPES:raise ValueError('Consent confirmation differs')
    except Exception:
        # Disabled consent blocks locally immediately, even when remote revocation is pending.
        if not req.enabled:return {**public(row,wallet),'enabled':False,'status':'revocation_pending'}
        raise HTTPException(503,'Consent saved; OpenSea connection is pending. Retry to confirm.') from None
    await automatic.lock_execution(db);await db.refresh(row);await db.refresh(wallet)
    if row.revision!=revision or wallet.archived_at:raise HTTPException(409,'Wallet access changed. Reload this screen.')
    row.status=result['status']
    db.add(ActivityEvent(user_id=user.id,event_type='opensea_access_changed',label='OpenSea eligibility access updated',
        detail='Read-only stage eligibility access '+('enabled.' if req.enabled else 'disabled.'),is_demo=False,icon_name='wallet'))
    await db.commit()
    return public(row,wallet)
