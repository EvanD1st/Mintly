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
            messages.append((task.id, auth.snapshot['user_id'], task.status, task.updated_at))
    # Acknowledge after delivery. A crash may duplicate a notification, never lose it.
    # No transaction execution lock is held during FCM requests.
    for task_id, user_id, status, version in messages:
        try:
            sent = await NotificationService.send_notification('Automatic mint ' + status,
                task_id, category='mint_status', deep_link='mintly://queue', user_id=user_id)
        except Exception:
            sent = False
        async with AsyncSessionLocal() as db:
            await db.execute(update(MintTask).where(MintTask.id == task_id,
                MintTask.status == status, MintTask.updated_at == version,
                MintTask.notification_pending.is_(True)).values(notification_pending=not sent))
            await db.commit()


async def run():
    while True:
        try:
            await deliver_one()
        except Exception:
            pass
        await asyncio.sleep(15)


if __name__ == '__main__':
    asyncio.run(run())
