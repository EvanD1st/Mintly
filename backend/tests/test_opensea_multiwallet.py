"""Real local signer/cache regressions; not a production throughput benchmark.

Only the upstream mint builder is replaced. Consent, preflight validation,
the execution lock, custody keys, nonce reservations and SeaDrop execution run
through their normal paths. No approval snapshots are edited by these tests.
"""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import uuid

from eth_account import Account
from eth_account._utils.legacy_transactions import Transaction
from eth_abi import decode, encode
import pytest
from sqlalchemy import event, select

from app.config import settings
from app.models import AutomaticGrant, AutomaticNonce, MintAuthorization, MintTask, User, Wallet
from app.services import automatic, automatic_signer as signer, mint_instruction_cache as cache
from app.services.custody import CustodyVault, private_write
from app.services.mint_plans import aware
from app.services.opensea import OpenSeaClient, OpenSeaUnavailable
from app.services.seadrop_mint import PARAM_TYPE, SIGNED_SELECTOR, decode_mint
from test_automatic_evm import lab


@pytest.fixture
async def six_wallets(lab, monkeypatch, request):
    count=getattr(request,'param',6)
    # Give simultaneous test clients time to wait for the unchanged real lock
    # on slower developer machines. PostgreSQL uses its normal row locking.
    def busy_timeout(connection, *_):
        cursor=connection.cursor()
        cursor.execute('PRAGMA busy_timeout=120000')
        cursor.close()
    engine=lab.factory.kw['bind'].sync_engine
    if engine.dialect.name=='sqlite':event.listen(engine,'checkout',busy_timeout)
    signer._preflights.clear();signer._reconciled.clear()
    lab.kind='signed'
    build=OpenSeaClient.build_mint
    calls=[]
    available=False
    async def builder(self,slug,address,quantity):
        calls.append((slug,address,quantity))
        if not available:
            raise OpenSeaUnavailable('Instructions available at preflight',503,mint_reason='stage_not_active')
        return await build(self,slug,address,quantity)
    monkeypatch.setattr(OpenSeaClient,'build_mint',builder)
    login=await lab.client.post('/api/auth/login',json={'username':'admin','password':'Admin test password 123'})
    assert login.status_code==200,login.text
    headers={'Authorization':'Bearer '+login.json()['token']}
    member_headers=dict(lab.client.headers)
    password=(lab.tmp/'password').read_text()
    wallets=[]
    async with lab.factory() as db:
        admin=await db.scalar(select(User).where(User.username=='admin'))
        for i in range(count):
            if count==6:
                user=lab.user if i<3 else admin
            elif i==0:
                user=lab.user
            else:
                user=User(id=str(uuid.uuid4()),username=f'presale-scale-{i}',
                    password_hash=lab.user.password_hash,role='member',is_active=True,must_change_password=False)
                db.add(user);await db.flush()
            if i==0:
                owner,wallet,grant=lab.owner,lab.wallet,lab.grant
            else:
                owner=Account.create()
                assert lab.w.provider.make_request('hardhat_setBalance',[owner.address,hex(10**18)])['result'] is True
                wallet=Wallet(id=str(uuid.uuid4()),user_id=user.id,address=owner.address,
                    label=f'Disposable wallet {i}',signing_capability='custodial',is_demo=False)
                key_id,grant_id=str(uuid.uuid4()),str(uuid.uuid4())
                private_write(lab.tmp/f'{key_id}.keystore.json',json.dumps(Account.encrypt(owner.key,password,kdf='scrypt',iterations=1024)))
                policy=dict(grant_id=grant_id,key_id=key_id,user_id=user.id,wallet_id=wallet.id,account=owner.address,
                    chain_id=31337,contracts=[lab.nft.address],mint_kinds=['signed'],budget_wei=10**16,
                    max_task_wei=10**15,expires_at=lab.end)
                private_write(lab.tmp/f'{grant_id}.policy.json',json.dumps(policy))
                grant=AutomaticGrant(id=grant_id,user_id=user.id,wallet_id=wallet.id,chain_id=31337,account=owner.address,
                    context_hash=automatic.digest(policy),scope={k:policy[k] for k in ('contracts','mint_kinds','max_task_wei')},
                    budget_wei=policy['budget_wei'],expires_at=datetime.fromtimestamp(lab.end,timezone.utc),status='enabled')
                db.add(wallet);await db.flush();db.add(grant)
            wallets.append(SimpleNamespace(owner=owner,wallet=wallet,grant=grant,user=user,quantity=1+i%2))
        await db.commit()
    try:
        for i,item in enumerate(wallets):
            if count==6:
                owner_headers=headers if i>=3 else member_headers
            elif i==0:
                owner_headers=member_headers
            else:
                login=await lab.client.post('/api/auth/login',json={
                    'username':item.user.username,'password':'Member test password 123'})
                assert login.status_code==200,login.text
                owner_headers={'Authorization':'Bearer '+login.json()['token']}
            item.headers=owner_headers
            response=await lab.client.post('/api/tasks/arm',headers=owner_headers,json={**lab.request,
                'wallet_id':item.wallet.id,'grant_id':item.grant.id,'quantity':item.quantity,
                'mint_kind':'signed','onchain_stage_index':1,'conditional_eligibility':True,
                'idempotency_key':f'six-wallet-consent-{i}'})
            assert response.status_code==200,response.text
            item.task_id=response.json()['id']
            async with lab.factory() as db:
                task=await db.get(MintTask,item.task_id)
                auth=await db.get(MintAuthorization,task.authorization_id)
                assert auth.snapshot['execution'] is None and auth.user_consent_text
                item.snapshot=json.loads(json.dumps(auth.snapshot))
                item.intent=signer.intent_for(auth.snapshot,item.grant)
                item.deadline=aware(task.expires_at_utc)
        assert len(calls)==count and len({x.owner.address for x in wallets})==count
        assert len({x.user.id for x in wallets})==(2 if count==6 else count)
        available=True;calls.clear()
        # These are actual signer advance checks which validate upstream
        # calldata against SeaDrop, then persist private encrypted instructions.
        for item in wallets:
            response=await lab.signer_client.post(f'/tasks/{item.task_id}/preflight')
            assert response.status_code==200,response.text
        assert Counter(calls)==Counter(('local-test',x.owner.address,x.quantity) for x in wallets)
        journal=CustodyVault().journal()
        try:
            for item in wallets:
                item.execution=cache.get(journal,item.task_id,item.intent)
                assert item.execution is not None
            assert journal.execute('SELECT count(*) FROM signed').fetchone()[0]==0
        finally:journal.close()
        async with lab.factory() as db:
            assert not (await db.scalars(select(AutomaticNonce))).all()
        # Simulate a signer memory restart; preparation must use the durable cache.
        signer._preflights.clear();signer._reconciled.clear();calls.clear()
        lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start])
        lab.w.provider.make_request('evm_mine',[])
        yield SimpleNamespace(lab=lab,wallets=wallets,calls=calls)
    finally:
        signer._preflights.clear();signer._reconciled.clear()
        if engine.dialect.name=='sqlite':event.remove(engine,'checkout',busy_timeout)


