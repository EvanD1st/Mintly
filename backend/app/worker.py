"""Mintly Background Task Worker for discovery, task leasing, minting, and receipt tracking."""

import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, and_, or_
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import MintTask, MintAuthorization, MintPlan, Drop, MintStage, Wallet, User, ActivityEvent
from app.services.mint_executor import MintExecutor
from app.services.signer.base import SignerPolicy, SEADROP_V1_ADDRESS
from app.services.notifier import NotificationService
from app.services.x_feed import sync_x_drops
from app.services.mint_plans import refresh_mint_plan
from app.services.opensea import OpenSeaUnavailable
from app.services.permission_relayer import process_one_permission

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("mintly.worker")


class MintlyWorker:
    """Distributed worker with lease locks, atomic two-phase submission, and receipt reconciliation."""

    def __init__(self):
        self.worker_id = f"worker_{uuid.uuid4().hex[:8]}"
        self.executor = MintExecutor()
        self.running = False
        self.lease_duration = timedelta(seconds=settings.WORKER_LEASE_DURATION_SECONDS)

    async def claim_ready_task(self, session) -> MintTask:
        """Lease one task under a PostgreSQL row lock.

        SKIP LOCKED keeps competing workers from selecting the same task.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(MintTask).join(Wallet, Wallet.id == MintTask.wallet_id).join(User, User.id == Wallet.user_id)
            .where(
                and_(
                    MintTask.status == "armed",
                    User.automation_paused.is_(False),
                    MintTask.execution_mode.is_(None),
                    MintTask.scheduled_for_utc <= now,
                    MintTask.expires_at_utc > now,
                    or_(
                        MintTask.worker_id.is_(None),
                        MintTask.lease_expires_at < now,
                    )
                )
            )
            .order_by(MintTask.scheduled_for_utc.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        task = (await session.execute(stmt)).scalar_one_or_none()
        if not task:
            return None

        # The row lock remains held until this commit.
        task.worker_id = self.worker_id
        task.lease_expires_at = now + self.lease_duration
        task.status = "preparing"
        await session.commit()
        await session.refresh(task)
        logger.info(f"[{self.worker_id}] Acquired lease on task {task.id} (Drop: {task.drop_id})")
        return task

    async def execute_task(self, task: MintTask, session):
        """Prepares calldata, enforces policy, signs, persists hash, and broadcasts."""
        try:
            # 1. Fetch related entities
            drop = (await session.execute(select(Drop).where(Drop.id == task.drop_id))).scalar_one_or_none()
            stage = (await session.execute(select(MintStage).where(MintStage.id == task.stage_id))).scalar_one_or_none()
            wallet = (await session.execute(select(Wallet).where(Wallet.id == task.wallet_id))).scalar_one_or_none()
            auth = (await session.execute(select(MintAuthorization).where(MintAuthorization.id == task.authorization_id))).scalar_one_or_none()

            if not drop or not stage or not auth or not wallet:
                task.status = "failed"
                task.failure_reason = "Missing referenced drop, stage, or authorization record."
                await session.commit()
                return

            if (
                stage.drop_id != drop.id or auth.drop_id != drop.id
                or auth.stage_id != stage.id or auth.wallet_id != wallet.id
                or auth.is_revoked
            ):
                task.status = "failed"
                task.failure_reason = "Authorization no longer matches the task or was revoked."
                await session.commit()
                return

            # Live execution remains closed until signer, nonce, eligibility and
            # chain reconciliation are certified together.
            if not task.is_demo:
                task.status = "failed"
                task.failure_reason = "Live automatic minting is disabled."
                await session.commit()
                return

            # Check if task expired
            now = datetime.now(timezone.utc)
            if now > task.expires_at_utc:
                task.status = "expired"
                task.failure_reason = "Drop submission window expired before execution."
                await session.commit()
                logger.warning(f"Task {task.id} expired at {task.expires_at_utc}")
                return

            # 2. Build Signer Policy
            policy = SignerPolicy(
                chain_id=drop.chain_id,
                authorized_minter=wallet.address,
                authorized_recipient=auth.recipient_address,
                allowed_nft_contract=drop.contract_address,
                allowed_seadrop_contract=SEADROP_V1_ADDRESS,
                authorized_quantity=auth.quantity,
                max_price_per_token_wei=auth.max_price_per_token_wei,
                max_fee_wei=auth.max_fee_wei,
                total_spend_cap_wei=auth.total_spend_cap_wei,
                stage_name=stage.stage_name,
            )

            # 3. Build Calldata
            calldata = self.executor.build_mint_public_calldata(
                nft_contract=policy.allowed_nft_contract,
                fee_recipient="0x0000000000000000000000000000000000000000",
                minter_if_not_payer=policy.authorized_recipient,
                quantity=auth.quantity,
            )
            task.prepared_calldata = calldata

            # 4. Prepare and Sign Transaction
            from app.services import automatic
            await automatic.lock_execution(session)
            await session.refresh(task)
            if task.status != 'preparing':
                await session.commit()
                return
            await automatic.require_running(session, wallet.user_id)
            nonce = task.assigned_nonce if task.assigned_nonce is not None else 0
            signed_res = self.executor.prepare_and_sign(
                policy=policy,
                from_address=policy.authorized_minter,
                nonce=nonce,
                calldata=calldata,
            )

            # 5. Persist submission intent & signed hash BEFORE broadcast
            task.status = "submitting"
            task.transaction_hash = signed_res["transaction_hash"]
            task.signed_tx_raw = signed_res.get("raw_transaction")
            task.broadcast_attempts += 1
            await session.commit()
            logger.info(f"[{self.worker_id}] Task {task.id} persisted signed tx {task.transaction_hash}. Broadcasting...")

            # 6. Broadcast transaction to network
            if signed_res.get("is_simulated") and task.is_demo:
                tx_hash = signed_res["transaction_hash"]
            else:
                if signed_res.get("is_simulated"):
                    raise RuntimeError("A simulated signature cannot be submitted as a live task.")
                tx_hash = await self.executor.broadcast_transaction(task.signed_tx_raw, drop.chain)

            task.status = "submitted"
            task.submitted_at = datetime.now(timezone.utc)
            task.explorer_url = f"https://basescan.org/tx/{tx_hash}" if drop.chain.lower() == "base" else f"https://etherscan.io/tx/{tx_hash}"

            session.add(ActivityEvent(
                user_id=wallet.user_id,
                event_type="task_submitted",
                label="Transaction submitted",
                detail=f"{drop.name} ({auth.quantity} NFTs) submitted to {drop.chain}",
                icon_name="send",
                is_demo=task.is_demo,
            ))
            await session.commit()

            await NotificationService.send_notification(
                title="Mint Transaction Submitted",
                body=f"Submitted mint for {drop.name}. Tracking confirmation...",
                category="mint_status",
                deep_link=f"mintly://queue",
                user_id=wallet.user_id,
            )
            logger.info(f"[{self.worker_id}] Task {task.id} successfully broadcasted. Hash: {tx_hash}")

        except Exception as e:
            logger.error(f"[{self.worker_id}] Task execution failed: {e}", exc_info=True)
            # An RPC error after a real send is ambiguous. Keep the signed payload
            # and hash for reconciliation; never create a different transaction.
            if task.status != "submitting" or task.is_demo:
                task.status = "failed"
            task.failure_reason = str(e)
            await session.commit()

    async def reconcile_pending_tasks(self, session):
        """Recover expired preparation leases and inspect persisted signed hashes."""
        now = datetime.now(timezone.utc)
        abandoned = (await session.execute(
            select(MintTask).where(
                MintTask.status == "preparing",
                MintTask.execution_mode.is_(None),
                MintTask.lease_expires_at < now,
            ).with_for_update(skip_locked=True)
        )).scalars().all()
        for t in abandoned:
            t.status = "armed" if t.expires_at_utc > now else "expired"
            t.worker_id = None
            t.lease_expires_at = None
        if abandoned:
            await session.commit()

        stmt = select(MintTask).where(MintTask.status.in_(("submitting", "submitted")), MintTask.execution_mode.is_(None))
        tasks = (await session.execute(stmt)).scalars().all()

        for t in tasks:
            if not t.transaction_hash:
                continue

            drop = (await session.execute(select(Drop).where(Drop.id == t.drop_id))).scalar_one_or_none()
            chain = drop.chain if drop else "Base"

            res = await self.executor.reconcile_transaction(t.transaction_hash, chain, is_demo=t.is_demo)
            if res.get("status") == "confirmed":
                wallet = await session.get(Wallet, t.wallet_id)
                t.status = "confirmed"
                t.confirmed_at = datetime.now(timezone.utc)
                t.actual_gas_used = res.get("gas_used")
                t.actual_effective_gas_price = res.get("effective_gas_price")
                t.actual_total_cost_wei = res.get("total_fee_wei")
                t.block_number = res.get("block_number")

                session.add(ActivityEvent(
                    user_id=wallet.user_id if wallet else None,
                    event_type="task_confirmed",
                    label="Mint confirmed!",
                    detail=f"{drop.name if drop else 'NFT'} confirmed in block {t.block_number}",
                    icon_name="check-circle",
                    is_demo=t.is_demo,
                ))
                await session.commit()

                await NotificationService.send_notification(
                    title="Mint Confirmed! 🎉",
                    body=f"Your mint for {drop.name if drop else 'NFT'} was confirmed on-chain.",
                    category="mint_status",
                    deep_link="mintly://queue",
                    user_id=wallet.user_id if wallet else None,
                )
                logger.info(f"Task {t.id} confirmed on-chain!")

            elif res.get("status") == "reverted":
                t.status = "failed"
                t.failure_reason = "Transaction reverted on-chain."
                t.actual_gas_used = res.get("gas_used")
                t.actual_total_cost_wei = res.get("total_fee_wei")
                await session.commit()
                logger.warning(f"Task {t.id} reverted on-chain.")

            elif t.status == "submitting" and t.is_demo:
                # A demo signature is persisted before the simulated submit.
                t.status = "submitted"
                t.submitted_at = datetime.now(timezone.utc)
                await session.commit()

    async def run_discovery_poll(self, session):
        """Import only @lakzonevn drops; announce persisted records once."""
        try:
            added = await sync_x_drops(session)
            if added:
                await NotificationService.send_notification(
                    title="New drops from @lakzonevn",
                    body=f"{added} new drops are available to review.",
                    category="daily_list",
                    deep_link="mintly://drops",
                )
        except Exception as e:
            logger.warning(f"Discovery poll failed: {e}")

    async def check_due_mint_plan(self, session):
        """Check at most one wallet/stage per call to respect the free API limit."""
        now = datetime.now(timezone.utc)
        plan = (await session.execute(select(MintPlan).join(User, User.id == MintPlan.user_id).where(
            MintPlan.archived_at.is_(None), MintPlan.next_check_at.is_not(None), MintPlan.next_check_at <= now,
            User.is_active.is_(True), User.deleted_at.is_(None),
        ).order_by(MintPlan.next_check_at.asc()).limit(1)
          .with_for_update(skip_locked=True))).scalar_one_or_none()
        if plan is None:
            return
        wallet = (await session.execute(select(Wallet).where(
            Wallet.id == plan.wallet_id, Wallet.user_id == plan.user_id, Wallet.archived_at.is_(None),
        ))).scalar_one_or_none()
        if wallet is None:
            plan.status = "error"
            plan.status_note = "Linked wallet is unavailable."
            plan.next_check_at = None
            await session.commit()
            return
        try:
            await refresh_mint_plan(plan, wallet, now=now, db=session)
        except OpenSeaUnavailable as error:
            plan.status = "error"
            plan.status_note = str(error)
            plan.next_check_at = now + timedelta(minutes=5)
        notify = plan.status == "ready_for_approval" and plan.notified_stage_uuid != plan.stage_uuid
        if notify:
            plan.notified_stage_uuid = plan.stage_uuid
        await session.commit()
        if notify:
            await NotificationService.send_notification(
                title="OpenSea mint ready for MetaMask",
                body=f"{plan.collection_name} is ready for your wallet. Review the price and gas in MetaMask.",
                category="mint_status", deep_link="mintly://queue", user_id=plan.user_id,
            )

    async def start(self):
        """Main worker execution loop."""
        self.running = True
        logger.info(f"Starting MintlyWorker [{self.worker_id}] (poll interval: {settings.WORKER_POLL_INTERVAL_SECONDS}s)")
        
        iteration = 0
        while self.running:
            try:
                async with AsyncSessionLocal() as session:
                    # 1. Check for ready mint tasks to lease & execute
                    task = await self.claim_ready_task(session)
                    if task:
                        await self.execute_task(task, session)

                    # 2. Reconcile in-flight submitted tasks
                    await self.reconcile_pending_tasks(session)
                    await process_one_permission(session)

                    # 3. Refresh the real feed roughly every five minutes.
                    if iteration % 60 == 0:
                        await self.run_discovery_poll(session)

                    # Free OpenSea key: at most four timed wallet checks per minute.
                    if iteration % 3 == 0:
                        await self.check_due_mint_plan(session)

                iteration += 1
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    def stop(self):
        self.running = False


async def main():
    worker = MintlyWorker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
