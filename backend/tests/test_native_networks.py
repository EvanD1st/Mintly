"""Native units, independent limits and real signing on disposable chain IDs.

The local EVM exercises actual SeaDrop/signatures/nonces. L2/L3 oracle RPC
responses are instrumented separately; this is not a production fee benchmark.
"""
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import json
import uuid
import os
from unittest.mock import AsyncMock
import pytest
from eth_abi import encode
from eth_account import Account
from fastapi import HTTPException
from sqlalchemy import select
from web3.datastructures import AttributeDict
from app.config import settings
from app.models import User,NativeDailyLimit,DailyDebit,MintTask,MintAuthorization,AutomaticGrant,CopyEvent,CopyRule
from app.services import automatic,daily_budget,automatic_fees
from app.services.networks import NETWORKS,symbol,require_currency,advertised
from app.services.opensea import CHAINS,chain_rpc
from app.services.custody import CustodyVault,private_read
from test_automatic_evm import lab
from test_copy_mints import copying


@pytest.mark.parametrize('chain',[999,33139,57073])
def test_new_network_identity_opt_in_and_rpc_validation(monkeypatch,chain):
    n=NETWORKS[chain]
    assert CHAINS[n.slug] == (chain,n.name)
    monkeypatch.setattr(settings,'AUTOMATIC_CHAIN_ID',4663)
    monkeypatch.setattr(settings,'ENABLE_CUSTODIAL_AUTOMATIC',True)
    monkeypatch.setattr(settings,n.opt_in,False)
    with pytest.raises(HTTPException): automatic.enabled(chain)
    monkeypatch.setattr(settings,n.opt_in,True)
    monkeypatch.setattr(settings,n.rpc_setting,'https://rpc.example.test')
    automatic.enabled(chain)
    assert automatic.rpc_for(chain)==chain_rpc(n.slug)=='https://rpc.example.test'
    assert any(v['chain_id']==chain for v in advertised(native_currencies=True))
    if symbol(chain)!='ETH': assert not any(v['chain_id']==chain for v in advertised())
    monkeypatch.setattr(settings,n.rpc_setting,'http://rpc.example.test')
    with pytest.raises(HTTPException): automatic.enabled(chain)


@pytest.mark.parametrize('chain',[999,33139])
def test_wide_budgets_are_exact_but_each_transaction_stays_bounded(chain):
    assert automatic.budget_wei('12.500000000000000001',chain)==12500000000000000001
    require_currency(chain,symbol(chain))
    for value in (None,'ETH'):
        with pytest.raises(HTTPException): require_currency(chain,value)
    for amount in ('1000000','0.0000000000000000001','NaN','-1'):
        with pytest.raises(HTTPException): automatic.budget_wei(amount,chain)
    with pytest.raises(HTTPException): automatic.wei('12.5')
    with pytest.raises(HTTPException): automatic.budget_wei('12.5',1)


async def test_native_daily_limits_roundtrip_exact_and_do_not_reset_eth(test_db):
    user=(await test_db.scalars(select(User).where(User.username=='member'))).one()
    user_id=user.id
    user.daily_limit_wei=123;user.daily_limit_revision=4
    before=daily_budget.configuration(user)
    for c,value in [('HYPE',4250000000000000001),('APE',12500000000000000001)]:
        owner=await daily_budget.limit_owner(test_db,user,c,create=True)
        owner.daily_limit_wei=value;owner.daily_limit_revision=1
        assert daily_budget.configuration(owner)['currency']==c
    await test_db.commit();test_db.expire_all()
    for c,value in [('HYPE',4250000000000000001),('APE',12500000000000000001)]:
        assert (await test_db.get(NativeDailyLimit,(user_id,c))).daily_limit_wei==value
    user=await test_db.get(User,user_id)
    assert daily_budget.configuration(user)==before
    assert 'currency' not in before  # Existing immutable ETH journal hash is unchanged.


@pytest.mark.parametrize('chain',[8453,57073])
async def test_op_stack_quote_and_receipt_include_outside_gas_fees(chain):
    calls=AsyncMock(side_effect=[encode(['uint256'],[1000]),encode(['uint256'],[200])])
    w=SimpleNamespace(eth=SimpleNamespace(call=calls))
    assert await automatic_fees.maximum_fee(w,{'data':'0x1234'},chain,100,10)==2800
    receipt=AttributeDict(dict(gasUsed=100,effectiveGasPrice=10,status=1,l1Fee='0x64',operatorFee='0x14',blockNumber=5))
    assert await automatic_fees.receipt_cost(w,receipt,chain,200)==1320
    receipt=AttributeDict({k:v for k,v in receipt.items() if k!='l1Fee'})
    with pytest.raises(ValueError,match='parent fee'): await automatic_fees.receipt_cost(w,receipt,chain,200)


