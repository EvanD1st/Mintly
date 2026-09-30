"""Task management, review, arming, disarming, and queue endpoints."""

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, verify_owner_authorization
from app.models import Drop, MintStage, Wallet, MintAuthorization, MintTask, ActivityEvent
from app.schemas.task import (
    DraftTaskRequest,
    DraftTaskResponse,
    ArmTaskRequest,
    TaskSchema,
    QueueResponse,
)
from app.services.parser import parse_eth_to_wei, format_wei_to_eth
from app.config import settings

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/draft", response_model=DraftTaskResponse)
async def draft_task_preview(req: DraftTaskRequest, db: AsyncSession = Depends(get_db)):
    """Validates inputs, performs exact integer accounting, and returns review summary."""
    drop = (await db.execute(select(Drop).options(selectinload(Drop.stages)).where(Drop.id == req.drop_id))).scalar_one_or_none()
    if not drop:
        raise HTTPException(status_code=404, detail="Drop not found.")

    stage = (await db.execute(select(MintStage).where(MintStage.id == req.stage_id))).scalar_one_or_none()
    if not stage or stage.drop_id != drop.id:
        raise HTTPException(status_code=404, detail="Stage not found for this drop.")

    wallet = (await db.execute(select(Wallet).where(Wallet.id == req.wallet_id))).scalar_one_or_none()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found.")

    wallet_label = wallet.label
    wallet_addr = wallet.address

    # Enforce quantity bounds
    if req.quantity > stage.limit_per_wallet:
        raise HTTPException(
            status_code=400,
            detail=f"Requested quantity {req.quantity} exceeds wallet stage limit {stage.limit_per_wallet}."
        )

    # Exact integer financial math in Wei
    fee_cap_wei = parse_eth_to_wei(req.fee_cap_eth)
    mint_total_wei = req.quantity * stage.price_wei
    total_spend_cap_wei = mint_total_wei + fee_cap_wei
    total_spend_eth_str = format_wei_to_eth(total_spend_cap_wei)

    # Signer readiness check
    is_signer_ready = True
    if not drop.is_supported_integration:
        is_signer_ready = False
        note = "Automatic minting is unavailable for independent mint sites without supported adapter."
    elif stage.stage_name.lower() not in ("public", "public stage"):
        is_signer_ready = False
        note = "Automatic minting supports public stages only; use the mint page for allowlists."
    elif drop.is_demo or (wallet and wallet.is_demo):
        is_signer_ready = True
        note = "Demo signing is ready. The real app must verify signing access before a task can be armed."
    else:
        is_ready = bool(settings.SIGNER_PRIVATE_KEY)
        is_signer_ready = is_ready
        note = "Server signer configured and ready." if is_ready else "Server signer private key not configured."

    return DraftTaskResponse(
        drop=drop,
        stage=stage,
        wallet_label=wallet_label,
        wallet_address=wallet_addr,
        chain=drop.chain,
        quantity=req.quantity,
        mint_price_each_eth=stage.price_eth_str,
        fee_cap_eth=req.fee_cap_eth,
        total_spend_cap_eth=total_spend_eth_str,
        total_spend_cap_wei=total_spend_cap_wei,
        is_signer_ready=is_signer_ready,
        signer_status_note=note,
    )