async def assert_approvals_unchanged(case):
    async with case.lab.factory() as db:
        for item in case.wallets:
            task=await db.get(MintTask,item.task_id)
            auth=await db.get(MintAuthorization,task.authorization_id)
            assert auth.snapshot==item.snapshot
            assert aware(task.expires_at_utc)==item.deadline
            if task.next_attempt_at:assert aware(task.next_attempt_at)<=item.deadline


async def concurrent_prepare(case,monkeypatch,*,duplicates=False):
    """All six clients arrive before any acquires the real execution lock."""
    requests=case.wallets*(2 if duplicates else 1)
    arrived=0;ready=asyncio.Event();sessions=[]
    original=automatic.lock_execution
    async def coordinated_lock(db):
        nonlocal arrived
        arrived+=1;sessions.append(db)
        if arrived==len(requests):ready.set()
        await asyncio.wait_for(ready.wait(),10)
        await original(db)
    with monkeypatch.context() as patch:
        patch.setattr(automatic,'lock_execution',coordinated_lock)
        results=await asyncio.gather(*(case.lab.signer_client.post(f'/tasks/{x.task_id}/prepare') for x in requests))
    assert len({id(db) for db in sessions})==len(requests)
    return results


async def test_six_authorized_wallets_use_validated_cache_and_sign_once(six_wallets,monkeypatch):
    case=six_wallets;lab=case.lab
    signatures=[];reads=[]
    original_account=CustodyVault.account
    original_get=cache.get
    def counted_account(vault,policy):
        account=original_account(vault,policy)
        def sign(tx):
            signatures.append((policy['wallet_id'],dict(tx)))
            return account.sign_transaction(tx)
        return SimpleNamespace(sign_transaction=sign)
    def counted_get(journal,task,intent):
        result=original_get(journal,task,intent)
        reads.append((task,intent,result is not None))
        return result
    monkeypatch.setattr(CustodyVault,'account',counted_account)
    monkeypatch.setattr(cache,'get',counted_get)
    results=await concurrent_prepare(case,monkeypatch,duplicates=True)
    for result in results:assert result.status_code==200 and result.json()['status']=='prepared',result.text
    assert [x.json()['hash'] for x in results[:6]]==[x.json()['hash'] for x in results[6:]]
    results=results[:6]
    assert not case.calls
    assert Counter((task,intent,hit) for task,intent,hit in reads)==Counter((x.task_id,x.intent,True) for x in case.wallets)
    assert Counter(wallet for wallet,_ in signatures)==Counter(x.wallet.id for x in case.wallets)
    await assert_approvals_unchanged(case)
    async with lab.factory() as db:
        reservations=(await db.scalars(select(AutomaticNonce))).all()
        assert len(reservations)==6 and all(x.nonce==0 for x in reservations)
        for item,result in zip(case.wallets,results):
            task=await db.get(MintTask,item.task_id)
            assert task.assigned_nonce==0 and Account.recover_transaction(task.signed_tx_raw)==item.owner.address
            tx=Transaction.from_bytes(bytes.fromhex(task.signed_tx_raw[2:]))
            mint=decode_mint({'to':'0x'+tx.to.hex(),'value':str(tx.value),'data':'0x'+tx.data.hex()},
                lab.nft.address,item.owner.address,item.quantity)
            assert mint['kind']=='signed' and mint['params'][2:5]==(lab.start,lab.end,1)
            assert tx.nonce==0 and tx.gas*tx.gasPrice<=item.snapshot['fee_cap_wei']
            assert tx.value+tx.gas*tx.gasPrice<=item.snapshot['total_cap_wei']
            receipt=lab.w.eth.wait_for_transaction_receipt(lab.w.eth.send_raw_transaction(task.signed_tx_raw))
            assert receipt.status==1 and '0x'+bytes(receipt.transactionHash).hex()==result.json()['hash']
    # Concurrent duplicate deliveries reuse durable bytes even after inclusion.
    replays=await concurrent_prepare(case,monkeypatch)
    assert [x.json()['hash'] for x in replays]==[x.json()['hash'] for x in results]
    assert len(signatures)==6 and not case.calls
    assert lab.nft.functions.totalSupply().call()==sum(x.quantity for x in case.wallets)
    recipients=Counter(lab.nft.functions.ownerOf(token).call() for token in range(1,sum(x.quantity for x in case.wallets)+1))
    assert recipients==Counter({x.owner.address:x.quantity for x in case.wallets})
    journal=CustodyVault().journal()
    try:
        rows=journal.execute('SELECT * FROM signed').fetchall()
        assert len(rows)==6
        assert {(r['task'],r['intent'],r['address'],r['nonce']) for r in rows}=={
            (x.task_id,x.intent,x.owner.address.lower(),0) for x in case.wallets}
        assert journal.execute('SELECT count(*) FROM daily_signed').fetchone()[0]==6
    finally:journal.close()