@pytest.mark.parametrize('chain',[4663,33139])
async def test_nitro_quote_uses_total_parent_inclusive_gas(chain):
    class Eth:
        @property
        async def gas_price(self): return 10
        estimate_gas=AsyncMock(return_value=100)
        call=AsyncMock(return_value=encode(['uint64','uint64','uint256','uint256'],[200,50,20,30]))
    gas,price=await automatic_fees.quote_gas(SimpleNamespace(eth=Eth()),{'from':'0x'+'1'*40,'to':'0x'+'2'*40,'value':0,'data':'0x1234'},chain)
    assert (gas,price)==(240,24)
    assert await automatic_fees.additional_fee(None,chain,gas,300)==0


@pytest.mark.parametrize('lab',[999,33139,57073],indirect=True)
@pytest.mark.parametrize('kind',['public','allowlist','signed'])
async def test_native_chain_real_signer_and_seadrop_mint_once(lab,monkeypatch,kind):
    chain=lab.w.eth.chain_id
    # Only fee-oracle transport is instrumented: Hardhat has no Nitro/OP precompiles.
    async def maximum(w,tx,chain_id,gas,price): return gas*price
    monkeypatch.setattr('app.services.automatic_signer.maximum_fee',maximum)
    async def local_quote(w,tx,chain_id): return ((await w.eth.estimate_gas(tx))*120+99)//100,await w.eth.gas_price
    monkeypatch.setattr(automatic_fees,'quote_gas',local_quote)
    monkeypatch.setattr('app.services.automatic_signer.quote_gas',local_quote)
    lab.kind=kind;lab.request['mint_kind']=kind
    if symbol(chain)!='ETH':
        missing={k:v for k,v in lab.request.items() if k!='native_symbol'}
        assert (await lab.client.post('/api/tasks/arm',json=missing)).status_code==422
        async with lab.factory() as db:
            user=await db.get(User,lab.user.id);user.daily_limit_wei=1
            await db.commit()  # An ETH cap must not consume HYPE/APE headroom.
    response=await lab.client.post('/api/tasks/arm',json=lab.request)
    assert response.status_code==200,response.text
    task_id=response.json()['id']
    assert response.json()['native_symbol']==symbol(chain)
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    first=await lab.sign(task_id);second=await lab.sign(task_id)
    assert first==second
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert Account.recover_transaction(task.signed_tx_raw)==lab.owner.address
        from eth_account._utils.legacy_transactions import Transaction
        tx=Transaction.from_bytes(bytes.fromhex(task.signed_tx_raw[2:]))
        assert (tx.v-35)//2==chain and tx.nonce==lab.w.eth.get_transaction_count(lab.owner.address)
        signed=task.signed_tx_raw
        debit=await db.get(DailyDebit,task_id)
        assert debit.currency==symbol(chain)
    receipt=lab.w.eth.wait_for_transaction_receipt(lab.w.eth.send_raw_transaction(signed))
    assert receipt.status==1 and lab.nft.functions.ownerOf(1).call()==lab.owner.address
    assert lab.nft.functions.totalSupply().call()==2
    journal=CustodyVault().journal()
    assert journal.execute('SELECT count(*) FROM signed').fetchone()[0]==1
    assert journal.execute('SELECT chain FROM signed').fetchone()[0]==chain
    journal.close()


def test_postgres_native_migration_preserves_old_approvals_and_large_integer(monkeypatch):
    """Upgrade a separate disposable database, including real PostgreSQL casts."""
    import asyncio
    import asyncpg
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.models import Wallet
    url=os.environ.get('MINTLY_TEST_DATABASE_URL','')
    if not url.startswith('postgresql+asyncpg://'): pytest.skip('Disposable PostgreSQL is required')
    base=make_url(url)
    assert base.host in ('127.0.0.1','localhost') and base.database.startswith('mintly_test')
    database='mintly_test_native_upgrade_'+uuid.uuid4().hex[:10]
    async def database_action(action):
        conn=await asyncpg.connect(host=base.host,port=base.port,user=base.username,password=base.password,database=base.database)
        try: await conn.execute(f'{action} DATABASE "{database}"')
        finally: await conn.close()
    asyncio.run(database_action('CREATE'))
    migration_url=base.set(database=database).render_as_string(hide_password=False)
    monkeypatch.setattr(settings,'DATABASE_URL',migration_url)
    async def records(after=False):
        engine=create_async_engine(migration_url)
        try:
            async with engine.begin() as conn:
                if not after:
                    await conn.execute(User.__table__.insert().values(id='owner',username='migration-owner',password_hash='unused',role='member'))
                    await conn.execute(Wallet.__table__.insert().values(id='wallet',user_id='owner',address='0x'+'1'*40,label='Wallet',signing_capability='custodial',supported_chains=['Ethereum']))
                    await conn.execute(AutomaticGrant.__table__.insert().values(id='grant',user_id='owner',wallet_id='wallet',chain_id=1,account='0x'+'1'*40,context_hash='unchanged-approval',scope={'max_task_wei':42},expires_at=datetime.now(timezone.utc)+timedelta(days=1),budget_wei=42,reserved_wei=7,spent_wei=3))
                else:
                    row=(await conn.execute(select(AutomaticGrant.__table__))).mappings().one()
                    assert (row['budget_wei'],row['reserved_wei'],row['spent_wei'])==(42,7,3)
                    assert row['context_hash']=='unchanged-approval' and row['scope']=={'max_task_wei':42}
                    await conn.execute(AutomaticGrant.__table__.update().values(budget_wei=12500000000000000001))
                    assert (await conn.execute(select(AutomaticGrant.budget_wei))).scalar_one()==12500000000000000001
        finally: await engine.dispose()
    try:
        command.upgrade(Config('alembic.ini'),'022_opensea_owner_fairness')
        asyncio.run(records())
        command.upgrade(Config('alembic.ini'),'head')
        asyncio.run(records(after=True))
    finally: asyncio.run(database_action('DROP'))