@router.post("/arm", response_model=TaskSchema)
async def arm_mint_task(
    req: ArmTaskRequest,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(verify_owner_authorization),
):
    """Explicitly arms a task after user confirmation, persisting durable authorization."""
    if not req.user_consent_confirmed:
        raise HTTPException(
            status_code=400,
            detail="User consent is required. Must authorize limits and acknowledge no inclusion guarantee."
        )

    drop = (await db.execute(select(Drop).options(selectinload(Drop.stages)).where(Drop.id == req.drop_id))).scalar_one_or_none()
    if not drop:
        raise HTTPException(status_code=404, detail="Drop not found.")

    if not drop.is_supported_integration:
        raise HTTPException(
            status_code=400,
            detail="Cannot arm an unsupported drop integration."
        )

    stage = (await db.execute(select(MintStage).where(MintStage.id == req.stage_id))).scalar_one_or_none()
    if not stage or stage.drop_id != drop.id:
        raise HTTPException(status_code=404, detail="Stage not found for this drop.")
    if stage.stage_name.lower() not in ("public", "public stage"):
        raise HTTPException(status_code=400, detail="Automatic minting supports public stages only.")

    wallet = (await db.execute(select(Wallet).where(Wallet.id == req.wallet_id))).scalar_one_or_none()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found.")
    if req.quantity > stage.limit_per_wallet:
        raise HTTPException(status_code=400, detail="Quantity exceeds this stage's wallet limit.")
    if not drop.is_demo and (wallet.is_demo or wallet.signing_capability != "isolated_server_signer"):
        raise HTTPException(status_code=400, detail="This wallet cannot authorize an automatic mint.")
    if not drop.is_demo:
        raise HTTPException(status_code=409, detail="Live automatic minting is not enabled or certified.")

    wallet_id = wallet.id
    wallet_addr = wallet.address

    existing = (await db.execute(select(MintTask).where(MintTask.idempotency_key == req.idempotency_key))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Idempotency key has already been used. Refresh the queue.")

    # Exact integer math
    fee_cap_wei = parse_eth_to_wei(req.fee_cap_eth)
    mint_total_wei = req.quantity * stage.price_wei
    total_spend_cap_wei = mint_total_wei + fee_cap_wei

    now = datetime.now(timezone.utc)

    # 1. Create immutable authorization
    auth = MintAuthorization(
        wallet_id=wallet_id,
        drop_id=drop.id,
        stage_id=stage.id,
        quantity=req.quantity,
        max_price_per_token_wei=stage.price_wei,
        max_fee_wei=fee_cap_wei,
        total_spend_cap_wei=total_spend_cap_wei,
        recipient_address=wallet_addr,
        user_consent_text="I authorize this task within the limits above. A successful mint is not guaranteed.",
        authorized_at=now,
    )
    db.add(auth)
    await db.flush()

    # 2. Check for duplicate armed tasks on same drop & cancel prior armed tasks
    await db.execute(
        update(MintTask)
        .where(MintTask.drop_id == drop.id, MintTask.status == "armed")
        .values(status="disarmed")
    )

    # 3. Create MintTask
    task = MintTask(
        authorization_id=auth.id,
        wallet_id=wallet_id,
        drop_id=drop.id,
        stage_id=stage.id,
        status="armed",
        is_demo=drop.is_demo,
        idempotency_key=req.idempotency_key,
        scheduled_for_utc=stage.start_time_utc,
        expires_at_utc=stage.start_time_utc + timedelta(hours=1),
    )
    db.add(task)

    # 4. Activity Event
    label = "Demo task armed" if drop.is_demo else "Mint task armed"
    db.add(ActivityEvent(
        event_type="task_armed",
        label=label,
        detail=f"{drop.name} · {req.quantity} NFTs",
        icon_name="timer",
        is_demo=drop.is_demo,
    ))
    await db.commit()

    # Format WAT time label
    wat_time = stage.start_time_utc.astimezone(ZoneInfo("Africa/Lagos")).strftime("%H:%M")

    return TaskSchema(
        id=task.id,
        wallet_id=task.wallet_id,
        drop_id=task.drop_id,
        stage_id=task.stage_id,
        status=task.status,
        is_demo=task.is_demo,
        scheduled_for_utc=task.scheduled_for_utc,
        expires_at_utc=task.expires_at_utc,
        quantity=req.quantity,
        unit_price_eth=stage.price_eth_str,
        fee_cap_eth=req.fee_cap_eth,
        total_cap_eth=format_wei_to_eth(total_spend_cap_wei),
        drop_name=drop.name,
        chain=drop.chain,
        stage_name=stage.stage_name,
        time_wat_label=f"{wat_time} WAT",
        icon_name=drop.icon_name,
    )


@router.post("/{task_id}/disarm")
async def disarm_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(verify_owner_authorization),
):
    """Safely disarms an armed task before submission.
    
    Protects against race condition: already submitted tasks cannot be disarmed.
    """
    task = (await db.execute(select(MintTask).where(MintTask.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if task.status == "disarmed":
        return {"message": "Task already disarmed.", "task_id": task_id, "status": "disarmed"}

    if task.status != "armed":
        raise HTTPException(
            status_code=409,
            detail=f"Task is already {task.status}. Transactions in flight or confirmed cannot be canceled by disarming."
        )

    changed = await db.execute(
        update(MintTask)
        .where(MintTask.id == task_id, MintTask.status == "armed")
        .values(status="disarmed")
        .returning(MintTask.id)
    )
    if changed.scalar_one_or_none() is None:
        raise HTTPException(status_code=409, detail="Task is already in flight and cannot be canceled by disarming.")
    drop = (await db.execute(select(Drop).where(Drop.id == task.drop_id))).scalar_one_or_none()
    drop_name = drop.name if drop else "NFT drop"

    db.add(ActivityEvent(
        event_type="task_disarmed",
        label="Demo task disarmed" if task.is_demo else "Task disarmed",
        detail=f"{drop_name} disarmed",
        icon_name="circle-pause",
        is_demo=task.is_demo,
    ))
    await db.commit()

    return {"message": "Task disarmed successfully.", "task_id": task_id, "status": "disarmed"}


@router.get("/queue", response_model=QueueResponse)
async def list_mint_queue(db: AsyncSession = Depends(get_db)):
    """Returns active and recent tasks in the mint queue."""
    stmt = select(MintTask).order_by(MintTask.scheduled_for_utc.asc())
    tasks = (await db.execute(stmt)).scalars().all()

    formatted_tasks = []
    for t in tasks:
        drop = (await db.execute(select(Drop).where(Drop.id == t.drop_id))).scalar_one_or_none()
        stage = (await db.execute(select(MintStage).where(MintStage.id == t.stage_id))).scalar_one_or_none()
        auth = (await db.execute(select(MintAuthorization).where(MintAuthorization.id == t.authorization_id))).scalar_one_or_none()

        wat_time = t.scheduled_for_utc.astimezone(ZoneInfo("Africa/Lagos")).strftime("%H:%M")
        
        qty = auth.quantity if auth else 1
        unit_eth = stage.price_eth_str if stage else "0"
        total_eth = format_wei_to_eth(auth.total_spend_cap_wei) if auth else "0"
        fee_eth = format_wei_to_eth(auth.max_fee_wei) if auth else "0"

        formatted_tasks.append(TaskSchema(
            id=t.id,
            wallet_id=t.wallet_id,
            drop_id=t.drop_id,
            stage_id=t.stage_id,
            status=t.status,
            is_demo=t.is_demo,
            scheduled_for_utc=t.scheduled_for_utc,
            expires_at_utc=t.expires_at_utc,
            quantity=qty,
            unit_price_eth=unit_eth,
            fee_cap_eth=fee_eth,
            total_cap_eth=total_eth,
            drop_name=drop.name if drop else "Unknown Drop",
            chain=drop.chain if drop else "Base",
            stage_name=stage.stage_name if stage else "Public",
            time_wat_label=f"{wat_time} WAT",
            icon_name=drop.icon_name if drop else "gem",
            transaction_hash=t.transaction_hash,
            explorer_url=t.explorer_url,
            failure_reason=t.failure_reason,
            submitted_at=t.submitted_at,
            confirmed_at=t.confirmed_at,
            actual_total_cost_wei=t.actual_total_cost_wei,
        ))

    return QueueResponse(tasks=formatted_tasks, total_count=len(formatted_tasks))
