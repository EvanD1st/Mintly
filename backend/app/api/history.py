"""Complete account records, including archived plans and in-flight transactions."""
from typing import Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_db
from app.api.tasks import task_response
from app.services.parser import format_wei_to_eth
from app.models import ActivityEvent, MintPlanRecord, MintTask, Wallet, User, MintPermission, MintRecovery

router = APIRouter(prefix='/history', tags=['history'])


@router.get('')
async def history(section: Literal['plans', 'mints', 'activity', 'permissions'] = 'mints',
                  offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
                  user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if section == 'plans':
        stmt = select(MintPlanRecord).where(MintPlanRecord.user_id == user.id).order_by(
            MintPlanRecord.recorded_at.desc(), MintPlanRecord.id.desc())
    elif section == 'mints':
        stmt = select(MintTask).join(Wallet, Wallet.id == MintTask.wallet_id).where(
            Wallet.user_id == user.id, MintTask.is_demo.is_(False)).order_by(MintTask.created_at.desc(), MintTask.id.desc())
    elif section == 'permissions':
        stmt = select(MintPermission).where(MintPermission.user_id == user.id).order_by(
            MintPermission.created_at.desc(), MintPermission.id.desc())
    else:
        stmt = select(ActivityEvent).where(ActivityEvent.user_id == user.id,
            ActivityEvent.is_demo.is_(False)).order_by(ActivityEvent.event_time.desc(), ActivityEvent.id.desc())
    rows = (await db.execute(stmt.offset(offset).limit(limit + 1))).scalars().all()
    records = []
    for row in rows[:limit]:
        if section == 'plans':
            records.append({'id': row.id, 'event': row.event, 'recorded_at': row.recorded_at, 'snapshot': row.snapshot})
        elif section == 'mints':
            # Queue serializer covers legacy tasks too, without exposing raw signed bytes or key material.
            from app.services.automatic import MODE
            if row.execution_mode == MODE:
                details = (await task_response(db, row)).model_dump(mode='json')
                from app.models import MintAuthorization
                auth = await db.get(MintAuthorization, row.authorization_id)
                details['authorization'] = {key: value for key, value in auth.snapshot.items() if key != 'execution'}
                details['authorized_at'] = auth.authorized_at
                details['actual_gas_used'] = row.actual_gas_used
                details['actual_effective_gas_price'] = row.actual_effective_gas_price
                details['block_number'] = row.block_number
                details['receipt_block_hash'] = row.receipt_block_hash
                details['original_expires_at_utc'] = row.expires_at_utc
                recoveries = (await db.scalars(select(MintRecovery).where(
                    MintRecovery.task_id == row.id, MintRecovery.user_id == user.id))).all()
                details['recoveries'] = [{'id': r.id, 'authorized_at': r.authorized_at,
                    'expires_at': r.expires_at, 'status': r.status, 'previous_hash': r.previous_hash,
                    'replacement_hash': r.replacement_hash, 'nonce': r.snapshot['recovery_nonce'],
                    'authorization_reference': r.authorization_reference,
                    'authorization': {k: v for k, v in r.snapshot.items() if k != 'execution'}} for r in recoveries]
            else:
                from app.models import MintAuthorization, Drop, MintStage
                auth = await db.get(MintAuthorization, row.authorization_id)
                drop = await db.get(Drop, row.drop_id)
                stage = await db.get(MintStage, row.stage_id)
                details = {'id': row.id, 'drop_name': drop.name if drop else 'Legacy mint',
                    'stage_name': stage.stage_name if stage else '', 'chain': drop.chain if drop else '',
                    'status': row.status, 'quantity': auth.quantity if auth else 1,
                    'total_cap_eth': format_wei_to_eth(auth.total_spend_cap_wei) if auth else '0',
                    'transaction_hash': row.transaction_hash, 'explorer_url': row.explorer_url,
                    'failure_reason': row.failure_reason, 'actual_total_cost_wei': row.actual_total_cost_wei}
            details['archived_at'] = row.archived_at
            details['created_at'] = row.created_at
            details['plan_id'] = row.plan_id
            records.append(details)
        elif section == 'permissions':
            records.append({'id': row.id, 'plan_id': row.plan_id, 'status': row.status,
                'note': row.note, 'transaction_hash': row.tx_hash, 'created_at': row.created_at,
                'expires_at': row.expires_at})
        else:
            records.append({'id': row.id, 'label': row.label, 'detail': row.detail,
                            'event_type': row.event_type, 'recorded_at': row.event_time})
    return {'records': records, 'next_offset': offset + limit if len(rows) > limit else None}
