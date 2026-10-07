"""Phrase-created account imports and unlinking tested with a real local signer/EVM."""
import uuid
from eth_account import Account
from sqlalchemy import select
from app.models import Wallet,AutomaticGrant,MintTask,CopyRule
from app.services.custody import CustodyVault
from test_automatic_evm import lab,importer
from test_copy_mints import copying
import pytest

async def test_import_adds_multiple_accounts_without_web_and_relink_does_not_restore_old_policy(lab,importer):
 client,base=importer
 accounts=[Account.create(),Account.create()]
 saved=[]
 for i,a in enumerate(accounts):
  req={k:v for k,v in base.items() if k not in ("wallet_id","contract")}
  req.update(request_id=str(uuid.uuid4()),private_key="0x"+a.key.hex(),account_address=a.address,wallet_label=f"Account {i+1}",collection_scope="reviewed_mints")
  r=await client.post("/api/automatic/import",json=req)
  assert r.status_code==200,r.text
  saved.append((req,r.json()))
 assert len((await lab.client.get("/api/wallets")).json())==3
 assert len({item[1]["wallet_id"] for item in saved})==2
 retry=await client.post("/api/automatic/import",json=saved[0][0]);assert retry.status_code==200 and retry.json()["id"]==saved[0][1]["id"]
 first=saved[0][1]
 assert (await lab.client.delete("/api/wallets/"+first["wallet_id"])).status_code==200
 assert len((await lab.client.get("/api/wallets")).json())==2
 req={**saved[0][0],"request_id":str(uuid.uuid4())}
 relink=await client.post("/api/automatic/import",json=req)
 assert relink.status_code==200 and relink.json()["wallet_id"]==first["wallet_id"]
 async with lab.factory() as db:
  assert (await db.get(AutomaticGrant,first["id"])).status=="disabled"
  assert (await db.get(AutomaticGrant,relink.json()["id"])).status=="enabled"
  assert (await db.get(AutomaticGrant,saved[1][1]["id"])).status=="enabled"
  assert (await db.get(Wallet,first["wallet_id"])).archived_at is None
 duplicate=await client.post("/api/automatic/import",json={**saved[1][0],"request_id":str(uuid.uuid4()),"wallet_label":"Replacement"})
 assert duplicate.status_code==409
 wallets=(await lab.client.get("/api/wallets")).json()
 assert next(w for w in wallets if w["id"]==saved[1][1]["wallet_id"])["label"]=="Account 2"

async def test_two_followed_addresses_and_editing_preserve_both_records(copying):
 c=copying;lab=c["lab"]
 second=Account.create()
 r=await lab.client.post("/api/copy-mints/watches",json={"address":second.address,"label":"Second source","chains":[31337]})
 assert r.status_code==200
 first_id=c["watch_id"];second_id=r.json()["id"];assert first_id!=second_id
 watches=(await lab.client.get("/api/copy-mints")).json()["watches"]
 assert {w["id"] for w in watches}=={first_id,second_id}
 updated=await lab.client.post("/api/copy-mints/watches",json={"address":second.address,"label":"Renamed second","chains":[31337]})
 assert updated.json()["id"]==second_id
 watches=(await lab.client.get("/api/copy-mints")).json()["watches"]
 assert next(w for w in watches if w["id"]==first_id)["address"]==c["source"].address
 assert len(watches)==2

@pytest.mark.parametrize("already_broadcast",[False,True])
async def test_unlinked_signed_copy_never_rebroadcasts_but_receipt_still_settles(copying,already_broadcast):
 c=copying;lab=c["lab"]
 await c["approve"]();await c["mint"](1);await c["scan"]()
 event=(await lab.client.get("/api/copy-mints/activity")).json()["events"][0];tid=event["task_id"]
 await lab.sign(tid)
 async with lab.factory() as db:raw=(await db.get(MintTask,tid)).signed_tx_raw
 if already_broadcast:
  lab.w.eth.send_raw_transaction(raw)
  lab.w.provider.make_request("evm_mine",[])
 response=await lab.client.delete("/api/wallets/"+lab.wallet.id)
 assert response.status_code==200 and response.json()["history_retained"]
 assert (await lab.client.get("/api/wallets")).json()==[]
 assert (await lab.signer_client.post(f"/tasks/{tid}/prepare")).status_code==200  # read-only existing signature reply; no new signature
 await lab.due();await lab.tick()
 async with lab.factory() as db:
  task=await db.get(MintTask,tid);grant=await db.get(AutomaticGrant,lab.grant.id);rule=await db.get(CopyRule,c["request"]["request_id"])
  assert grant.status=="disabled" and rule.status=="revoked"
  assert task.broadcast_disabled_at and task.broadcast_attempts==0
  if already_broadcast:
   assert task.status=="confirmed" and grant.reserved_wei==0 and rule.reserved_wei==0
   assert task.actual_total_cost_wei>0
  else:
   assert task.status=="uncertain" and grant.reserved_wei>0 and rule.reserved_wei>0
 assert lab.nft.functions.totalSupply().call()==(2 if already_broadcast else 1)
 assert len((await lab.client.get("/api/history?section=mints")).json()["records"])==1
 journal=CustodyVault().journal();assert journal.execute("SELECT COUNT(*) FROM signed").fetchone()[0]==1;journal.close()

async def test_unlink_before_signing_disarms_copy_and_signer_refuses_new_signature(copying):
 c=copying;lab=c["lab"]
 await c["approve"]();await c["mint"](1);await c["scan"]()
 tid=(await lab.client.get("/api/copy-mints/activity")).json()["events"][0]["task_id"]
 assert (await lab.client.delete("/api/wallets/"+lab.wallet.id)).status_code==200
 assert (await lab.signer_client.post(f"/tasks/{tid}/prepare")).status_code==409
 async with lab.factory() as db:
  assert (await db.get(MintTask,tid)).status=="disarmed"
  assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==0
 journal=CustodyVault().journal();assert journal.execute("SELECT COUNT(*) FROM signed").fetchone()[0]==0;journal.close()