async def test_six_cached_tasks_reject_wrong_scope_and_refresh_misses(six_wallets,monkeypatch):
    case=six_wallets
    types=['address','address','address','uint256',PARAM_TYPE,'uint256','bytes']
    journal=CustodyVault().journal()
    try:
        # Deliberately inject syntactically encrypted but out-of-scope cache
        # entries. The immutable approvals remain untouched.
        for i,item in enumerate(case.wallets[:4]):
            execution=dict(item.execution)
            values=list(decode(types,bytes.fromhex(execution['data'][10:])))
            if i==0:values[2]=case.wallets[1].owner.address
            if i==1:values[0]=case.lab.w.eth.accounts[4]
            if i==2:values[3]+=1;execution['value']=str(values[3]*10)
            if i==3:values[4]=(*values[4][:4],2,*values[4][5:])
            execution['data']='0x'+SIGNED_SELECTOR+encode(types,values).hex()
            cache.put(journal,item.task_id,item.intent,execution,item.snapshot['expiry'])
        journal.execute('DELETE FROM mint_instruction_cache WHERE task=?',(case.wallets[4].task_id,))
        journal.execute('UPDATE mint_instruction_cache SET expires_at=1 WHERE task=?',(case.wallets[5].task_id,))
        journal.commit()
    finally:journal.close()
    results=await concurrent_prepare(case,monkeypatch)
    assert [r.status_code for r in results]==[409,409,409,409,200,200]
    assert Counter(case.calls)==Counter(('local-test',x.owner.address,x.quantity) for x in case.wallets[4:])
    async with case.lab.factory() as db:
        for i,item in enumerate(case.wallets):
            task=await db.get(MintTask,item.task_id)
            assert bool(task.signed_tx_raw)==(i>=4)
        assert len((await db.scalars(select(AutomaticNonce))).all())==2
    journal=CustodyVault().journal()
    try:assert journal.execute('SELECT count(*) FROM signed').fetchone()[0]==2
    finally:journal.close()
    await assert_approvals_unchanged(case)