@pytest.mark.parametrize('lab',[999,33139],indirect=True)
async def test_wide_native_lifetime_reservations_never_overflow_or_overspend(lab,monkeypatch):
    async def quote(w,tx,chain_id): return ((await w.eth.estimate_gas(tx))*120+99)//100,await w.eth.gas_price
    async def maximum(w,tx,chain_id,gas,price): return gas*price
    monkeypatch.setattr('app.services.automatic_signer.quote_gas',quote)
    monkeypatch.setattr('app.services.automatic_signer.maximum_fee',maximum)
    policy_path=lab.tmp/f'{lab.grant.id}.policy.json'
    policy=json.loads(private_read(policy_path))
    policy.update(budget_wei=12500000000000000000,max_task_wei=6000000000000000020)
    # Establish the disposable approval before the first signature or journal pin.
    policy_path.write_text(json.dumps(policy),encoding='utf-8')
    async with lab.factory() as db:
        grant=await db.get(AutomaticGrant,lab.grant.id)
        grant.budget_wei=policy['budget_wei'];grant.scope={**grant.scope,'max_task_wei':policy['max_task_wei']}
        grant.context_hash=automatic.digest(policy)
        await db.commit()
    lab.w.provider.make_request('hardhat_setBalance',[lab.owner.address,hex(20*10**18)])
    request={**lab.request,'fee_cap_eth':'6','total_cap_eth':'6.00000000000000002'}
    ids=[]
    for i in range(2):
        response=await lab.client.post('/api/tasks/arm',json={**request,'idempotency_key':f'wide-native-intent-{i}'})
        assert response.status_code==200,response.text
        ids.append(response.json()['id'])
    assert (await lab.client.post('/api/tasks/arm',json={**request,'idempotency_key':'over-wide-native-budget'})).status_code==409
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.sign(ids[0])
    assert (await lab.sign(ids[1]))['status']=='armed'  # Preserve the unresolved-nonce guard.
    async with lab.factory() as db:
        first=await db.get(MintTask,ids[0])
        lab.w.eth.send_raw_transaction(first.signed_tx_raw)
    # One confirmation: the first lifetime liability must still be counted in full.
    await lab.sign(ids[1])
    journal=CustodyVault().journal()
    rows=journal.execute('SELECT liability,nonce FROM signed ORDER BY nonce').fetchall()
    assert sum(row['liability'] for row in rows)==12000000000000000040
    assert [row['nonce'] for row in rows]==[0,1]
    journal.close()


@pytest.mark.parametrize('lab',[999,33139,57073],indirect=True)
async def test_native_source_observation_prepares_one_owned_copy(copying,monkeypatch):
    c=copying;lab=c['lab'];chain=lab.w.eth.chain_id
    async def quote(w,tx,chain_id,paid=False): return ((await w.eth.estimate_gas(tx))*120+99)//100,await w.eth.gas_price
    async def maximum(w,tx,chain_id,gas,price): return gas*price
    monkeypatch.setattr('app.services.copy_mints.copy_gas_quote',quote)
    monkeypatch.setattr('app.services.copy_mints.maximum_fee',maximum)
    monkeypatch.setattr('app.services.automatic_signer.quote_gas',quote)
    monkeypatch.setattr('app.services.automatic_signer.maximum_fee',maximum)
    assert (await c['approve']())['status']=='active'
    await c['mint']();await c['scan']()
    async with lab.factory() as db:
        event=(await db.scalars(select(CopyEvent))).one()
        assert event.task_id,event.note
        task_id=event.task_id
        auth=await db.get(MintAuthorization,(await db.get(MintTask,task_id)).authorization_id)
        assert auth.snapshot['chain_id']==chain and auth.snapshot['account']==lab.owner.address
    await lab.sign(task_id)
    journal=CustodyVault().journal()
    assert journal.execute('SELECT count(*) FROM copy_signed').fetchone()[0]==1
    journal.close()


