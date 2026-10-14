"""Durable daily alerts follow Today visibility and current device ownership."""
import asyncio
from datetime import datetime,timezone,timedelta
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import async_sessionmaker
from firebase_admin import messaging
from app.models import User,NotificationDevice,SourcePost,Drop,DailyListNotice,MintTask
from app.services import daily_notices,notifier
from app.services.notifier import NotificationService
from app.config import settings
NOW=datetime(2026,10,14,5,tzinfo=timezone.utc)
async def setup(db,monkeypatch,offset=0,chain=8453):
 monkeypatch.setattr(settings,'ENABLE_BASE_AUTOMATIC',True)
 users=(await db.scalars(select(User).order_by(User.username))).all()
 post=SourcePost(post_id='123456789',author_username='lakzonevn',full_text='Daily mints',posted_at=NOW,
  list_date=(NOW+timedelta(days=offset)).date(),parser_version=1,is_manual_import=False)
 db.add(post);await db.flush()
 db.add(Drop(id='daily',source_post_id=post.id,name='Collection',chain='Base',chain_id=chain,
  mint_page_url='https://opensea.io/collection/test',is_demo=False))
 devices=[NotificationDevice(user_id=u.id,device_token='test-notification-token-'+str(i),is_active=True,
  preferences={'daily_list':True}) for i,u in enumerate(users)]
 db.add_all(devices);await db.commit()
 return users,devices,async_sessionmaker(db.bind,expire_on_commit=False)
@pytest.mark.parametrize('offset,chain',[(-1,8453),(1,8453),(0,12345)])
async def test_only_current_supported_today_list_enqueues(test_db,monkeypatch,offset,chain):
 _,_,factory=await setup(test_db,monkeypatch,offset,chain)
 assert await daily_notices.poll(factory,now=NOW)==0
 assert await test_db.scalar(select(func.count()).select_from(DailyListNotice))==0
async def test_once_per_day_owner_device_and_no_mint_side_effects(test_db,monkeypatch):
 users,devices,factory=await setup(test_db,monkeypatch)
 assert await daily_notices.poll(factory,now=NOW)==2
 assert await daily_notices.poll(factory,now=NOW)==0
 notify=AsyncMock(return_value=True)
 assert await daily_notices.deliver(factory,notify,now=NOW)
 assert await daily_notices.deliver(factory,notify,now=NOW)
 assert not await daily_notices.deliver(factory,notify,now=NOW)
 assert {c.kwargs['device_id'] for c in notify.await_args_list}=={d.id for d in devices}
 assert all(c.kwargs['category']=='daily_list' and c.kwargs['deep_link']=='mintly://drops' for c in notify.await_args_list)
 assert await daily_notices.poll(factory,now=NOW)==0
 assert await test_db.scalar(select(func.count()).select_from(MintTask))==0
async def test_failures_retry_after_backoff_and_survive_worker_restart(test_db,monkeypatch):
 _,devices,factory=await setup(test_db,monkeypatch);devices[1].preferences={'daily_list':False};await test_db.commit()
 await daily_notices.poll(factory,now=NOW)
 fail=AsyncMock(return_value=False);assert await daily_notices.deliver(factory,fail,now=NOW)
 row=await test_db.scalar(select(DailyListNotice).execution_options(populate_existing=True))
 assert row.attempts==1 and row.next_attempt_at.replace(tzinfo=timezone.utc)==NOW+timedelta(seconds=60)
 assert not await daily_notices.deliver(factory,fail,now=NOW+timedelta(seconds=59))
 good=AsyncMock(return_value=True)
 assert await daily_notices.deliver(async_sessionmaker(test_db.bind,expire_on_commit=False),good,now=NOW+timedelta(seconds=61))
 await test_db.refresh(row);assert row.status=='sent' and row.attempts==2
@pytest.mark.parametrize('change',['opt_out','inactive','owner','deleted','unavailable'])
async def test_recheck_before_delivery_prevents_stale_or_cross_account_notice(test_db,monkeypatch,change):
 users,devices,factory=await setup(test_db,monkeypatch);devices[1].preferences={'daily_list':False};await test_db.commit()
 await daily_notices.poll(factory,now=NOW)
 if change=='opt_out':devices[0].preferences={'daily_list':False}
 elif change=='inactive':devices[0].is_active=False
 elif change=='owner':devices[0].user_id=users[1].id
 elif change=='deleted':users[0].deleted_at=NOW
 else:(await test_db.get(Drop,'daily')).status_kind='unsupported'
 await test_db.commit();notify=AsyncMock(return_value=True)
 assert await daily_notices.deliver(factory,notify,now=NOW);notify.assert_not_awaited()
async def test_wat_midnight_expiry_and_abandoned_lease(test_db,monkeypatch):
 _,devices,factory=await setup(test_db,monkeypatch);devices[1].preferences={'daily_list':False};await test_db.commit()
 await daily_notices.poll(factory,now=NOW)
 row=await test_db.scalar(select(DailyListNotice));row.lease_until=NOW+timedelta(seconds=10);await test_db.commit()
 notify=AsyncMock(return_value=True)
 assert not await daily_notices.deliver(factory,notify,now=NOW)
 assert await daily_notices.deliver(factory,notify,now=NOW+timedelta(seconds=11))
 await test_db.refresh(row);row.status='pending';row.next_attempt_at=NOW;await test_db.commit()
 assert not await daily_notices.deliver(factory,notify,now=NOW.replace(hour=23))
 await test_db.refresh(row);assert row.status=='expired' and notify.await_count==1
async def test_concurrent_postgres_consumers_choose_one_notice(test_db,monkeypatch):
 if test_db.bind.dialect.name!='postgresql':pytest.skip('Requires PostgreSQL row locks.')
 _,devices,factory=await setup(test_db,monkeypatch);devices[1].preferences={'daily_list':False};await test_db.commit()
 await asyncio.gather(daily_notices.poll(factory,now=NOW),daily_notices.poll(factory,now=NOW))
 notify=AsyncMock(return_value=True)
 await asyncio.gather(daily_notices.deliver(factory,notify,now=NOW),daily_notices.deliver(factory,notify,now=NOW))
 assert notify.await_count==1
async def test_fcm_scopes_device_and_uses_stable_android_tag(test_db,monkeypatch):
 users,devices,factory=await setup(test_db,monkeypatch)
 monkeypatch.setattr(notifier,'AsyncSessionLocal',factory)
 monkeypatch.setattr(NotificationService,'_get_firebase_app',classmethod(lambda cls:object()))
 sent=[];monkeypatch.setattr(messaging,'send',lambda message,app:sent.append(message))
 assert await NotificationService.send_notification('Today is ready','Check eligibility',user_id=users[0].id,
  device_id=devices[0].id,data={'notification_id':'stable-daily-id'})
 assert len(sent)==1 and sent[0].token==devices[0].device_token
 assert sent[0].android.notification.tag=='stable-daily-id'
 assert not await NotificationService.send_notification('Today is ready','Check eligibility',user_id=users[1].id,device_id=devices[0].id)
