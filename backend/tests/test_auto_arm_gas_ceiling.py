"""Auto-Arming gas ceilings, quoted holds, and crash-safe signed liability."""
from datetime import datetime,timezone
from eth_account._utils.legacy_transactions import Transaction
from fastapi import HTTPException
import pytest
from app.models import MintTask,MintAuthorization,AutomaticGrant,DailyDebit
from app.services import auto_arm_funding as funding
from app.services.custody import CustodyVault
from app.services.custody_recovery import recover_task
from test_feed_automation_evm import free_feed,arm_free
from test_automatic_evm import lab,recovery_clock


def test_eth_ceiling_is_exact_and_does_not_expand_smaller_approvals():
    cap=20_000_000_000_000
    assert funding.ETH_GAS_CEILING_WEI==cap
    for chain in (1,8453,4663,57073):
        assert funding.fee_ceiling(chain,10**16)==cap
        assert funding.fee_ceiling(chain,cap-1)==cap-1
        s={'chain_id':chain,'feed_approval_id':'approved','fee_cap_wei':10**16,'total_cap_wei':10**16}
        assert funding.execution_liability(s,0,cap)==cap
        with pytest.raises(HTTPException) as caught:funding.execution_liability(s,0,cap+1)
        assert caught.value.status_code==503 and 'Waiting for lower fees' in caught.value.detail
        assert caught.value.headers['X-Mintly-Reason']=='auto_arm_gas_limit'
    for chain,approved in ((33139,9*10**18),(999,10**17)):
        assert funding.fee_ceiling(chain,approved)==approved
    manual={'chain_id':1,'fee_cap_wei':10**16,'total_cap_wei':10**16}
    assert funding.execution_liability(manual,0,cap+1)==10**16


def open_phase(lab,monkeypatch):
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start])
    lab.w.provider.make_request('evm_mine',[])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromtimestamp(lab.w.eth.get_block('latest').timestamp,tz)
    monkeypatch.setattr('app.services.automatic_signer.datetime',Clock)


async def test_existing_unsigned_approval_cannot_bypass_new_cap(free_feed,monkeypatch):
    f=free_feed;lab=f['lab'];task_id,_=await arm_free(f)
    # Simulate an already-armed older approval; never edit its immutable snapshot.
    monkeypatch.setattr(funding,'ETH_GAS_CEILING_WEI',20_000_000_000_000)
    open_phase(lab,monkeypatch)
    response=await lab.signer_client.post('/tasks/'+task_id+'/prepare')
    assert response.status_code==503 and 'Waiting for lower fees' in response.text,response.text
    assert response.headers['X-Mintly-Reason']=='auto_arm_gas_limit'
    from app.services.mint_diagnostics import category
    import httpx
    error=httpx.HTTPStatusError('Gas ceiling',request=response.request,response=response)
    assert category([],503,error)=='auto_arm_gas_limit'
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);auth=await db.get(MintAuthorization,task.authorization_id)
        assert task.signed_tx_raw is None and task.transaction_hash is None
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==funding.QUEUED_WEI
        assert auth.total_spend_cap_wei>funding.ETH_GAS_CEILING_WEI
    journal=CustodyVault().journal()
    try:assert journal.execute('SELECT count(*) FROM signed').fetchone()[0]==0
    finally:journal.close()
    queue=(await lab.client.get('/api/tasks/queue')).json()['tasks'][0]
    assert queue['effective_fee_cap_eth']=='0.00002' and queue['reserved_now_eth']=='0.00001'


@pytest.mark.parametrize('budget',['policy','daily'])
async def test_only_buffered_quote_is_reserved_and_replay_restores_it(free_feed,monkeypatch,budget):
    f=free_feed;lab=f['lab'];task_id,_=await arm_free(f)
    async with lab.factory() as db:
        auth=await db.get(MintAuthorization,(await db.get(MintTask,task_id)).authorization_id)
        cap=auth.total_spend_cap_wei
        if budget=='policy':
            grant=await db.get(AutomaticGrant,lab.grant.id)
            grant.spent_wei=grant.budget_wei-cap+1  # Less than the full approval remains.
        else:
            from app.models import User
            from app.services import daily_budget
            owner=await db.get(User,lab.user.id)
            owner.daily_limit_wei=cap-1
            owner.daily_limit_revision=1
            journal=CustodyVault().journal()
            try:
                config=daily_budget.configuration(owner)
                from app.services.automatic import digest
                journal.execute('INSERT INTO daily_limits(user_id,revision,intent,configuration) VALUES(?,?,?,?)',
                    (owner.id,owner.daily_limit_revision,digest(config),__import__('json').dumps(config)))
                journal.commit()
            finally:journal.close()
        await db.commit()
    open_phase(lab,monkeypatch)
    await lab.sign(task_id)
    journal=CustodyVault().journal()
    try:entry=dict(journal.execute('SELECT * FROM signed WHERE task=?',(task_id,)).fetchone())
    finally:journal.close()
    signed=Transaction.from_bytes(bytes.fromhex(entry['raw'][2:]))
    assert entry['liability']==signed.value+signed.gas*signed.gasPrice
    assert 0<entry['liability']<cap
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);grant=await db.get(AutomaticGrant,lab.grant.id)
        debit=await db.get(DailyDebit,task_id)
        assert debit.maximum_wei==grant.reserved_wei==entry['liability']
        task.signed_tx_raw=None;task.transaction_hash=None;task.status='armed'
        grant.reserved_wei=funding.QUEUED_WEI;debit.maximum_wei=funding.QUEUED_WEI
        await db.commit()
    await lab.sign(task_id)
    async with lab.factory() as db:
        assert (await db.get(MintTask,task_id)).signed_tx_raw==entry['raw']
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==entry['liability']
        assert (await db.get(DailyDebit,task_id)).maximum_wei==entry['liability']


async def test_same_nonce_recovery_reserves_larger_quote_once(free_feed,monkeypatch,recovery_clock):
    f=free_feed;lab=f['lab'];task_id,_=await arm_free(f)
    open_phase(lab,monkeypatch);await lab.sign(task_id)
    journal=CustodyVault().journal()
    try:old=dict(journal.execute('SELECT * FROM signed WHERE task=?',(task_id,)).fetchone())
    finally:journal.close()
    async with lab.factory() as db:
        result=await recover_task(db,task_id,lab.user.id,datetime.fromtimestamp(lab.end,timezone.utc),'bounded-free-recovery')
        task=await db.get(MintTask,task_id);auth=await db.get(MintAuthorization,task.authorization_id)
        replacement=Transaction.from_bytes(bytes.fromhex(task.signed_tx_raw[2:]))
        assert replacement.nonce==old['nonce']
        liability=max(old['liability'],replacement.value+replacement.gas*replacement.gasPrice)
        assert liability<=auth.total_spend_cap_wei
        assert (await db.get(DailyDebit,task_id)).maximum_wei==liability
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==liability
        assert result['hash']==task.transaction_hash
    journal=CustodyVault().journal()
    try:
        assert journal.execute('SELECT count(*) FROM signed').fetchone()[0]==1
        assert journal.execute('SELECT liability FROM signed WHERE task=?',(task_id,)).fetchone()[0]==liability
    finally:journal.close()