@pytest.mark.parametrize('lab',[999,33139],indirect=True)
async def test_native_daily_limit_is_independently_pinned_and_carries_reservations(lab,monkeypatch):
    currency=symbol(lab.w.eth.chain_id)
    async def signer(user_id,operation,coin='ETH'):
        method=lab.signer_client.post if operation=='register' else lab.signer_client.get
        result=await method(f'/account-limits/{user_id}/{operation}?currency={coin}')
        result.raise_for_status();return result.json()
    monkeypatch.setattr('app.api.automatic.signer_limit',signer)
    result=await lab.client.post('/api/automatic/daily-limit',json={'limit_eth':'12.500000000000000001','currency':currency,'consent':True})
    assert result.status_code==200,result.text
    assert result.json()['limit_wei']=='12500000000000000001'
    journal=CustodyVault().journal()
    pin=journal.execute('SELECT * FROM native_daily_limits WHERE user_id=? AND currency=?',(lab.user.id,currency)).fetchone()
    assert json.loads(pin['configuration'])['limit_wei']==12500000000000000001
    assert not journal.execute('SELECT * FROM daily_limits WHERE user_id=?',(lab.user.id,)).fetchone()
    journal.close()
    result=await lab.client.post('/api/automatic/daily-limit',json={'limit_eth':'0.0006','currency':currency,'consent':True})
    assert result.status_code==200,result.text
    armed=await lab.client.post('/api/tasks/arm',json=lab.request)
    assert armed.status_code==200,armed.text
    other=await lab.client.post('/api/tasks/arm',json={**lab.request,'idempotency_key':'another-bounded-native-mint'})
    assert other.status_code==429,other.text
    usage=(await lab.client.get(f'/api/automatic/daily-limit?currency={currency}')).json()
    assert usage['reserved_wei']=='500000000000020'
    assert (await lab.client.get('/api/automatic/daily-limit')).json()['reserved_wei']=='0'
    async with lab.factory() as db:
        owner=await db.get(NativeDailyLimit,(lab.user.id,currency));owner.daily_limit_wei=12500000000000000001
        await db.commit()
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    assert (await lab.signer_client.post(f'/tasks/{armed.json()["id"]}/prepare')).status_code==409


@pytest.mark.parametrize('lab',[999,33139],indirect=True)
async def test_mixed_currency_copy_budget_is_rejected_before_watching_or_signing(copying,monkeypatch):
    c=copying;lab=c['lab']
    monkeypatch.setattr(settings,'ENABLE_ETHEREUM_AUTOMATIC',True)
    eth_id=str(uuid.uuid4())
    async with lab.factory() as db:
        db.add(AutomaticGrant(id=eth_id,user_id=lab.user.id,wallet_id=lab.wallet.id,chain_id=1,account=lab.owner.address,
            context_hash=automatic.digest(['distinct-eth-policy',eth_id]),scope=lab.grant.scope,
            budget_wei=10**16,reserved_wei=0,spent_wei=0,status='enabled',expires_at=lab.grant.expires_at))
        await db.commit()
    request={k:v for k,v in c['request'].items() if k!='grant_id'}
    request['grant_ids']=[lab.grant.id,eth_id]
    result=await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/wallet-rules',json=request)
    assert result.status_code==422 and 'separate copy limits' in result.text
    async with lab.factory() as db:
        assert not (await db.scalars(select(CopyRule))).all()
    journal=CustodyVault().journal()
    assert journal.execute('SELECT count(*) FROM copy_rules').fetchone()[0]==0
    journal.close()


@pytest.mark.parametrize('chain', [999, 33139])
def test_saved_copy_budget_is_exact_without_mutating_pinned_group(chain):
    from app.api.copy_mints import public_rule
    budget = 12500000000000000001
    snapshot = dict(price_cap_wei=0, fee_cap_wei=100, total_cap_wei=100, budget_wei=budget,
        budget_group={'id': 'group', 'members': ['rule'], 'budget_wei': budget})
    before = automatic.digest(snapshot)
    rule = SimpleNamespace(id='rule', watch_id='watch', chain_id=chain, status='active',
        expires_at=datetime.now(timezone.utc)+timedelta(days=1), snapshot=snapshot,
        budget_wei=budget, spent_wei=0, reserved_wei=0)
    response = public_rule(rule)
    assert response['saved_budget_wei'] == '12500000000000000001'
    assert automatic.digest(snapshot) == before
    assert response['snapshot']['budget_group']['budget_wei'] == budget
