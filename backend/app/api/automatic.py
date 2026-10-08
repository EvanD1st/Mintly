"""Public metadata for explicitly provisioned custody. No key import over HTTP."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from pydantic import BaseModel
from pydantic import Field
from pathlib import Path
import httpx
from app.config import settings
from app.api.deps import get_current_user, get_db
from app.models import AutomaticGrant, MintTask, MintAuthorization, CopyRule, Wallet, User, ActivityEvent, MintPermission, DailyDebit
from app.services import automatic

router = APIRouter(prefix='/automatic', tags=['automatic'])


class PauseRequest(BaseModel):
    paused: bool


class DailyLimitRequest(BaseModel):
    limit_eth: str | None = Field(default=None, pattern=r'^[0-9]+(\.[0-9]+)?$',max_length=40)
    consent: bool


async def signer_limit(user_id,operation):
    token = Path(settings.AUTOMATIC_SIGNER_TOKEN_FILE).read_text().strip()
    if len(token) < 32:
        raise ValueError('Signer control authentication unavailable')
    async with httpx.AsyncClient(timeout=40,trust_env=False) as client:
        url=settings.AUTOMATIC_SIGNER_URL + f'/account-limits/{user_id}/{operation}'
        method=client.post if operation == 'register' else client.get
        response=await method(url,headers={'Authorization':'Bearer '+token})
        response.raise_for_status()
        return response.json()


@router.get('/daily-limit')
async def daily_limit(user=Depends(get_current_user),db=Depends(get_db)):
    from app.services import daily_budget
    used=await daily_budget.usage(db,user.id)
    verified=True
    if user.daily_limit_wei is not None:
        try:
            signed=await signer_limit(user.id,'usage')
            unsigned=(await db.scalars(select(DailyDebit).where(DailyDebit.user_id==user.id,
                DailyDebit.actual_wei.is_(None),DailyDebit.day<=daily_budget.day_key()))).all()
            signed_ids=set(signed['signed_tasks'])
            used['spent_wei']=int(signed['spent_wei'])
            used['reserved_wei']=int(signed['reserved_wei'])+sum(r.maximum_wei for r in unsigned if r.task_id not in signed_ids)
        except Exception:
            verified=False
    return {'limit_wei':str(user.daily_limit_wei) if user.daily_limit_wei is not None else None,
        **{k:str(v) for k,v in used.items()},'day_wat':daily_budget.day_key(),
        'remaining_wei':str(max(0,user.daily_limit_wei-used['spent_wei']-used['reserved_wei'])) if user.daily_limit_wei is not None and verified else None,
        'status':user.daily_limit_status,'usage_verified':verified,'timezone':'WAT'}


@router.post('/daily-limit')
async def set_daily_limit(req:DailyLimitRequest,user=Depends(get_current_user),db=Depends(get_db)):
    from app.services import daily_budget
    if not req.consent:
        raise HTTPException(422,'Confirm the account-wide daily limit.')
    amount=automatic.wei(req.limit_eth) if req.limit_eth is not None else None
    if amount == 0:
        raise HTTPException(422,'Enter a positive daily amount or turn off the additional daily cap.')
    await automatic.lock_execution(db)
    user=await db.get(User,user.id,populate_existing=True)
    await daily_budget.seed_existing(db,user.id)
    if user.daily_limit_status != 'registering' or user.daily_limit_wei != amount:
        user.daily_limit_revision += 1
    revision=user.daily_limit_revision
    user.daily_limit_wei,user.daily_limit_status=amount,'registering'
    await db.commit()
    try:
        registered=await signer_limit(user.id,'register')
        if registered.get('revision') != revision:
            raise ValueError('Daily limit revision differs')
    except Exception:
        raise HTTPException(503,'Daily limit saved, but signer confirmation is pending. Retry this setting; future signing is blocked.') from None
    await automatic.lock_execution(db)
    await db.refresh(user)
    if user.daily_limit_revision != revision or user.daily_limit_wei != amount:
        raise HTTPException(409,'The daily limit changed. Reload Settings.')
    user.daily_limit_status='active'
    db.add(ActivityEvent(user_id=user.id,event_type='daily_limit_changed',label='Daily spending limit updated',
        detail='One WAT-day limit across scheduled and copy mints. Existing signed transactions remain tracked.',is_demo=False,icon_name='gem'))
    await db.commit()
    return await daily_limit(user,db)


@router.get('/status')
async def status(user=Depends(get_current_user)):
    return {'paused': user.automation_paused}


@router.post('/pause')
async def pause(req: PauseRequest, user=Depends(get_current_user), db=Depends(get_db)):
    await automatic.lock_execution(db)
    user = await db.get(User, user.id, populate_existing=True)
    user.automation_paused = req.paused
    if req.paused:
        tasks = (await db.scalars(select(MintTask).join(Wallet, Wallet.id == MintTask.wallet_id).where(
            Wallet.user_id == user.id, MintTask.status.in_(['armed', 'preparing']),
            MintTask.signed_tx_raw.is_(None)))).all()
        for task in tasks:
            task.status, task.failure_reason = 'disarmed', 'Paused in Settings. Review this mint to set it up again.'
            if task.execution_mode == automatic.MODE:
                await automatic.release_reservation(db, task)
        rules = (await db.scalars(select(CopyRule).where(CopyRule.user_id == user.id,
            CopyRule.status.in_(['active', 'registering'])))).all()
        for rule in rules:
            rule.status = 'paused'
        permissions = (await db.scalars(select(MintPermission).where(MintPermission.user_id == user.id,
            MintPermission.status.in_(['awaiting_signature','armed'])))).all()
        for permission in permissions:
            permission.status, permission.note = 'cancelled', 'Automation paused in Settings.'
    db.add(ActivityEvent(user_id=user.id, event_type='automation_paused' if req.paused else 'automation_resumed',
        label='All automation paused' if req.paused else 'Automation available',
        detail='Signed transactions remain tracked. Resume paused copy rules and review mint plans separately.',
        is_demo=False, icon_name='gem'))
    await db.commit()
    return {'paused': user.automation_paused, 'note': 'Paused plans and copy rules need to be enabled again.'}


@router.get('/policies')
async def policies(user=Depends(get_current_user), db=Depends(get_db)):
    grants = (await db.execute(select(AutomaticGrant).where(AutomaticGrant.user_id == user.id))).scalars().all()
    return [automatic.public_grant(g) for g in grants]


@router.post('/policies/{grant_id}/disable')
async def disable(grant_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    await automatic.lock_execution(db)
    grant = (await db.execute(select(AutomaticGrant).where(AutomaticGrant.id == grant_id, AutomaticGrant.user_id == user.id))).scalar_one_or_none()
    if not grant:
        raise HTTPException(404, 'Policy not found.')
    grant.status = 'disabled'
    tasks = (await db.execute(select(MintTask).join(MintAuthorization, MintAuthorization.id == MintTask.authorization_id).where(
        MintAuthorization.grant_id == grant.id, MintTask.status.in_(['armed', 'preparing']), MintTask.signed_tx_raw.is_(None)))).scalars().all()
    for task in tasks:
        task.status = 'disarmed'
        await automatic.release_reservation(db, task)
    for rule in (await db.execute(select(CopyRule).where(CopyRule.grant_id == grant.id,
            CopyRule.status.in_(['active','registering'])))).scalars().all():
        rule.status = 'paused'
    await db.commit()
    return {'status': 'disabled', 'note': 'Future signing disabled in Mintly. Signed transactions remain in flight. This does not erase server custody or revoke a wallet grant.'}
