"""Discovery queues notices without credentials; notification worker delivers them."""
import asyncio,hashlib
from datetime import datetime,timezone,timedelta
from sqlalchemy import select,or_,update
from app.models import SourceAlert
from app.database import AsyncSessionLocal


async def enqueue(db,event,detail,now=None):
    from app.services.x_feed import insert_for
    now=now or datetime.now(timezone.utc)
    key=hashlib.sha256(f'{now:%Y%m%d}|{event}'.encode()).hexdigest()
    await db.execute(insert_for(db)(SourceAlert).values(id=key,detail=detail,status='pending',attempts=0,
        next_attempt_at=now,created_at=now,updated_at=now).on_conflict_do_nothing(index_elements=['id']))
    await db.commit()


async def deliver(factory=AsyncSessionLocal,notify=None,*,now=None):
    from app.services.notifier import NotificationService
    notify=notify or NotificationService.send_notification
    now=now or datetime.now(timezone.utc)
    async with factory() as db:
        row=await db.scalar(select(SourceAlert).where(SourceAlert.status=='pending',SourceAlert.next_attempt_at<=now,
            or_(SourceAlert.lease_until.is_(None),SourceAlert.lease_until<=now))
            .order_by(SourceAlert.created_at).with_for_update(skip_locked=True).limit(1))
        if not row:return False
        row.attempts+=1;row.lease_until=now+timedelta(seconds=90)
        key,detail,attempts,lease=row.id,row.detail,row.attempts,row.lease_until
        await db.commit()
    try:
        sent=await asyncio.wait_for(notify('Discovery needs attention',detail,category='source_health',
            data={'notification_id':key},deep_link='mintly://drops'),15)
    except Exception:sent=False
    async with factory() as db:
        await db.execute(update(SourceAlert).where(SourceAlert.id==key,SourceAlert.lease_until==lease).values(
            status='sent' if sent else 'failed' if attempts>=5 else 'pending',lease_until=None,
            next_attempt_at=now+timedelta(seconds=min(900,60*2**(attempts-1)))))
        await db.commit()
    return True
