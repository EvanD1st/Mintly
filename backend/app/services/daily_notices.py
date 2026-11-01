"""Database/FCM only. No mint execution lock, provider calls or signer access."""
import asyncio
import hashlib
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select,or_,update
from app.database import AsyncSessionLocal
from app.models import DailyListNotice,SourcePost,Drop,NotificationDevice,User
from app.services.feed_sources import daily_collections
from app.services.feed_checks import supported
from app.services.notifier import NotificationService

async def available(db,day):
    posts={}
    for group in await daily_collections(db,day):
        drop=group['drop']
        if drop.status_kind=='unsupported' or not drop.mint_page_url.startswith('https://'):continue
        for post,_ in group['mentions']:
            if post.list_date==day and post.is_daily_list:posts[post.id]=post
    return sorted(posts.values(),key=lambda p:(p.list_sequence or 1,p.id))

async def poll(factory=AsyncSessionLocal,*,now=None):
    now=now or datetime.now(timezone.utc);day=now.astimezone(ZoneInfo('Africa/Lagos')).date()
    async with factory() as db:
        posts=await available(db,day)
        if not posts:return 0
        devices=(await db.scalars(select(NotificationDevice).join(User).where(
            NotificationDevice.is_active.is_(True),User.is_active.is_(True),User.deleted_at.is_(None)))).all()
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        insert=pg_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
        count=0
        for post in posts:
            if not post.notice_eligible:continue
            for device in devices:
                if not (device.preferences or {}).get('daily_list',True):continue
                key=hashlib.sha256(f'{post.id}|{device.id}|{device.user_id}'.encode()).hexdigest()
                result=await db.execute(insert(DailyListNotice).values(id=key,list_date=day,device_id=device.id,
                    user_id=device.user_id,source_post_id=post.id,status='pending',attempts=0,next_attempt_at=now,
                    created_at=now,updated_at=now).on_conflict_do_nothing(index_elements=['source_post_id','device_id','user_id']))
                count+=max(0,result.rowcount)
        await db.commit();return count

async def deliver(factory=AsyncSessionLocal,notify=None,*,now=None):
    now=now or datetime.now(timezone.utc);day=now.astimezone(ZoneInfo('Africa/Lagos')).date()
    notify=notify or NotificationService.send_notification
    async with factory() as db:
        # Old lists are never announced after their WAT day ends.
        await db.execute(update(DailyListNotice).where(DailyListNotice.list_date<day,
            DailyListNotice.status=='pending').values(status='expired',lease_until=None))
        row=await db.scalar(select(DailyListNotice).join(SourcePost,SourcePost.id==DailyListNotice.source_post_id).where(DailyListNotice.list_date==day,
            DailyListNotice.status=='pending',DailyListNotice.next_attempt_at<=now,
            or_(DailyListNotice.lease_until.is_(None),DailyListNotice.lease_until<=now))
            .order_by(SourcePost.list_sequence,DailyListNotice.created_at,DailyListNotice.id).with_for_update(of=DailyListNotice,skip_locked=True).limit(1))
        if not row:await db.commit();return False
        device=await db.get(NotificationDevice,row.device_id);user=await db.get(User,row.user_id)
        if not device or not device.is_active or device.user_id!=row.user_id or not user or not user.is_active or user.deleted_at or not (device.preferences or {}).get('daily_list',True):
            row.status='suppressed';await db.commit();return True
        posts=await available(db,day)
        post=next((p for p in posts if p.id==row.source_post_id),None)
        if not post:
            row.status='expired';await db.commit();return True
        # Maintain publication order per account/device, including delayed retries.
        earlier=await db.scalar(select(DailyListNotice.id).join(SourcePost,SourcePost.id==DailyListNotice.source_post_id).where(
            DailyListNotice.user_id==row.user_id,DailyListNotice.device_id==row.device_id,
            DailyListNotice.list_date==day,DailyListNotice.status=='pending',DailyListNotice.id!=row.id,
            SourcePost.list_sequence<(post.list_sequence or 1)).limit(1))
        if earlier:await db.commit();return False
        sequence=post.list_sequence or 1
        title="Today's mint list is ready" if sequence==1 else 'Second list just dropped' if sequence==2 else 'Another mint list just dropped'
        groups=await daily_collections(db,day)
        additions=sum(1 for g in groups if any(p.id==post.id for p,_ in g['mentions']) and
            not any(p.list_date<day or (p.list_sequence or 1)<sequence for p,_ in g['mentions']))
        body=(f'{additions} new collection(s). Open Today to see the highlighted additions.' if additions else
            'Collections from this list are already on Today. Open Today to review its source details.')
        row.lease_until=now+timedelta(seconds=90);row.attempts+=1
        key,lease,uid,did,attempts=row.id,row.lease_until,row.user_id,row.device_id,row.attempts
        await db.commit() # Release all database locks before FCM delivery.
    try:
        sent=await asyncio.wait_for(notify(title,body,category='daily_list',
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
