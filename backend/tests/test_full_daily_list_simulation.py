"""Cold daily-list traffic plus real mixed execution, with wall-clock pacing.

Only upstream HTTP/eligibility identity responses and their latency are
controlled. No production credentials, accounts, keys or RPCs are used.
"""
import asyncio
from collections import Counter
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import AsyncMock
import uuid
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from sqlalchemy import event,select,func

from app.models import SourcePost,Drop,Wallet,User,OpenSeaAccess,FeedWalletCheck,CollectionArtwork,MintTask,MintAuthorization,AutomaticGrant,AutomaticNonce,MintPlan,CopyWatch,CopyEvent,CopyRule
from app.config import settings
from app.services import automatic,copy_mints,feed_checks,opensea,opensea_limits,mint_diagnostics
from app.services.custody import CustodyVault
from app.services.mint_plans import aware
from app.services.phase_identity import stage_kind
from app.services.signer.base import SEADROP_V1_ADDRESS
from app.automatic_worker import step as execution_step
from test_automatic_evm import lab
from test_copy_mints import copying
from test_ten_user_simulation import provision_mixed,production_keys,summary,save_report

# Capture the production method before disposable fixtures replace the builder.
REAL_BUILD=opensea.OpenSeaClient.build_mint


async def make_daily_list(lab,items,collections):
    artifacts=json.loads((Path(__file__).parent/'fixtures/seadrop-presale.json').read_text())['contracts']
    contracts=[lab.nft];fee=lab.w.eth.accounts[1];funding=lab.w.eth.accounts[0]
    for _ in range(collections-1):
        spec=artifacts['PresaleTestNFT']
        receipt=lab.w.eth.wait_for_transaction_receipt(lab.w.eth.contract(abi=spec['abi'],bytecode=spec['bytecode'])
            .constructor(SEADROP_V1_ADDRESS).transact({'from':funding}))
        nft=lab.w.eth.contract(address=receipt.contractAddress,abi=spec['abi'])
        bounds=(10,20,lab.start,lab.end,100,500,500)
        lab.w.eth.wait_for_transaction_receipt(nft.functions.configure(bytes(32),fee,funding,bounds).transact({'from':funding}))
        lab.w.provider.make_request('hardhat_impersonateAccount',[nft.address])
        lab.w.provider.make_request('hardhat_setBalance',[nft.address,hex(10**18)])
        lab.w.eth.wait_for_transaction_receipt(lab.sea.functions.updatePublicDrop((10,lab.start,lab.end,20,500,True))
            .transact({'from':nft.address}))
        lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[nft.address])
        contracts.append(nft)
    now=datetime.now(timezone.utc);drops=[];details={}
    async with lab.factory() as db:
        post=SourcePost(id=str(uuid.uuid4()),post_id='disposable-eight-entry-list',author_username='lakzonevn',
            full_text='Disposable captured-list-shaped fixture; no X connection.',posted_at=now,
            list_date=now.astimezone(ZoneInfo('Africa/Lagos')).date(),is_daily_list=True)
        db.add(post);await db.flush()
        for i,nft in enumerate(contracts):
            slug='local-test' if i==0 else f'full-list-{i}'
            if i==0:
                drop=await db.get(Drop,lab.drop.id);drop.source_post_id=post.id
            else:
                drop=Drop(id=str(uuid.uuid4()),source_post_id=post.id,name=f'Daily collection {i}',
                    chain='Local test',chain_id=31337,contract_address=nft.address,
                    mint_page_url=f'https://opensea.io/collection/{slug}',is_supported_integration=True,is_demo=False)
                db.add(drop)
            drops.append(drop)
            details[slug]=dict(chain='local',contract_address=nft.address,collection_slug=slug,
                opensea_url=f'https://opensea.io/collection/{slug}',drop_type='seadrop_v1_erc721',stages=[
                    dict(uuid='public',label='Public',stage_type='public_sale',price='10',max_per_wallet='20',
                        start_time=datetime.fromtimestamp(lab.start,timezone.utc).isoformat(),
                        end_time=datetime.fromtimestamp(lab.end,timezone.utc).isoformat(),price_currency_address='0x'+'0'*40),
                    dict(uuid=f'whitelist-{i}',label='Whitelist',stage_type='signed_sale',price='10',max_per_wallet='20',
                        start_time=datetime.fromtimestamp(lab.start,timezone.utc).isoformat(),
                        end_time=datetime.fromtimestamp(lab.end,timezone.utc).isoformat(),price_currency_address='0x'+'0'*40)])
        for item in items:
            db.add(OpenSeaAccess(wallet_id=item.wallet.id,user_id=item.user.id,enabled=True,revision=1,
                expires_at=now+timedelta(days=1),terms_version='disposable-consent',status='ready',consented_at=now))
        await db.commit()
    return drops,details


