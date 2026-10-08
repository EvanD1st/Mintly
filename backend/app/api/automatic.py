"""Public metadata for explicitly provisioned custody. No key import over HTTP."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from pydantic import BaseModel
from app.api.deps import get_current_user, get_db
from app.models import AutomaticGrant, MintTask, MintAuthorization, CopyRule, Wallet, User, ActivityEvent, MintPermission
from app.services import automatic

router = APIRouter(prefix='/automatic', tags=['automatic'])


class PauseRequest(BaseModel):
    paused: bool


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
