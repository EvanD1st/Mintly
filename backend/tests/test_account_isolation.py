"""Two-account isolation checks using disposable records; no signing or network spending."""
from datetime import datetime,timezone,timedelta
from unittest.mock import AsyncMock
import pytest
from httpx import AsyncClient,ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from firebase_admin import messaging
from app.main import app
from app.api.deps import get_db
from app.models import User,Wallet,Drop,MintStage,MintAuthorization,MintTask,ActivityEvent,CopyWatch,CopyRule,CopyEvent,AutomaticGrant,MintPlan,MintPlanRecord,MintPermission
from app.services import notifier
from app.services.notifier import NotificationService
from app.worker import MintlyWorker

@pytest.fixture
async def accounts(test_db):
 async def override(): yield test_db
 app.dependency_overrides[get_db]=override
 now=datetime.now(timezone.utc);end=now+timedelta(days=1)
 d=Drop(id="private-drop",name="Public collection",mint_page_url="https://opensea.io/collection/test")
 s=MintStage(id="private-stage",drop_id=d.id,stage_name="Public",start_time_utc=now,end_time_utc=end)
 test_db.add(d);await test_db.flush();test_db.add(s);await test_db.flush()
 rows={}
 for i,name in enumerate(("member","admin"),1):
  u=await test_db.scalar(select(User).where(User.username==name))
  w=Wallet(id=f"wallet-{name}",user_id=u.id,label=name,address="0x"+f"{i:040x}",is_demo=False)
  test_db.add(w);await test_db.flush()
  g=AutomaticGrant(id=f"grant-{name}",user_id=u.id,wallet_id=w.id,chain_id=4663,account=w.address,context_hash=name,scope={},expires_at=end,budget_wei=1000)
  p=MintPlan(id=f"plan-{name}",user_id=u.id,wallet_id=w.id,collection_slug=f"collection-{name}",collection_name=name,chain="robinhood",chain_id=4663,contract_address="0x"+"3"*40,opensea_url=f"https://opensea.io/collection/collection-{name}")
  test_db.add_all([g,p]);await test_db.flush()
  a=MintAuthorization(id=f"auth-{name}",wallet_id=w.id,drop_id=d.id,stage_id=s.id,quantity=1,max_price_per_token_wei=0,max_fee_wei=1,total_spend_cap_wei=1,recipient_address=w.address,user_consent_text="Test fixture only",authorized_at=now)
  test_db.add(a);await test_db.flush()
  t=MintTask(id=f"task-{name}",authorization_id=a.id,wallet_id=w.id,drop_id=d.id,stage_id=s.id,status="submitted",idempotency_key=name,scheduled_for_utc=now,expires_at_utc=end,transaction_hash="0x"+str(i)*64,is_demo=False)
  watch=CopyWatch(id=f"watch-{name}",user_id=u.id,address="0x"+"4"*40,label=name,chains=[4663],cursors={})
  test_db.add_all([t,watch]);await test_db.flush()
  snapshot=dict(account=w.address,source_address=watch.address,quantity=1,approved_at=int(now.timestamp()),price_cap_wei=0,fee_cap_wei=1,total_cap_wei=1,budget_wei=1000)
  rule=CopyRule(id=f"rule-{name}",user_id=u.id,watch_id=watch.id,grant_id=g.id,chain_id=4663,snapshot=snapshot,context_hash=name,status="active",expires_at=end,resume_after_block=0,budget_wei=1000)
  event=CopyEvent(id=str(i)*64,user_id=u.id,watch_id=watch.id,observation=dict(price_wei=0,timestamp=int(now.timestamp()),chain_id=4663),status="detected")
  test_db.add_all([rule,event,ActivityEvent(user_id=u.id,event_type="test",label=name,detail=f"private-{name}",is_demo=False),MintPlanRecord(id=f"record-{name}",user_id=u.id,plan_id=p.id,event="removed",snapshot={"name":name}),MintPermission(id=f"permission-{name}",user_id=u.id,plan_id=p.id,code_hash=name,typed_data={},execution={},execute_after=now,expires_at=end,signature_deadline=end,status="cancelled")])
  rows[name]=dict(user=u,wallet=w,task=t,rule=rule,event=event)
 await test_db.commit()
 async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as c:
  for name,row in rows.items():
   login=await c.post("/api/auth/login",json={"username":name,"password":f"{name.title()} test password 123"})
   assert login.status_code==200
   row["headers"]={"Authorization":"Bearer "+login.json()["token"]}
  yield c,rows
 app.dependency_overrides.pop(get_db,None)