def controlled_provider(lab,items,details,monkeypatch):
    """Run the actual OpenSea request/gate/cache/parser around controlled I/O."""
    original_builder=opensea.OpenSeaClient.build_mint
    addresses={item.owner.address.lower():i for i,item in enumerate(items)}
    calls=[];waits=[];original_permit=opensea_limits.permit
    async def measured_permit(path):
        begin=time.monotonic();delay,reason=await original_permit(path)
        waits.append(dict(path=path,phase=mint_diagnostics.current_phase(),delay=delay,reason=reason,
            wait_ms=(time.monotonic()-begin)*1000))
        return delay,reason
    monkeypatch.setattr(opensea_limits,'permit',measured_permit)
    class Response:
        status=200;headers={};content_length=None
        def __init__(self,path,payload):self.path=path;self.payload=payload;self.content=self
        async def __aenter__(self):
            index=len(calls)
            delay=2.4 if self.path.endswith('/mint') else 2.2 if index%13==12 else .6 if self.path.endswith('/eligibility') else .35
            self.delay=delay
            calls.append(dict(path=self.path,kind='mint' if self.path.endswith('/mint') else 'eligibility' if self.path.endswith('/eligibility') else 'artwork' if self.path.startswith('/collections/') else 'metadata',
                started=time.monotonic(),phase=mint_diagnostics.current_phase(),provider_delay_ms=delay*1000))
            return self
        async def __aexit__(self,*args):return False
        async def read(self,limit):
            await asyncio.sleep(self.delay)
            slug=self.path.split('/')[2]
            if self.path.startswith('/collections/'):
                result=dict(collection=slug,image_url=f'https://i.seadn.io/{slug}.png')
            elif self.path.endswith('/mint'):
                status,result=await original_builder(opensea.OpenSeaClient(),slug,self.payload['minter'],self.payload['quantity'])
                assert status==200
            elif self.path.endswith('/eligibility'):
                address=self.payload['minter'];i=addresses[address.lower()];j=list(details).index(slug)
                result=dict(address=address,stages=[dict(stage_uuid=f'whitelist-{j}',eligible=(i+j)%2==0,
                    remaining=20,max_total_mintable_by_wallet=20,price_wei=10)])
            else:result=details[slug]
            return json.dumps(result).encode()
    class Session:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        def request(self,method,url,**kwargs):
            assert url.startswith(opensea.API_ROOT+'/'),'No live transport is permitted'
            return Response(url[len(opensea.API_ROOT):],kwargs.get('json'))
    # Replace only this module's transport binding, leaving local Web3 RPC intact.
    monkeypatch.setattr(opensea,'aiohttp',SimpleNamespace(ClientSession=Session,ClientTimeout=aiohttp.ClientTimeout,ClientError=aiohttp.ClientError))
    monkeypatch.setattr(opensea.OpenSeaClient,'_key',AsyncMock(return_value='disposable-provisioned-key'))
    monkeypatch.setattr(opensea.OpenSeaClient,'build_mint',REAL_BUILD)
    monkeypatch.setattr(settings,'OPENSEA_COORDINATE_REQUESTS',True)
    monkeypatch.setattr(opensea_limits,'AsyncSessionLocal',lab.factory)
    monkeypatch.setattr(feed_checks,'supported',lambda d:d.chain_id==31337)
    # The API imports this predicate directly, so its test-local binding must
    # advertise the disposable chain as well as the background worker's binding.
    monkeypatch.setattr('app.api.drops.supported',lambda d:d.chain_id==31337)
    monkeypatch.setitem(opensea.CHAINS,'local',(31337,'Local test'))
    async def broker(wallet_id,operation,*,slug=None,key=None):
        assert operation=='stages'
        item=next(item for item in items if item.wallet.id==wallet_id)
        status,result=await opensea.OpenSeaClient()._request('GET',f'/drops/{slug}/eligibility',
            payload={'minter':item.owner.address},key=key)
        assert status==200;return result
    monkeypatch.setattr('app.api.opensea_access.broker',broker)
    return calls,waits


