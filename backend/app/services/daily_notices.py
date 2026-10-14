"""Database/FCM only. No mint execution lock, provider calls or signer access."""
import asyncio
import hashlib
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select,or_,update
from app.database import AsyncSessionLocal
from app.models import DailyListNotice,SourcePost,Drop,NotificationDevice,User
from app.services.feed_checks import supported
from app.services.notifier import NotificationService

async def available(db,day):
    rows=(await db.execute(select(Drop,SourcePost).join(SourcePost).where(
        SourcePost.list_date==day,Drop.is_demo.is_(False),or_(SourcePost.is_manual_import.is_(True),
        SourcePost.author_username=='lakzonevn')).order_by(SourcePost.posted_at))).all()
    return next((post.id for drop,post in rows if supported(drop)),None)

async def poll(factory=AsyncSessionLocal,*,now=None):
    now=now or datetime.now(timezone.utc);day=now.astimezone(ZoneInfo('Africa/Lagos')).date()
    async with factory() as db:
        post=await available(db,day)
        if not post:return 0
        devices=(await db.scalars(select(NotificationDevice).join(User).where(
            NotificationDevice.is_active.is_(True),User.is_active.is_(True),User.deleted_at.is_(None)))).all()
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        insert=pg_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
        count=0
        for device in devices:
            if not (device.preferences or {}).get('daily_list',True):continue
            key=hashlib.sha256(f'{day}|{device.id}|{device.user_id}'.encode()).hexdigest()
            result=await db.execute(insert(DailyListNotice).values(id=key,list_date=day,device_id=device.id,
                user_id=device.user_id,source_post_id=post,status='pending',attempts=0,next_attempt_at=now,
                created_at=now,updated_at=now).on_conflict_do_nothing(index_elements=['list_date','device_id','user_id']))
            count+=max(0,result.rowcount)
        await db.commit();return count

async def deliver(factory=AsyncSessionLocal,notify=None,*,now=None):
    now=now or datetime.now(timezone.utc);day=now.astimezone(ZoneInfo('Africa/Lagos')).date()
    notify=notify or NotificationService.send_notification
    async with factory() as db:
        # Old lists are never announced after their WAT day ends.
        await db.execute(update(DailyListNotice).where(DailyListNotice.list_date<day,
            DailyListNotice.status=='pending').values(status='expired',lease_until=None))
        row=await db.scalar(select(DailyListNotice).where(DailyListNotice.list_date==day,
            DailyListNotice.status=='pending',DailyListNotice.next_attempt_at<=now,
            or_(DailyListNotice.lease_until.is_(None),DailyListNotice.lease_until<=now))
            .order_by(DailyListNotice.created_at,DailyListNotice.id).with_for_update(skip_locked=True).limit(1))
        if not row:await db.commit();return False
        device=await db.get(NotificationDevice,row.device_id);user=await db.get(User,row.user_id)
        if not device or not device.is_active or device.user_id!=row.user_id or not user or not user.is_active or user.deleted_at or not (device.preferences or {}).get('daily_list',True):
            row.status='suppressed';await db.commit();return True
        if not await available(db,day):
            row.status='expired';await db.commit();return True
        row.lease_until=now+timedelta(seconds=90);row.attempts+=1
        key,lease,uid,did,attempts=row.id,row.lease_until,row.user_id,row.device_id,row.attempts
        await db.commit() # Release all database locks before FCM delivery.
    try:
        sent=await asyncio.wait_for(notify('Today’s mint list is ready',
            'Open Today to check the available collections and your wallet’s eligibility.',category='daily_list',
            deep_link='mintly://drops',user_id=uid,device_id=did,
            data={'notification_id':key,'list_date':day.isoformat()}),15)
    except Exception:sent=False
    async with factory() as db:
        await db.execute(update(DailyListNotice).where(DailyListNotice.id==key,
            DailyListNotice.status=='pending',DailyListNotice.lease_until==lease).values(
                status='sent' if sent else 'failed' if attempts>=5 else 'pending',lease_until=None,
                sent_at=now if sent else None,next_attempt_at=now+timedelta(seconds=min(60*2**(attempts-1),900))))
        await db.commit()
    return True