@pytest.mark.asyncio
async def test_wallet_history_copy_lists_and_mutations_are_owner_scoped(accounts,test_db,monkeypatch):
 c,rows=accounts
 monkeypatch.setattr("app.services.copy_mints.enabled",lambda:None)
 monkeypatch.setattr("app.services.copy_mints.networks",lambda:[])
 for name,row in rows.items():
  h=row["headers"];other="admin" if name=="member" else "member"
  wallets=(await c.get("/api/wallets",headers=h)).json()
  assert [w["id"] for w in wallets]==[f"wallet-{name}"]
  assert (await c.delete(f"/api/wallets/wallet-{other}",headers=h)).status_code==404
  for section,key in [("plans","record"),("mints","task"),("permissions","permission"),("copies","rule")]:
   r=await c.get(f"/api/history?section={section}",headers=h)
   assert r.status_code==200,r.text
   assert [record["id"] for record in r.json()["records"]]==[f"{key}-{name}"]
  activity=(await c.get("/api/history?section=activity",headers=h)).json()["records"]
  assert all(f"private-{other}" not in r["detail"] for r in activity)
  watches=(await c.get("/api/copy-mints",headers=h)).json()["watches"]
  assert [w["id"] for w in watches]==[f"watch-{name}"]
  assert [r["id"] for r in watches[0]["rules"]]==[f"rule-{name}"]
  feed=(await c.get("/api/copy-mints/activity",headers=h)).json()
  assert [e["id"] for e in feed["events"]]==[row["event"].id]
  assert (await c.get(f"/api/copy-mints/activity?watch_id=watch-{other}",headers=h)).status_code==404
  assert (await c.get(f"/api/copy-mints/events/{rows[other]['event'].id}/context",headers=h)).status_code==404
  assert (await c.delete(f"/api/copy-mints/watches/watch-{other}",headers=h)).status_code==404
  assert (await c.post(f"/api/copy-mints/watches/watch-{other}/pause",headers=h,json={"paused":True})).status_code==404
 assert (await c.post("/api/copy-mints/pause",headers=rows["member"]["headers"],json={"paused":True})).status_code==200
 await test_db.refresh(rows["member"]["rule"]);await test_db.refresh(rows["admin"]["rule"])
 assert rows["member"]["rule"].status=="paused" and rows["admin"]["rule"].status=="active"

@pytest.mark.asyncio
async def test_notification_ownership_preferences_and_delivery(accounts,test_db,monkeypatch):
 c,rows=accounts
 monkeypatch.setattr(notifier,"AsyncSessionLocal",async_sessionmaker(test_db.bind,expire_on_commit=False))
 monkeypatch.setattr(NotificationService,"_get_firebase_app",classmethod(lambda cls:object()))
 sent=[];monkeypatch.setattr(messaging,"send",lambda message,app:sent.append(message))
 for name in rows:
  r=await c.post("/api/notifications/register",headers=rows[name]["headers"],json={"token":f"private-device-token-for-{name}"})
  assert r.status_code==200
 token="private-device-token-for-member"
 admin=rows["admin"]["headers"];member=rows["member"]["headers"]
 assert (await c.post("/api/notifications/register",headers=admin,json={"token":token})).status_code==409
 assert (await c.post("/api/notifications/preferences",headers=admin,json={"token":token,"mint_status":False})).status_code==404
 assert (await c.post("/api/notifications/unregister",headers=admin,json={"token":token})).status_code==200
 assert not await NotificationService.send_notification("Private mint","Private",category="mint_status")
 assert sent==[]
 assert await NotificationService.send_notification("Private mint","Private",category="mint_status",user_id=rows["member"]["user"].id)
 assert [m.token for m in sent]==[token]
 assert sent[0].data["user_id"]==rows["member"]["user"].id
 sent.clear()
 assert await NotificationService.send_notification("Feed session","Admin",category="source_health")
 assert [m.token for m in sent]==["private-device-token-for-admin"]
 assert (await c.get("/api/notifications/recent",headers=member)).status_code==403
 NotificationService.clear_sink()

@pytest.mark.asyncio
async def test_legacy_receipt_alert_and_history_have_wallet_owner(accounts,test_db,monkeypatch):
 c,rows=accounts
 worker=MintlyWorker()
 monkeypatch.setattr(worker.executor,"reconcile_transaction",AsyncMock(return_value={"status":"confirmed","gas_used":1,"effective_gas_price":1,"total_fee_wei":1,"block_number":1}))
 send=AsyncMock();monkeypatch.setattr(NotificationService,"send_notification",send)
 await worker.reconcile_pending_tasks(test_db)
 assert {call.kwargs["user_id"] for call in send.call_args_list}=={r["user"].id for r in rows.values()}
 events=(await test_db.execute(select(ActivityEvent).where(ActivityEvent.event_type=="task_confirmed"))).scalars().all()
 assert {e.user_id for e in events}=={r["user"].id for r in rows.values()}
