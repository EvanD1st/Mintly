"""Mintly Background Task Worker for discovery, task leasing, minting, and receipt tracking."""

import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, and_, or_
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import MintTask, MintAuthorization, Drop, MintStage, Wallet, ActivityEvent
from app.services.mint_executor import MintExecutor
from app.services.signer.base import SignerPolicy, SEADROP_V1_ADDRESS
from app.services.twikit_adapter import TwikitSourceAdapter
from app.services.notifier import NotificationService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("mintly.worker")


class MintlyWorker:
    """Distributed worker with lease locks, atomic two-phase submission, and receipt reconciliation."""

    def __init__(self):
        self.worker_id = f"worker_{uuid.uuid4().hex[:8]}"
        self.executor = MintExecutor()
        self.twikit = TwikitSourceAdapter()
        self.running = False
        self.lease_duration = timedelta(seconds=settings.WORKER_LEASE_DURATION_SECONDS)

    async def claim_ready_task(self, session) -> MintTask:
        """Atomically leases an armed task ready for submission using database leases.
        
        Prevents multiple workers from claiming the same task.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(MintTask)
            .where(
                and_(
                    MintTask.status == "armed",
                    MintTask.scheduled_for_utc <= now,
                    or_(
                        MintTask.worker_id.is_(None),
                        MintTask.lease_expires_at < now,
                    )
                )
            )
            .order_by(MintTask.scheduled_for_utc.asc())
            .limit(1)
        )
        task = (await session.execute(stmt)).scalar_one_or_none()
        if not task:
            return None

        # Acquire lease atomically
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

            if not drop or not stage or not auth:
                task.status = "failed"
                task.failure_reason = "Missing referenced drop, stage, or authorization record."
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
                authorized_minter=wallet.address if wallet else "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
                authorized_recipient=auth.recipient_address,
                allowed_nft_contract=drop.contract_address or "0x1234567890123456789012345678901234567890",
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
            nonce = task.assigned_nonce or 0
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
            if signed_res.get("is_simulated"):
                tx_hash = signed_res["transaction_hash"]
            else:
                tx_hash = await self.executor.broadcast_transaction(task.signed_tx_raw, drop.chain)

            task.status = "submitted"
            task.submitted_at = datetime.now(timezone.utc)
            task.explorer_url = f"https://basescan.org/tx/{tx_hash}" if drop.chain.lower() == "base" else f"https://etherscan.io/tx/{tx_hash}"

            session.add(ActivityEvent(
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
            )
            logger.info(f"[{self.worker_id}] Task {task.id} successfully broadcasted. Hash: {tx_hash}")

        except Exception as e:
            logger.error(f"[{self.worker_id}] Task execution failed: {e}", exc_info=True)
            task.status = "failed"
            task.failure_reason = str(e)
            await session.commit()

    async def reconcile_pending_tasks(self, session):
        """Checks confirmation status of in-flight submitted tasks."""
        stmt = select(MintTask).where(MintTask.status == "submitted")
        tasks = (await session.execute(stmt)).scalars().all()

        for t in tasks:
            if not t.transaction_hash:
                continue

            drop = (await session.execute(select(Drop).where(Drop.id == t.drop_id))).scalar_one_or_none()
            chain = drop.chain if drop else "Base"

            res = await self.executor.reconcile_transaction(t.transaction_hash, chain, is_demo=t.is_demo)
            if res.get("status") == "confirmed":
                t.status = "confirmed"
                t.confirmed_at = datetime.now(timezone.utc)
                t.actual_gas_used = res.get("gas_used")
                t.actual_effective_gas_price = res.get("effective_gas_price")
                t.actual_total_cost_wei = res.get("total_fee_wei")
                t.block_number = res.get("block_number")

                session.add(ActivityEvent(
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
                )
                logger.info(f"Task {t.id} confirmed on-chain!")

            elif res.get("status") == "reverted":
                t.status = "failed"
                t.failure_reason = "Transaction reverted on-chain."
                t.actual_gas_used = res.get("gas_used")
                t.actual_total_cost_wei = res.get("total_fee_wei")
                await session.commit()
                logger.warning(f"Task {t.id} reverted on-chain.")

    async def run_discovery_poll(self, session):
        """Polls for latest drops via Twikit."""
        try:
            drops = await self.twikit.poll_latest_drops()
            if drops:
                logger.info(f"Discovered {len(drops)} new drops from {settings.X_MONITORED_USER}")
                await NotificationService.send_notification(
                    title="New Drops Detected",
                    body=f"LAKZONE posted {len(drops)} new drops for today.",
                    category="daily_list",
                    deep_link="mintly://drops",
                )
        except Exception as e:
            logger.warning(f"Discovery poll failed: {e}")

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

                    # 3. Periodic discovery poll every N loops
                    if iteration % 12 == 0:  # ~every 60 seconds if loop sleep is 5s
                        await self.run_discovery_poll(session)

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
