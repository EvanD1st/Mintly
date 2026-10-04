"""Public metadata for explicitly provisioned custody. No key import over HTTP."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from app.api.deps import get_current_user, get_db
from app.models import AutomaticGrant, MintTask, MintAuthorization, CopyRule
from app.services import automatic

router = APIRouter(prefix='/automatic', tags=['automatic'])


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
