"""Wallet unlinking is scoped, idempotent and preserves pending receipt accounting."""
from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select
from app.models import Wallet,AutomaticGrant,CopyWatch,CopyRule,MintAuthorization,MintTask
from test_account_isolation import accounts

async def add_task(db,wallet,grant,amount,key,rule=None,signed=False):
 now=datetime.now(timezone.utc)
 snapshot=dict(user_id=wallet.user_id,account=wallet.address,recipient=wallet.address,chain_id=4663,chain="Robinhood",contract="0x"+"5"*40,drop_id="private-drop",stage_id="private-stage",drop_name="Private collection",stage_name="Public",start=int(now.timestamp()),end=int((now+timedelta(days=1)).timestamp()),expiry=int((now+timedelta(days=1)).timestamp()),quantity=1,price_wei=0,price_cap_wei=0,fee_cap_wei=amount,total_cap_wei=amount)
 a=MintAuthorization(id="auth-"+key,wallet_id=wallet.id,grant_id=grant.id,drop_id="private-drop",stage_id="private-stage",quantity=1,max_price_per_token_wei=0,max_fee_wei=amount,total_spend_cap_wei=amount,recipient_address=wallet.address,user_consent_text="Local test",authorized_at=now,snapshot=snapshot)
 db.add(a);await db.flush()
 t=MintTask(id=key,authorization_id=a.id,wallet_id=wallet.id,drop_id=a.drop_id,stage_id=a.stage_id,copy_rule_id=rule.id if rule else None,status="prepared" if signed else "armed",execution_mode="custodial_v1",idempotency_key=key,scheduled_for_utc=now,expires_at_utc=now+timedelta(days=1),signed_tx_raw="0x01" if signed else None,transaction_hash="0x"+"8"*64 if signed else None)
 db.add(t);await db.flush();return t

@pytest.mark.asyncio
async def test_unlink_disables_only_selected_wallet_and_retains_signed_reservation(accounts,test_db):
 c,rows=accounts;member=rows["member"];wallet=member["wallet"]
 grant=await test_db.get(AutomaticGrant,"grant-member");rule=member["rule"]
 grant.reserved_wei=60;rule.reserved_wei=30
 unsigned=await add_task(test_db,wallet,grant,10,"unsigned-copy",rule)
 signed=await add_task(test_db,wallet,grant,20,"signed-copy",rule,True)
 manual=await add_task(test_db,wallet,grant,30,"unsigned-manual")
 other=Wallet(id="second-wallet",user_id=wallet.user_id,label="Second wallet",address="0x"+"6"*40,is_default=False)
 test_db.add(other);await test_db.flush()
 now=datetime.now(timezone.utc)
 g=AutomaticGrant(id="second-grant",user_id=wallet.user_id,wallet_id=other.id,chain_id=4663,account=other.address,context_hash="second",scope={},budget_wei=1000,reserved_wei=5,expires_at=now+timedelta(days=1))
 test_db.add(g);await test_db.flush()
 t=await add_task(test_db,other,g,5,"second-armed")
 await test_db.commit()
 before=len((await c.get("/api/history?section=mints",headers=member["headers"])).json()["records"])
 for _ in range(2):
  r=await c.delete("/api/wallets/"+wallet.id,headers=member["headers"])
  assert r.status_code==200 and r.json()["automatic_actions_disabled"]
  assert [w["id"] for w in (await c.get("/api/wallets",headers=member["headers"])).json()]==[other.id]
 await test_db.refresh(grant);await test_db.refresh(rule);await test_db.refresh(wallet)
 assert wallet.archived_at and grant.status=="disabled" and rule.status=="revoked"
 assert grant.reserved_wei==20 and rule.reserved_wei==20
 for item in (unsigned,manual,signed,t,other,g):await test_db.refresh(item)
 assert unsigned.status==manual.status=="disarmed"
 assert signed.status=="prepared" and signed.signed_tx_raw=="0x01" and signed.broadcast_disabled_at
 assert t.status=="armed" and g.status=="enabled" and g.reserved_wei==5 and other.is_default
 assert len((await c.get("/api/history?section=mints",headers=member["headers"])).json()["records"])==before
 assert (await c.post("/api/copy-mints/pause",headers=member["headers"],json={"paused":False})).status_code in (200,409)
 await test_db.refresh(rule);assert rule.status=="revoked"
 foreign=await c.delete("/api/wallets/"+rows["admin"]["wallet"].id,headers=member["headers"])
 assert foreign.status_code==404
 assert len((await c.get("/api/wallets",headers=rows["admin"]["headers"])).json())==1
