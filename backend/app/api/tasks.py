"""Read or cancel legacy tasks. MetaMask transactions always require user approval."""

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import ActivityEvent, Drop, MintAuthorization, MintStage, MintTask, User, Wallet
from app.schemas.task import DraftTaskRequest, ArmTaskRequest, TaskSchema, QueueResponse
from app.services.parser import format_wei_to_eth

router = APIRouter(prefix="/tasks", tags=["tasks"])
UNATTENDED_MESSAGE = "Unattended minting is unavailable for MetaMask wallets. Confirm every transaction in MetaMask."


@router.post("/draft")
async def draft_task_preview(req: DraftTaskRequest, user: User = Depends(get_current_user)):
    raise HTTPException(status_code=409, detail=UNATTENDED_MESSAGE)


@router.post("/arm")
async def arm_mint_task(req: ArmTaskRequest, user: User = Depends(get_current_user)):
    raise HTTPException(status_code=409, detail=UNATTENDED_MESSAGE)


@router.post("/{task_id}/disarm")
async def disarm_task(task_id: str, db: AsyncSession = Depends(get_db),
                      user: User = Depends(get_current_user)):
    task = (await db.execute(select(MintTask).join(Wallet, Wallet.id == MintTask.wallet_id).where(
        MintTask.id == task_id, Wallet.user_id == user.id,
    ))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task.status == "disarmed":
        return {"message": "Task already disarmed.", "task_id": task_id, "status": "disarmed"}
    if task.status != "armed":
        raise HTTPException(status_code=409, detail=f"Task is already {task.status} and cannot be canceled here.")
    changed = await db.execute(update(MintTask).where(
        MintTask.id == task_id, MintTask.status == "armed",
    ).values(status="disarmed").returning(MintTask.id))
    if changed.scalar_one_or_none() is None:
        raise HTTPException(status_code=409, detail="Task is already in flight and cannot be canceled here.")
    db.add(ActivityEvent(user_id=user.id, event_type="task_disarmed", label="Task disarmed",
                         detail=task_id, icon_name="circle-pause", is_demo=False))
    await db.commit()
    return {"message": "Task disarmed successfully.", "task_id": task_id, "status": "disarmed"}


@router.get("/queue", response_model=QueueResponse)
async def list_mint_queue(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    tasks = (await db.execute(select(MintTask).join(Wallet, Wallet.id == MintTask.wallet_id).where(
        Wallet.user_id == user.id, MintTask.is_demo.is_(False),
    ).order_by(MintTask.scheduled_for_utc.asc()))).scalars().all()
    formatted = []
    for task in tasks:
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