@pytest.mark.parametrize('users,collections',[(2,2),(10,8)],ids=['smoke','ten_users_eight_collections'])
async def test_full_daily_list_with_copy_and_fresh_automatic(copying,monkeypatch,users,collections):
    case=await provision_mixed(copying,monkeypatch,users,copy_count=users//2,automatic_kind='signed')
    c,lab,items=case.c,case.lab,case.items
    lab.kind='signed'
    drops,details=await make_daily_list(lab,items,collections)
    iterations=production_keys(lab,items)
    calls,waits=controlled_provider(lab,items,details,monkeypatch)
    assert (settings.OPENSEA_GLOBAL_REQUEST_SECONDS,settings.OPENSEA_MINT_REQUEST_SECONDS,
        settings.OPENSEA_QUEUE_WAIT_SECONDS,settings.OPENSEA_PREPARATION_MAX_ATTEMPTS)==(2,20,8,40)
    from app.api import artwork
    artwork._cache.clear();opensea._drop_cache.clear();opensea._verified_mints.clear()
    starts=time.monotonic();limit=starts+(200 if users==2 else 750)
    opened=asyncio.Event();scanned=asyncio.Event();execution_done=asyncio.Event();feed_done=asyncio.Event()
    samples=[];snapshots=[];feed_completions={};task_completions={};approval_before={};signatures=[]
    original_account=CustodyVault.account
    def account(vault,policy):
        inner=original_account(vault,policy)
        def sign(tx):signatures.append(policy['wallet_id']);return inner.sign_transaction(tx)
        return SimpleNamespace(sign_transaction=sign)
    monkeypatch.setattr(CustodyVault,'account',account)
    async def open_today(item,*,queue=False):
        begin=time.monotonic()
        response=await lab.client.get(f'/api/drops?daily_only=true&wallet_id={item.wallet.id}',headers=item.headers)
        samples.append((time.monotonic()-begin)*1000)
        assert response.status_code==200,response.text
        data=response.json();assert len(data['drops'])==collections and data['selected_wallet_id']==item.wallet.id
        if queue:
            body={'wallet_id':item.wallet.id,'drop_ids':[drop.id for drop in drops]}
            for _ in range(2):
                r=await lab.client.post('/api/drops/wallet-checks',headers=item.headers,json=body)
                assert r.status_code==202 and r.json()['queued']==collections,r.text
        return data
    async def today_clients():
        await asyncio.gather(*(open_today(item,queue=True) for item in items));opened.set()
        while not feed_done.is_set():
            await asyncio.sleep(15)
            await asyncio.gather(*(open_today(item) for item in items))
    async def observe_copy():
        await c['mint'](1)
        async def scan(wid):
            async with lab.factory() as db:
                await copy_mints.scan_watch(db,await db.get(CopyWatch,wid),31337)
        await asyncio.gather(*(scan(wid) for wid in case.watches))
        async with lab.factory() as db:
            events=(await db.scalars(select(CopyEvent))).all()
            assert len(events)==case.copy_count and all(e.task_id for e in events),[(e.status,e.note) for e in events]
            for item in items[:case.copy_count]:item.task_id=next(e.task_id for e in events if e.user_id==item.user.id)
            for item in items:
                task=await db.get(MintTask,item.task_id);auth=await db.get(MintAuthorization,task.authorization_id)
                approval_before[task.id]=(json.loads(json.dumps(auth.snapshot)),aware(task.expires_at_utc))
                if not task.copy_rule_id:assert auth.snapshot['execution'] is None
        scanned.set()
    async def execute():
        await scanned.wait()
        while time.monotonic()<limit:
            # Align the disposable scheduler clock with the deliberately advanced
            # local chain, as existing EVM tests do; the rate gates use real time.
            now=datetime.fromtimestamp(lab.w.eth.get_block('latest').timestamp,timezone.utc)
            progress=await execution_step(lab.factory,lab.sign,now=now)
            if progress:
                lab.w.provider.make_request('evm_mine',[]);lab.w.provider.make_request('evm_mine',[])
            else:
                await asyncio.sleep(.5);lab.w.provider.make_request('evm_mine',[])
            async with lab.factory() as db:
                tasks=(await db.scalars(select(MintTask))).all()
                for task in tasks:
                    assert task.status not in ('failed','expired','reverted'),(task.status,task.failure_reason)
                    assert aware(task.expires_at_utc)==approval_before[task.id][1]
                    if task.next_attempt_at:assert aware(task.next_attempt_at)<=aware(task.expires_at_utc)
                    if task.status=='confirmed':task_completions.setdefault(task.id,time.monotonic()-starts)
                if len(task_completions)==users:execution_done.set();return
        raise AssertionError('Mixed execution did not progress within the bounded test window')
    async def check_feed():
        await opened.wait()
        async with lab.factory() as db:assert await db.scalar(select(func.count()).select_from(FeedWalletCheck))==users*collections
        while time.monotonic()<limit:
            await feed_checks.step(lab.factory)
            async with lab.factory() as db:
                rows=(await db.scalars(select(FeedWalletCheck))).all()
                for row in rows:
                    if row.status in ('complete','unverified'):feed_completions.setdefault((row.user_id,row.drop_id),time.monotonic()-starts)
                    assert row.attempts<=3
                if len(feed_completions)==users*collections:feed_done.set();return
            await asyncio.sleep(1) # Same display-check worker cadence as production.
        raise AssertionError('Cold-list checks did not drain within the bounded test window')
    async def images():
        await opened.wait()
        done=set()
        while len(done)<collections and time.monotonic()<limit:
            for drop in drops:
                if drop.id in done:continue
                async with lab.factory() as db:
                    image=await artwork.collection_image(opensea.collection_slug(drop.mint_page_url),
                        chain_id=31337,contract=drop.contract_address,db=db)
                if image:done.add(drop.id)
            if len(done)<collections:await asyncio.sleep(5)
        assert len(done)==collections
    async def monitor():
        while not (execution_done.is_set() and feed_done.is_set()):
            await asyncio.sleep(10)
            elapsed=round(time.monotonic()-starts,1)
            snapshots.append(dict(seconds=elapsed,confirmed_tasks=len(task_completions),completed_checks=len(feed_completions),requests=len(calls)))
            print(f'full_list_progress users={users} seconds={elapsed} confirmed={len(task_completions)} checks={len(feed_completions)}',flush=True)
    tasks=[asyncio.create_task(fn()) for fn in (today_clients,observe_copy,execute,check_feed,images,monitor)]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks),limit-starts+20)
        expected={item.user.id:item.owner.address.lower() for item in items}
        async with lab.factory() as db:
            rows=(await db.scalars(select(FeedWalletCheck))).all();fresh=0;unverified_whitelist=0
            assert len(rows)==users*collections and all(row.status in ('complete','unverified') for row in rows)
            for row in rows:
                if row.result.get('address'):assert row.result['address'].lower()==expected[row.user_id]
                slug=opensea.collection_slug(next(drop.mint_page_url for drop in drops if drop.id==row.drop_id))
                i=next(i for i,item in enumerate(items) if item.user.id==row.user_id);j=list(details).index(slug)
                whitelist=next((s for s in row.result.get('stages',[]) if stage_kind(s['type'])=='signed'),None)
                if not whitelist or whitelist['eligibility']=='unverified':
                    unverified_whitelist+=1
                    assert row.result.get('note')
                else:assert whitelist['eligibility']==('eligible' if (i+j)%2==0 else 'not_eligible')
                presented=feed_checks.presentation(row)
                fresh+=presented['status']!='unverified'
                if aware(row.expires_at)<=datetime.now(timezone.utc):assert not presented['setup_enabled']
            assert await db.scalar(select(func.count()).select_from(MintPlan))==0
            assert await db.scalar(select(func.count()).select_from(AutomaticNonce))==users
            mint_tasks=(await db.scalars(select(MintTask))).all()
            for item in items:
                task=next(t for t in mint_tasks if t.wallet_id==item.wallet.id)
                auth=await db.get(MintAuthorization,task.authorization_id)
                assert task.status=='confirmed' and task.assigned_nonce==0
                assert (auth.snapshot,aware(task.expires_at_utc))==approval_before[task.id]
                receipt=lab.w.eth.get_transaction_receipt(task.transaction_hash)
                assert receipt.status==1 and receipt['from']==item.owner.address
                assert task.actual_total_cost_wei<=auth.total_spend_cap_wei
                grant=await db.get(AutomaticGrant,item.grant.id)
                assert grant.reserved_wei==0 and grant.spent_wei==task.actual_total_cost_wei
            for rule in (await db.scalars(select(CopyRule))).all():assert rule.reserved_wei==0
        assert Counter(signatures)==Counter(item.wallet.id for item in items)
        assert lab.nft.functions.totalSupply().call()==users+1
        for item in items:
            assert sum(lab.nft.functions.ownerOf(token).call()==item.owner.address for token in range(1,users+2))==1
        journal=CustodyVault().journal()
        try:
            assert journal.execute('SELECT count(*) FROM signed').fetchone()[0]==users
            assert journal.execute('SELECT count(*) FROM copy_signed').fetchone()[0]==case.copy_count
        finally:journal.close()
        starts_all=sorted(call['started'] for call in calls)
        mint_starts=sorted(call['started'] for call in calls if call['kind']=='mint')
        assert all(b-a>=1.8 for a,b in zip(starts_all,starts_all[1:])), 'Aggregate gap was bypassed'
        assert all(b-a>=19.8 for a,b in zip(mint_starts,mint_starts[1:])), 'Mint gap was bypassed'
        assert len(mint_starts)==users-case.copy_count
        counts=Counter(call['kind'] for call in calls)
        assert counts['eligibility']==users*collections-unverified_whitelist and counts['artwork']==collections
        save_report(dict(scenario='full_daily_list_real_pacing',database=case.engine.dialect.name,users=users,
            collections=collections,wallet_checks=users*collections,copy_tasks=case.copy_count,
            automatic_tasks=users-case.copy_count,kdf_iterations=iterations,confirmed_tasks=users,
            first_confirmation_seconds=round(min(task_completions.values()),3),last_confirmation_seconds=round(max(task_completions.values()),3),
            first_wallet_check_seconds=round(min(feed_completions.values()),3),last_wallet_check_seconds=round(max(feed_completions.values()),3),
            fresh_checks_at_end=fresh,expired_display_caches_at_end=users*collections-fresh,
            unverified_whitelist_checks=unverified_whitelist,verified_whitelist_checks=users*collections-unverified_whitelist,
            provider_requests=dict(counts),provider_delay_ms=summary([call['provider_delay_ms'] for call in calls]),
            request_gate_wait_ms=summary([w['wait_ms'] for w in waits]),
            gate_deferrals=dict(Counter(f"{w['phase'] or 'background'}:{w['reason']}" for w in waits if w['delay'])),
            today_api_ms=summary(samples),fresh_builder_span_seconds=round(mint_starts[-1]-mint_starts[0],3),
            progress=snapshots))
    finally:
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        if case.engine.dialect.name=='sqlite':event.remove(case.engine,'checkout',case.timeout)
