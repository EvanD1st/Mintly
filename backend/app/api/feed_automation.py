from datetime import datetime
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field,StrictBool
from sqlalchemy import select
from app.api.deps import get_current_user,get_db
from app.models import FeedMintApproval
from app.services import automatic,feed_automation

router=APIRouter(prefix='/automatic/free-drops',tags=['automatic'])

class Approve(BaseModel):
    request_id:str=Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    grant_id:str
    quantity:int=Field(default=1,ge=1,le=65535,strict=True)
    quantity_mode:Literal['fixed','wallet_max']='fixed'
    fee_cap:str=Field(pattern=r'^[0-9]+(\.[0-9]+)?$',max_length=40)
    native_symbol:str='ETH'
    expires_at:datetime
    consent:StrictBool=False

class Enable(BaseModel):
    request_id:str=Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    wallet_id:str | None=None
    consent:StrictBool=False

@router.post('/enable')
async def enable(req:Enable,user=Depends(get_current_user),db=Depends(get_db)):
    return await feed_automation.enable_for_today_wallet(db,user,req)

@router.get('')
async def status(user=Depends(get_current_user),db=Depends(get_db)):
    rows=(await db.scalars(select(FeedMintApproval).where(FeedMintApproval.user_id==user.id).order_by(FeedMintApproval.created_at.desc()))).all()
    return {'approvals':[feed_automation.public(r) for r in rows],
        'enabled_once':await feed_automation.enabled_once(db,user)}

@router.post('')
async def approve(req:Approve,user=Depends(get_current_user),db=Depends(get_db)):
    return await feed_automation.create(db,user,req)

@router.delete('/{approval_id}')
async def revoke(approval_id:str,user=Depends(get_current_user),db=Depends(get_db)):
    await automatic.lock_execution(db)
    row=await db.get(FeedMintApproval,approval_id)
    if not row or row.user_id!=user.id:raise HTTPException(404,'Standing approval not found.')
    row.status='revoking';await db.commit()
    try:await feed_automation.broker(row.id,operation='revoke')
    except Exception:raise HTTPException(503,'New free-list signing is blocked. Confirmation of cancellation is pending; retry to finish.') from None
    await db.refresh(row)
    return feed_automation.public(row)
