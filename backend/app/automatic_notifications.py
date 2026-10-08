"""Notification outbox consumer; FCM latency cannot stall transaction execution."""
import asyncio
from sqlalchemy import select, update
from app.database import AsyncSessionLocal
from app.models import MintTask, MintAuthorization
from app.services.notifier import NotificationService


async def deliver_one():
    async with AsyncSessionLocal() as db:
        tasks = (await db.execute(select(MintTask).where(MintTask.notification_pending.is_(True))
            .order_by(MintTask.updated_at).limit(25))).scalars().all()
        messages = []
        for task in tasks:
            auth = await db.get(MintAuthorization, task.authorization_id)
            from app.services.copy_mints import is_funding_note
            funding = task.copy_rule_id and task.status == 'failed' and not task.signed_tx_raw and is_funding_note(
                task.failure_reason, auth.snapshot['chain_id'])
            messages.append((task.id, auth.snapshot['user_id'], task.status, task.updated_at,
                task.failure_reason if funding else None))
    # Acknowledge after delivery. A crash may duplicate a notification, never lose it.
    # No transaction execution lock is held during FCM requests.
    for task_id, user_id, status, version, funding_note in messages:
        try:
            sent = await NotificationService.send_notification('Copy mint skipped' if funding_note else 'Automatic mint ' + status,
                funding_note or task_id, category='mint_status', deep_link='mintly://queue', user_id=user_id)
        except Exception:
            sent = False
        async with AsyncSessionLocal() as db:
            await db.execute(update(MintTask).where(MintTask.id == task_id,
                MintTask.status == status, MintTask.updated_at == version,
                MintTask.notification_pending.is_(True)).values(notification_pending=not sent))
            await db.commit()


async def run():
    from app.services import wallet_alerts
    import time
    last_alert_check=-1000
    while True:
        try:
            await deliver_one()
            if time.monotonic()-last_alert_check>=60:
                await wallet_alerts.poll()
                last_alert_check=time.monotonic()
            await wallet_alerts.deliver()
        except Exception:
            pass
        await asyncio.sleep(15)


if __name__ == '__main__':
    asyncio.run(run())
