"""Disposable 4/10-account workloads; never a production throughput claim.

Real API consent, PostgreSQL/SQLite locks, signer journal and local SeaDrop
execution; controlled upstream responses, cheap fixture KDF, in-process HTTP.
"""
import asyncio
from collections import Counter
from contextvars import ContextVar
from datetime import datetime,timezone,timedelta
import json
import math
import os
from pathlib import Path
import time
from types import SimpleNamespace
import uuid
from unittest.mock import AsyncMock

from eth_account import Account
import pytest
from sqlalchemy import event,select

from app.config import settings
from app.models import User,Wallet,AutomaticGrant,AutomaticNonce,CopyWatch,CopyEvent,MintTask,MintAuthorization,FeedWalletCheck
from app.services import automatic,copy_mints,feed_checks,mint_instruction_cache as cache
from app.services.custody import CustodyVault,private_write
from app.services.mint_plans import aware
from app.services.opensea import OpenSeaClient
from test_automatic_evm import lab
from test_copy_mints import copying
from test_opensea_multiwallet import six_wallets,concurrent_prepare,assert_approvals_unchanged


def summary(values):
    values=sorted(values)
    return dict(count=len(values),p50_ms=round(values[(len(values)-1)//2],3),
        p95_ms=round(values[max(0,math.ceil(len(values)*.95)-1)],3),max_ms=round(values[-1],3))


def save_report(report):
    target=os.environ.get('MINTLY_SCALE_REPORT')
    if target:
        with Path(target).open('a',encoding='utf-8') as f:f.write(json.dumps(report)+'\n')


def sqlite_timeout(lab):
    engine=lab.factory.kw['bind'].sync_engine
    def configure(connection,*_):connection.execute('PRAGMA busy_timeout=120000')
    if engine.dialect.name=='sqlite':event.listen(engine,'checkout',configure)
    return engine,configure


def production_keys(lab,items):
    """Optional CPU profile; keep encryption outside the measured mint phase."""
    iterations=262144 if os.environ.get('MINTLY_SCALE_PRODUCTION_KDF')=='1' else 1024
    if iterations==262144:
        for item in items:
            policy=json.loads((lab.tmp/f'{item.grant.id}.policy.json').read_text())
            private_write(lab.tmp/f"{policy['key_id']}.keystore.json",json.dumps(Account.encrypt(
                item.owner.key,(lab.tmp/'password').read_text(),kdf='scrypt',iterations=iterations)))
    return iterations


async def background(lab,items,monkeypatch):
    """Actual isolated feed-check rows, cached artwork and account-scoped reads."""
    from app.api import artwork
    from app.services.opensea import CHAINS
    artwork._cache.clear()
    calls=[];latencies=[]
    monkeypatch.setattr(OpenSeaClient,'_key',AsyncMock(return_value='disposable-image-key'))
    async def metadata(*args,**kwargs):
        calls.append('artwork');await asyncio.sleep(.01)
        return 200,{'collection':'local-test','image_url':'https://i.seadn.io/disposable.png'}
    monkeypatch.setattr(OpenSeaClient,'_request',metadata)
    monkeypatch.setattr(feed_checks,'supported',lambda d:d.chain_id==31337)
    monkeypatch.setitem(CHAINS,'local',(31337,'Local test'))
    monkeypatch.setattr(OpenSeaClient,'get_drop',AsyncMock(return_value={'chain':'local',
        'contract_address':lab.nft.address,'stages':[dict(uuid='public',label='Public',stage_type='public_sale',
            start_time=datetime.fromtimestamp(lab.start,timezone.utc).isoformat(),
            end_time=datetime.fromtimestamp(lab.end,timezone.utc).isoformat(),price='10',max_per_wallet='20',
            price_currency_address='0x'+'0'*40)]}))
    async with lab.factory() as db:
        assert await artwork.collection_image('local-test',chain_id=31337,contract=lab.nft.address,db=db)
    async def one(item):
        for path in ('/api/wallets','/api/mint-plans','/api/tasks/queue','/api/copy-mints/activity','/api/drops'):
            begin=time.perf_counter();r=await lab.client.get(path,headers=item.headers)
            latencies.append((time.perf_counter()-begin)*1000)
            assert r.status_code==200,(path,r.text)
        async with lab.factory() as db:
            await feed_checks.queue_checks(db,await db.get(User,item.user.id),await db.get(Wallet,item.wallet.id),[lab.drop])
            for _ in range(3):
                assert await artwork.collection_image('local-test',chain_id=31337,contract=lab.nft.address,db=db)
    await asyncio.gather(*(one(item) for item in items))
    for _ in items:assert await feed_checks.step(lab.factory)
    async with lab.factory() as db:
        rows=(await db.scalars(select(FeedWalletCheck))).all()
        assert len(rows)==len(items) and all(row.status=='complete' for row in rows)
        expected={item.user.id:item.owner.address.lower() for item in items}
        assert all(row.result['address'].lower()==expected[row.user_id] for row in rows)
    assert calls==['artwork'],'Stored artwork must not repeatedly call the provider'
    return dict(screen_http=summary(latencies),feed_checks=len(items),artwork_fetches=len(calls))


@pytest.mark.parametrize('count',[4,10])
async def test_mixed_accounts_copy_automatic_and_background(copying,monkeypatch,count):
    c=copying;lab=c['lab'];engine,timeout=sqlite_timeout(lab)
    assert (settings.OPENSEA_GLOBAL_REQUEST_SECONDS,settings.OPENSEA_MINT_REQUEST_SECONDS)==(2,20)
    copy_count=count-1
    items=[SimpleNamespace(user=lab.user,wallet=lab.wallet,grant=lab.grant,owner=lab.owner,headers=dict(lab.client.headers))]
    watches=[c['watch_id']];await c['approve']()
    async with lab.factory() as db:
        for i in range(1,count):
            user=User(id=str(uuid.uuid4()),username=f'scale-user-{i}',password_hash=lab.user.password_hash,
                role='member',is_active=True,must_change_password=False)
            owner=Account.create()
            assert lab.w.provider.make_request('hardhat_setBalance',[owner.address,hex(10**18)])['result']
            wallet=Wallet(id=str(uuid.uuid4()),user_id=user.id,address=owner.address,label='Disposable',signing_capability='custodial',is_demo=False)
            key_id,gid=str(uuid.uuid4()),str(uuid.uuid4())
            private_write(lab.tmp/f'{key_id}.keystore.json',json.dumps(Account.encrypt(owner.key,
                (lab.tmp/'password').read_text(),kdf='scrypt',iterations=1024)))
            policy=dict(grant_id=gid,key_id=key_id,user_id=user.id,wallet_id=wallet.id,account=owner.address,
                chain_id=31337,contracts=[lab.nft.address],mint_kinds=['public'],budget_wei=10**16,
                max_task_wei=10**15,expires_at=lab.end)
            private_write(lab.tmp/f'{gid}.policy.json',json.dumps(policy))
            grant=AutomaticGrant(id=gid,user_id=user.id,wallet_id=wallet.id,chain_id=31337,account=owner.address,
                context_hash=automatic.digest(policy),scope={k:policy[k] for k in ('contracts','mint_kinds','max_task_wei')},
                budget_wei=10**16,expires_at=datetime.fromtimestamp(lab.end,timezone.utc),status='enabled')
            db.add(user);await db.flush();db.add(wallet);await db.flush();db.add(grant)
            items.append(SimpleNamespace(user=user,wallet=wallet,grant=grant,owner=owner))
        await db.commit()
    for i,item in enumerate(items[1:],1):
        login=await lab.client.post('/api/auth/login',json={'username':item.user.username,'password':'Member test password 123'})
        assert login.status_code==200
        item.headers={'Authorization':'Bearer '+login.json()['token']}
        if i<copy_count:
            follow=await lab.client.post('/api/copy-mints/watches',headers=item.headers,json={
                'address':c['source'].address,'label':'Shared source','chains':[31337]})
            assert follow.status_code==200,follow.text
            wid=follow.json()['id'];watches.append(wid)
            approved=await lab.client.post(f'/api/copy-mints/watches/{wid}/rules',headers=item.headers,
                json={**c['request'],'request_id':str(uuid.uuid4()),'grant_id':item.grant.id})
            assert approved.status_code==200,approved.text
        else:
            plan=await lab.client.post('/api/tasks/arm',headers=item.headers,json={**lab.request,
                'wallet_id':item.wallet.id,'grant_id':item.grant.id,'quantity':1})
            assert plan.status_code==200,plan.text
            item.task_id=plan.json()['id']
    try:
        iterations=production_keys(lab,items)
        await c['mint'](1)
        scan_times=[]
        async def scan(wid):
            begin=time.perf_counter()
            async with lab.factory() as db:await copy_mints.scan_watch(db,await db.get(CopyWatch,wid),31337)
            scan_times.append((time.perf_counter()-begin)*1000)
        started=time.perf_counter()
        await asyncio.gather(*(scan(wid) for wid in watches))
        scan_ms=(time.perf_counter()-started)*1000
        async with lab.factory() as db:
            events=(await db.scalars(select(CopyEvent))).all()
            assert len(events)==copy_count and all(e.task_id for e in events),[(e.status,e.note) for e in events]
            for item in items[:copy_count]:
                item.task_id=next(e.task_id for e in events if e.user_id==item.user.id)
            before={}
            for item in items:
                task=await db.get(MintTask,item.task_id);auth=await db.get(MintAuthorization,task.authorization_id)
                before[task.id]=(json.loads(json.dumps(auth.snapshot)),aware(task.expires_at_utc))
        owner=ContextVar('scale_request',default=None);lock_waits=[]
        original=automatic.lock_execution
        async def measured_lock(db):
            begin=time.perf_counter();await original(db)
            if owner.get():lock_waits.append((time.perf_counter()-begin)*1000)
        monkeypatch.setattr(automatic,'lock_execution',measured_lock)
        signatures=[];original_account=CustodyVault.account
        def account(vault,policy):
            real=original_account(vault,policy)
            def sign(tx):signatures.append(policy['wallet_id']);return real.sign_transaction(tx)
            return SimpleNamespace(sign_transaction=sign)
        monkeypatch.setattr(CustodyVault,'account',account)
        ready=asyncio.Event();arrived=0;prepare_times=[]
        async def prepare(item):
            nonlocal arrived
            arrived+=1
            if arrived==count:ready.set()
            await ready.wait();owner.set(item.task_id);begin=time.perf_counter()
            r=await lab.signer_client.post(f'/tasks/{item.task_id}/prepare')
            prepare_times.append((time.perf_counter()-begin)*1000)
            assert r.status_code==200 and r.json()['status']=='prepared',r.text
        async def features():await ready.wait();return await background(lab,items,monkeypatch)
        started=time.perf_counter()
        results=await asyncio.gather(*(prepare(item) for item in items),features())
        prepare_ms=(time.perf_counter()-started)*1000
        replays=await asyncio.gather(*(lab.signer_client.post(f'/tasks/{item.task_id}/prepare') for item in items))
        assert all(r.status_code==200 for r in replays)
        assert Counter(signatures)==Counter(item.wallet.id for item in items)
        async with lab.factory() as db:
            assert len((await db.scalars(select(AutomaticNonce))).all())==count
            for item,replay in zip(items,replays):
                task=await db.get(MintTask,item.task_id);auth=await db.get(MintAuthorization,task.authorization_id)
                assert (auth.snapshot,aware(task.expires_at_utc))==before[task.id]
                assert task.assigned_nonce==0 and replay.json()['hash']==task.transaction_hash
                receipt=lab.w.eth.wait_for_transaction_receipt(lab.w.eth.send_raw_transaction(task.signed_tx_raw))
                assert receipt.status==1 and receipt['from']==item.owner.address
                assert receipt.gasUsed*receipt.effectiveGasPrice+10<=auth.total_spend_cap_wei
        assert lab.nft.functions.totalSupply().call()==count+1
        recipients=Counter(lab.nft.functions.ownerOf(token).call() for token in range(1,count+2))
        assert all(recipients[item.owner.address]==1 for item in items)
        journal=CustodyVault().journal()
        try:
            assert journal.execute('SELECT count(*) FROM signed').fetchone()[0]==count
            assert journal.execute('SELECT count(*) FROM copy_signed').fetchone()[0]==copy_count
        finally:journal.close()
        save_report(dict(scenario='mixed_public',database=engine.dialect.name,kdf_iterations=iterations,users=count,copy_tasks=copy_count,
            automatic_tasks=1,signatures=count,successful_receipts=count,scan_batch_ms=round(scan_ms,3),
            scan=summary(scan_times),prepare_and_background_ms=round(prepare_ms,3),
            prepare=summary(prepare_times),execution_lock_wait=summary(lock_waits),background=results[-1]))
    finally:
        if engine.dialect.name=='sqlite':event.remove(engine,'checkout',timeout)


@pytest.mark.parametrize('six_wallets',[10],indirect=True)
async def test_ten_cached_whitelist_accounts_and_duplicate_requests(six_wallets,monkeypatch):
    case=six_wallets;lab=case.lab
    iterations=production_keys(lab,case.wallets)
    assert len({x.user.id for x in case.wallets})==10
    calls=[];real=CustodyVault.account
    def account(vault,policy):
        inner=real(vault,policy)
        def sign(tx):calls.append(policy['wallet_id']);return inner.sign_transaction(tx)
        return SimpleNamespace(sign_transaction=sign)
    monkeypatch.setattr(CustodyVault,'account',account)
    start=time.perf_counter()
    results,features=await asyncio.gather(concurrent_prepare(case,monkeypatch,duplicates=True),background(lab,case.wallets,monkeypatch))
    elapsed=(time.perf_counter()-start)*1000
    assert len(results)==20 and all(r.status_code==200 for r in results),[(r.status_code,r.text) for r in results]
    assert [r.json()['hash'] for r in results[:10]]==[r.json()['hash'] for r in results[10:]]
    assert Counter(calls)==Counter(x.wallet.id for x in case.wallets) and not case.calls
    await assert_approvals_unchanged(case)
    async with lab.factory() as db:
        assert len((await db.scalars(select(AutomaticNonce))).all())==10
        for item in case.wallets:
            task=await db.get(MintTask,item.task_id)
            assert task.assigned_nonce==0
            receipt=lab.w.eth.wait_for_transaction_receipt(lab.w.eth.send_raw_transaction(task.signed_tx_raw))
            assert receipt.status==1 and receipt['from']==item.owner.address
    assert lab.nft.functions.totalSupply().call()==sum(x.quantity for x in case.wallets)
    recipients=Counter(lab.nft.functions.ownerOf(token).call() for token in range(1,sum(x.quantity for x in case.wallets)+1))
    assert all(recipients[x.owner.address]==x.quantity for x in case.wallets)
    journal=CustodyVault().journal()
    try:
        rows=journal.execute('SELECT * FROM signed').fetchall()
        assert len(rows)==10 and {(x['task'],x['intent'],x['nonce']) for x in rows}=={(x.task_id,x.intent,0) for x in case.wallets}
    finally:journal.close()
    save_report(dict(scenario='ten_cached_whitelist',database=lab.factory.kw['bind'].dialect.name,
        users=10,kdf_iterations=iterations,concurrent_prepare_requests=20,signatures=10,successful_receipts=10,fresh_builder_calls=0,
        prepare_and_background_ms=round(elapsed,3),background=features))


@pytest.mark.parametrize('six_wallets',[10],indirect=True)
async def test_ten_stale_cache_requests_fail_within_immutable_deadline(six_wallets,monkeypatch):
    case=six_wallets
    journal=CustodyVault().journal()
    try:journal.execute('UPDATE mint_instruction_cache SET expires_at=1');journal.commit()
    finally:journal.close()
    from app.services.opensea import OpenSeaUnavailable
    calls=[]
    async def unavailable(self,slug,address,quantity):
        calls.append(address)
        raise OpenSeaUnavailable('Controlled shared provider cooldown',503,retry_after_seconds=20,upstream_status=503)
    monkeypatch.setattr(OpenSeaClient,'build_mint',unavailable)
    results=await concurrent_prepare(case,monkeypatch)
    assert len(calls)==10 and all(r.status_code==503 and r.headers['Retry-After']=='20' for r in results)
    await assert_approvals_unchanged(case)
    from app.automatic_worker import step
    now=datetime.fromtimestamp(case.lab.end-5,timezone.utc)
    for _ in range(10):assert await step(case.lab.factory,case.lab.sign,now=now)
    async with case.lab.factory() as db:
        assert not (await db.scalars(select(AutomaticNonce))).all()
        for item in case.wallets:
            task=await db.get(MintTask,item.task_id)
            assert not task.signed_tx_raw and aware(task.next_attempt_at)==item.deadline
    for _ in range(10):assert await step(case.lab.factory,case.lab.sign,now=datetime.fromtimestamp(case.lab.end,timezone.utc))
    assert not await step(case.lab.factory,case.lab.sign,now=datetime.fromtimestamp(case.lab.end,timezone.utc))
    async with case.lab.factory() as db:
        for item in case.wallets:
            assert (await db.get(MintTask,item.task_id)).status=='expired'
            assert (await db.get(AutomaticGrant,item.grant.id)).reserved_wei==0
    await assert_approvals_unchanged(case)
    journal=CustodyVault().journal()
    try:assert journal.execute('SELECT count(*) FROM signed').fetchone()[0]==0
    finally:journal.close()


async def test_ten_fresh_builder_permit_capacity_is_a_simulation(test_db,monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.services import opensea_limits as limits
    monkeypatch.setattr(settings,'OPENSEA_COORDINATE_REQUESTS',True)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    now=datetime.now(timezone.utc);permits=[]
    for _ in range(10):
        delay,_=await limits.acquire('/drops/disposable/mint',factory=factory,now=now)
        if delay:now+=timedelta(seconds=delay)
        if delay:assert await limits.acquire('/drops/disposable/mint',factory=factory,now=now)==(0,None)
        permits.append(now)
    assert [(t-permits[0]).total_seconds() for t in permits]==list(range(0,200,20))
    save_report(dict(scenario='permit_capacity_simulation',users=10,
        mint_gap_seconds=settings.OPENSEA_MINT_REQUEST_SECONDS,first_to_tenth_permit_seconds=180,
        permits_within_30_second_window=sum(t<permits[0]+timedelta(seconds=30) for t in permits)))
