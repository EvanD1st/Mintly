"""One task lifecycle for explicitly provisioned custodial signing and legacy history."""

from zoneinfo import ZoneInfo
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import ActivityEvent, Drop, MintAuthorization, MintStage, MintTask, User, Wallet, MintRecovery
from app.schemas.task import DraftTaskRequest, ArmTaskRequest, TaskSchema, QueueResponse
from app.services.parser import format_wei_to_eth
from app.services import automatic
from app.services.opensea import OpenSeaUnavailable

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/draft")
async def draft_task_preview(req: DraftTaskRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    grant, snapshot = await automatic.make_snapshot(db, req, user.id)
    await automatic.signer_ready(grant.id)
    web3 = await automatic.provider()
    try:
        execution = await automatic.prepare_mint(web3, snapshot)
        eligibility = 'verified'
    except Exception as error:
        if (snapshot['mint_kind'] == 'public' or not req.conditional_eligibility
                or not isinstance(error, OpenSeaUnavailable) or error.status not in (429, 503)):
            raise HTTPException(409, 'Exact stage or eligibility could not be verified. Review the stage or explicitly authorize a conditional presale attempt.') from error
        execution, eligibility = None, 'conditional_at_opening'
    finally:
        await web3.provider.disconnect()
    # No signature, reservation or spending occurs at preview.
    return {'snapshot': snapshot, 'review_hash': automatic.digest(snapshot), 'eligibility': eligibility, 'execution_ready': execution is not None,
            'policy': automatic.public_grant(grant), 'is_signer_ready': True,
            'signer_status_note': 'Custodial signer policy. Execution continues while the app is closed.'}


@router.post("/arm")
async def arm_mint_task(req: ArmTaskRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    automatic.enabled()
    if not req.user_consent_confirmed:
        raise HTTPException(422, 'Explicit task authorization is required.')
    request_hash = automatic.digest(req.model_dump(mode='json', exclude={'idempotency_key'}))
    key = automatic.digest([user.id, req.idempotency_key])
    await automatic.lock_execution(db)
    existing = (await db.execute(select(MintTask).where(MintTask.idempotency_key == key))).scalar_one_or_none()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, 'Idempotency key was already used for different task limits.')
        return await task_response(db, existing)
    if req.plan_id:
        pending = await db.scalar(select(MintTask.id).where(MintTask.plan_id == req.plan_id,
            MintTask.status.not_in(automatic.TERMINAL)).limit(1))
        if pending:
            raise HTTPException(409, 'This plan already has an active automatic mint. Check its task before arming another.')
    grant, snapshot = await automatic.make_snapshot(db, req, user.id)
    await automatic.signer_ready(grant.id)
    web3 = await automatic.provider()
    try:
        execution = await automatic.prepare_mint(web3, snapshot)
    except Exception as error:
        if (snapshot['mint_kind'] == 'public' or not req.conditional_eligibility
                or not isinstance(error, OpenSeaUnavailable) or error.status not in (429, 503)):
            raise HTTPException(409, 'Exact stage or eligibility could not be verified before arming.') from error
        execution = None
    finally:
        await web3.provider.disconnect()
    if req.review_hash and req.review_hash != automatic.digest(snapshot):
        raise HTTPException(409, 'The reviewed stage or limits changed. Review again before arming.')
    snapshot['execution'] = execution
    auth = MintAuthorization(id=str(uuid.uuid4()), wallet_id=req.wallet_id, drop_id=req.drop_id,
        stage_id=req.stage_id, quantity=req.quantity, max_price_per_token_wei=snapshot['price_cap_wei'],
        max_fee_wei=snapshot['fee_cap_wei'], total_spend_cap_wei=snapshot['total_cap_wei'],
        recipient_address=snapshot['recipient'], user_consent_text='Arm exact custodial automatic mint with the displayed finite limits.',
        authorized_at=datetime.now(timezone.utc), grant_id=grant.id, snapshot=snapshot)
    task = MintTask(id=str(uuid.uuid4()), authorization_id=auth.id, wallet_id=req.wallet_id,
        drop_id=req.drop_id, stage_id=req.stage_id, plan_id=req.plan_id, status='armed', is_demo=False,
        idempotency_key=key, request_hash=request_hash, execution_mode=automatic.MODE,
        scheduled_for_utc=datetime.fromtimestamp(snapshot['start'], timezone.utc),
        expires_at_utc=datetime.fromtimestamp(snapshot['expiry'], timezone.utc))
    grant.reserved_wei += auth.total_spend_cap_wei
    db.add(auth)
    await db.flush()
    db.add(task)
    db.add(ActivityEvent(user_id=user.id, event_type='automatic_armed', label='Automatic mint armed',
                         detail=task.id, icon_name='gem', is_demo=False))
    await db.commit()
    return await task_response(db, task)


async def task_response(db, task):
    auth = await db.get(MintAuthorization, task.authorization_id)
    s = auth.snapshot
    recovery = await db.scalar(select(MintRecovery).where(MintRecovery.task_id == task.id))
    return TaskSchema(id=task.id, wallet_id=task.wallet_id, drop_id=task.drop_id,
        stage_id=task.stage_id, status=task.status, is_demo=task.is_demo,
        scheduled_for_utc=task.scheduled_for_utc,
        expires_at_utc=recovery.expires_at if recovery and recovery.activated_at else task.expires_at_utc,
        quantity=auth.quantity, unit_price_eth=format_wei_to_eth(s['price_wei']),
        fee_cap_eth=format_wei_to_eth(auth.max_fee_wei), total_cap_eth=format_wei_to_eth(auth.total_spend_cap_wei),
        drop_name=s['drop_name'], chain=s['chain'], stage_name=s['stage_name'], icon_name='gem',
        time_wat_label=datetime.fromtimestamp(s['start'], ZoneInfo('Africa/Lagos')).strftime('%H:%M WAT'),
        transaction_hash=task.transaction_hash, explorer_url=task.explorer_url, failure_reason=task.failure_reason,
        submitted_at=task.submitted_at, confirmed_at=task.confirmed_at, actual_total_cost_wei=task.actual_total_cost_wei,
        execution_mode=task.execution_mode, wallet_address=s['account'])


@router.post("/{task_id}/disarm")
async def disarm_task(task_id: str, db: AsyncSession = Depends(get_db),
                      user: User = Depends(get_current_user)):
    await automatic.lock_execution(db)
    task = (await db.execute(select(MintTask).join(Wallet, Wallet.id == MintTask.wallet_id).where(
        MintTask.id == task_id, Wallet.user_id == user.id,
    ))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task.status == "disarmed":
        return {"message": "Task already disarmed.", "task_id": task_id, "status": "disarmed"}
    if task.status not in ("armed", "preparing"):
        raise HTTPException(status_code=409, detail=f"Task is already {task.status} and cannot be canceled here.")
    changed = await db.execute(update(MintTask).where(
        MintTask.id == task_id, MintTask.status.in_(["armed", "preparing"]), MintTask.signed_tx_raw.is_(None),
    ).values(status="disarmed").returning(MintTask.id))
    if changed.scalar_one_or_none() is None:
        raise HTTPException(status_code=409, detail="Task is already in flight and cannot be canceled here.")
    if task.execution_mode == automatic.MODE:
        await automatic.release_reservation(db, task)
    db.add(ActivityEvent(user_id=user.id, event_type="task_disarmed", label="Task disarmed",
                         detail=task_id, icon_name="circle-pause", is_demo=False))
    await db.commit()
    return {"message": "Task disarmed successfully.", "task_id": task_id, "status": "disarmed"}


@router.get("/queue", response_model=QueueResponse)
async def list_mint_queue(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    tasks = (await db.execute(select(MintTask).join(Wallet, Wallet.id == MintTask.wallet_id).where(
        Wallet.user_id == user.id, MintTask.is_demo.is_(False), MintTask.archived_at.is_(None),
    ).order_by(MintTask.scheduled_for_utc.asc()))).scalars().all()
    formatted = []
    for task in tasks:
        if task.execution_mode == automatic.MODE:
            formatted.append(await task_response(db, task))
            continue
        drop = (await db.execute(select(Drop).where(Drop.id == task.drop_id))).scalar_one_or_none()
        stage = (await db.execute(select(MintStage).where(MintStage.id == task.stage_id))).scalar_one_or_none()
        auth = (await db.execute(select(MintAuthorization).where(
            MintAuthorization.id == task.authorization_id,
        ))).scalar_one_or_none()
        formatted.append(TaskSchema(
            id=task.id, wallet_id=task.wallet_id, drop_id=task.drop_id, stage_id=task.stage_id,
            status=task.status, is_demo=False, scheduled_for_utc=task.scheduled_for_utc,
            expires_at_utc=task.expires_at_utc, quantity=auth.quantity if auth else 1,
            unit_price_eth=stage.price_eth_str if stage else "",
            fee_cap_eth=format_wei_to_eth(auth.max_fee_wei) if auth else "0",
            total_cap_eth=format_wei_to_eth(auth.total_spend_cap_wei) if auth else "0",
            drop_name=drop.name if drop else "Unknown drop", chain=drop.chain if drop else "Unknown",
            stage_name=stage.stage_name if stage else "Unknown",
            time_wat_label=task.scheduled_for_utc.astimezone(ZoneInfo("Africa/Lagos")).strftime("%H:%M WAT"),
            icon_name=drop.icon_name if drop else "gem", transaction_hash=task.transaction_hash,
            explorer_url=task.explorer_url, failure_reason=task.failure_reason,
            submitted_at=task.submitted_at, confirmed_at=task.confirmed_at,
            actual_total_cost_wei=task.actual_total_cost_wei,
        ))
    return QueueResponse(tasks=formatted, total_count=len(formatted))


async def archive_task(db, task, user_id, now):
    """Caller holds lock_execution. Signed tasks retain bytes, status and reservation."""
    in_flight = task.status not in automatic.TERMINAL and bool(
        task.signed_tx_raw or task.status not in ('armed', 'preparing'))
    if task.archived_at:
        return in_flight
    if task.status in ('armed', 'preparing') and not task.signed_tx_raw:
        task.status = 'disarmed'
        if task.execution_mode == automatic.MODE:
            await automatic.release_reservation(db, task)
    task.archived_at = now
    db.add(ActivityEvent(user_id=user_id, event_type='task_removed', label='Mint task removed',
        detail=task.id + ('; transaction tracking continues in History.' if in_flight else '; retained in History.'),
        icon_name='gem', is_demo=False))
    return in_flight


@router.delete('/{task_id}')
async def remove_task(task_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await automatic.lock_execution(db)
    task = (await db.execute(select(MintTask).join(Wallet, Wallet.id == MintTask.wallet_id).where(
        MintTask.id == task_id, Wallet.user_id == user.id, MintTask.is_demo.is_(False),
    ))).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, 'Task not found.')
    in_flight = await archive_task(db, task, user.id, datetime.now(timezone.utc))
    await db.commit()
    return {'status': 'removed', 'in_flight': in_flight, 'history_retained': True}