async def test_six_cache_misses_retry_within_original_deadlines_and_attempt_bound(six_wallets,monkeypatch):
    from app.automatic_worker import step
    case=six_wallets;lab=case.lab
    journal=CustodyVault().journal()
    try:
        journal.execute('DELETE FROM mint_instruction_cache');journal.commit()
    finally:journal.close()
    calls=[]
    async def unavailable(self,slug,address,quantity):
        calls.append((address,quantity))
        raise OpenSeaUnavailable('Shared mint permit unavailable',503,retry_after_seconds=20,mint_reason='rate_limited',upstream_status=429)
    monkeypatch.setattr(OpenSeaClient,'build_mint',unavailable)
    results=await concurrent_prepare(case,monkeypatch)
    assert [r.status_code for r in results]==[503]*6
    assert all(r.headers['Retry-After']=='20' for r in results)
    assert Counter(calls)==Counter((x.owner.address,x.quantity) for x in case.wallets)
    calls.clear()
    # Seed the final *operational retry count*, never an approval field. This
    # tests the default 40-attempt boundary without 39 redundant RPC failures.
    assert settings.OPENSEA_PREPARATION_MAX_ATTEMPTS==40
    first=min(case.wallets,key=lambda x:x.task_id)
    async with lab.factory() as db:
        (await db.get(MintTask,first.task_id)).preparation_attempts=39
        await db.commit()
    now=datetime.fromtimestamp(lab.end-10,timezone.utc)
    for _ in range(6):assert await step(lab.factory,lab.sign,now=now)
    assert len(calls)==6
    async with lab.factory() as db:
        for item in case.wallets:
            task=await db.get(MintTask,item.task_id)
            assert task.signed_tx_raw is None
            if item is first:
                assert task.status=='failed' and task.preparation_attempts==40
            else:
                assert task.status=='armed' and task.preparation_attempts==1
                assert aware(task.next_attempt_at)==item.deadline
        assert not (await db.scalars(select(AutomaticNonce))).all()
    assert not await step(lab.factory,lab.sign,now=datetime.fromtimestamp(lab.end-1,timezone.utc))
    for _ in range(5):assert await step(lab.factory,lab.sign,now=datetime.fromtimestamp(lab.end,timezone.utc))
    assert not await step(lab.factory,lab.sign,now=datetime.fromtimestamp(lab.end,timezone.utc))
    assert len(calls)==6  # No provider polling at or beyond the deadline.
    async with lab.factory() as db:
        for item in case.wallets:
            assert (await db.get(MintTask,item.task_id)).status==('failed' if item is first else 'expired')
            assert (await db.get(AutomaticGrant,item.grant.id)).reserved_wei==0
    journal=CustodyVault().journal()
    try:assert journal.execute('SELECT count(*) FROM signed').fetchone()[0]==0
    finally:journal.close()
    await assert_approvals_unchanged(case)
