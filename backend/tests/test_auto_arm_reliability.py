import copy,json,sqlite3,uuid
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.models import MintTask,MintAuthorization,AutomaticGrant,FeedMintApproval,FeedWalletCheck,User,Wallet,DailyDebit
from app.services import feed_automation,automatic
from app.services import auto_arm_funding as funding
from test_feed_automation_evm import free_feed,arm_free
from test_automatic_evm import lab


async def test_incomplete_check_does_not_access_contract_or_arm(free_feed):
    f=free_feed;lab=f['lab']
    async with lab.factory() as db:
        row=await db.get(FeedMintApproval,f['approval']['id'])
        check=await db.get(FeedWalletCheck,(lab.user.id,lab.wallet.id,lab.drop.id));check.result={};check.status='unverified'
        user=await db.get(User,lab.user.id);wallet=await db.get(Wallet,lab.wallet.id)
        assert await feed_automation.arm(db,row,{},check,user,wallet) is None
        assert 'not verified' in row.note
        assert not (await db.scalars(select(MintTask))).all()


def test_actionable_preparation_errors():
    from app.services.opensea import OpenSeaUnavailable
    assert 'incomplete' in feed_automation.preparation_error(KeyError('contract_address'))
    assert feed_automation.preparation_error(HTTPException(409,'OpenSea permission expired.'))=='OpenSea permission expired.'
    assert 'temporarily unavailable' in feed_automation.preparation_error(OpenSeaUnavailable('OpenSea is temporarily unavailable.',503))
    assert 'secret' not in feed_automation.preparation_error(RuntimeError('secret'))


async def test_tiny_reservation_is_released_exactly_on_disarm(free_feed):
    f=free_feed;lab=f['lab'];task_id,_=await arm_free(f)
    async with lab.factory() as db:
        grant=await db.get(AutomaticGrant,lab.grant.id)
        debit=await db.get(DailyDebit,task_id)
        assert grant.reserved_wei==debit.maximum_wei==funding.QUEUED_WEI
    response=await lab.client.post('/api/tasks/'+task_id+'/disarm')
    assert response.status_code==200,response.text
    async with lab.factory() as db:
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==0
        assert (await db.get(DailyDebit,task_id)).actual_wei==0


async def test_turn_off_restores_recorded_liability_after_lost_database_commit(free_feed,monkeypatch):
    f=free_feed;lab=f['lab'];task_id,_=await arm_free(f)
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromtimestamp(lab.w.eth.get_block('latest').timestamp,tz)
    monkeypatch.setattr('app.services.automatic_signer.datetime',Clock)
    await lab.sign(task_id)
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);raw=task.signed_tx_raw
        auth=await db.get(MintAuthorization,task.authorization_id)
        cap=(await db.get(DailyDebit,task_id)).maximum_wei
        assert 0<cap<auth.total_spend_cap_wei
        task.signed_tx_raw=None;task.transaction_hash=None;task.status='armed'
        debit=await db.get(DailyDebit,task_id);grant=await db.get(AutomaticGrant,lab.grant.id)
        grant.reserved_wei-=debit.maximum_wei-funding.QUEUED_WEI;debit.maximum_wei=funding.QUEUED_WEI
        await db.commit()
    response=await lab.client.delete('/api/automatic/free-drops/'+f['approval']['id'])
    assert response.status_code==200,response.text
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert task.status=='uncertain' and task.signed_tx_raw==raw and task.broadcast_disabled_at
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==cap
        assert (await db.get(DailyDebit,task_id)).maximum_wei==cap
    assert lab.nft.functions.totalSupply().call()==0


@pytest.mark.parametrize('limiter',['policy','daily'])
async def test_earlier_opening_preempts_later_unsigned_reservation(free_feed,limiter):
    f=free_feed;lab=f['lab'];late_id,_=await arm_free(f)
    async with lab.factory() as db:
        late=await db.get(MintTask,late_id);a=await db.get(MintAuthorization,late.authorization_id)
        grant=await db.get(AutomaticGrant,lab.grant.id)
        early_auth=MintAuthorization(id=str(uuid.uuid4()),wallet_id=a.wallet_id,drop_id=a.drop_id,stage_id=a.stage_id,
            quantity=a.quantity,max_price_per_token_wei=0,max_fee_wei=a.max_fee_wei,total_spend_cap_wei=a.total_spend_cap_wei,
            recipient_address=a.recipient_address,user_consent_text=a.user_consent_text,authorized_at=a.authorized_at,
            snapshot=copy.deepcopy(a.snapshot),grant_id=a.grant_id)
        db.add(early_auth);await db.flush()
        early=MintTask(id=str(uuid.uuid4()),authorization_id=early_auth.id,wallet_id=late.wallet_id,
            drop_id=late.drop_id,stage_id=late.stage_id,status='armed',is_demo=False,execution_mode=automatic.MODE,
            idempotency_key=str(uuid.uuid4()),scheduled_for_utc=late.scheduled_for_utc-timedelta(hours=1),expires_at_utc=late.expires_at_utc)
        db.add(early);await db.flush()
        db.add(DailyDebit(task_id=early.id,user_id=lab.user.id,day='2026-11-08',maximum_wei=funding.QUEUED_WEI,currency='ETH'))
        grant.reserved_wei+=funding.QUEUED_WEI
        # Simulate a legacy 4pm hold that filled almost all the policy.
        await funding.resize(db,late,a,grant,a.total_spend_cap_wei)
        if limiter=='policy':grant.spent_wei=grant.budget_wei-a.total_spend_cap_wei-funding.QUEUED_WEI
        else:
            user=await db.get(User,lab.user.id);user.daily_limit_wei=a.total_spend_cap_wei
        now=datetime.now(timezone.utc)+timedelta(hours=3)
        journal=sqlite3.connect(':memory:');journal.execute('CREATE TABLE signed(task TEXT)')
        try:
            with pytest.raises(HTTPException) as caught:
                await funding.fund(db,late,a,grant,journal=journal,now=now)
            assert 'priority' in caught.value.detail
            journal.execute('INSERT INTO signed VALUES (?)',(late.id,))
            if limiter=='policy':
                with pytest.raises(HTTPException):
                    await funding.fund(db,early,early_auth,grant,journal=journal,now=now)
            assert (await db.get(DailyDebit,late.id)).maximum_wei==a.total_spend_cap_wei
            journal.execute('DELETE FROM signed')
            await funding.fund(db,early,early_auth,grant,journal=journal,now=now)
            assert (await db.get(DailyDebit,early.id)).maximum_wei==a.total_spend_cap_wei
            assert (await db.get(DailyDebit,late.id)).maximum_wei<=funding.QUEUED_WEI
            assert grant.reserved_wei+grant.spent_wei<=grant.budget_wei
            if limiter=='daily':assert (await db.get(DailyDebit,late.id)).maximum_wei==0
        finally:journal.close()


@pytest.mark.parametrize('competing_quantity',[95,100])
async def test_max_quantity_shrinks_to_live_supply_and_replays_same_signature(free_feed,monkeypatch,competing_quantity):
    f=free_feed;lab=f['lab']
    assert (await lab.client.delete('/api/automatic/free-drops/'+f['approval']['id'])).status_code==200
    response=await lab.client.post('/api/automatic/free-drops/enable',json={'request_id':str(uuid.uuid4()),'wallet_id':lab.wallet.id,'consent':True})
    assert response.status_code==200,response.text
    f['approval']=response.json()['approvals'][0]
    async with lab.factory() as db:
        from app.services.feed_sources import daily_collections
        from zoneinfo import ZoneInfo
        row=await db.get(FeedMintApproval,f['approval']['id'])
        user=await db.get(User,lab.user.id);wallet=await db.get(Wallet,lab.wallet.id)
        groups=await daily_collections(db,datetime.now(ZoneInfo('Africa/Lagos')).date(),user.id)
        check=await db.get(FeedWalletCheck,(user.id,wallet.id,lab.drop.id))
        assert await feed_automation.arm(db,row,groups[0],check,user,wallet)
        task=(await db.scalars(select(MintTask))).one();task_id=task.id
        task=await db.get(MintTask,task_id);auth=await db.get(MintAuthorization,task.authorization_id)
        original=copy.deepcopy(auth.snapshot);assert auth.quantity==20
    sea=lab.sea.address
    lab.w.provider.make_request('hardhat_setBalance',[sea,hex(10**18)])
    lab.w.provider.make_request('hardhat_impersonateAccount',[sea])
    receipt=lab.w.eth.wait_for_transaction_receipt(lab.nft.functions.mintSeaDrop(lab.w.eth.accounts[3],competing_quantity).transact({'from':sea,'gas':3000000}))
    assert receipt.status==1
    lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[sea])
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromtimestamp(lab.w.eth.get_block('latest').timestamp,tz)
    monkeypatch.setattr('app.services.automatic_signer.datetime',Clock)
    if competing_quantity==100:
        response=await lab.signer_client.post('/tasks/'+task_id+'/prepare')
        assert response.status_code==409 and 'sold out' in response.text,response.text
        assert response.headers['X-Mintly-Reason']=='supply_exhausted'
        async with lab.factory() as db:
            task=await db.get(MintTask,task_id)
            assert task.signed_tx_raw is None
            assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==funding.QUEUED_WEI
        return
    first=await lab.sign(task_id)
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);auth=await db.get(MintAuthorization,task.authorization_id)
        assert auth.snapshot==original and auth.quantity==20
        assert funding.quantity(task,auth.quantity)==5
        raw=task.signed_tx_raw
        # Lost DB commit must recover the existing private signature and count.
        task.signed_tx_raw=None;task.transaction_hash=None;task.status='armed';task.prepared_calldata=None
        debit=await db.get(DailyDebit,task_id);grant=await db.get(AutomaticGrant,lab.grant.id)
        grant.reserved_wei-=debit.maximum_wei-funding.QUEUED_WEI;debit.maximum_wei=funding.QUEUED_WEI
        await db.commit()
    assert (await lab.sign(task_id))['hash']==first['hash']
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert task.signed_tx_raw==raw and funding.quantity(task,20)==5
        receipt=lab.w.eth.wait_for_transaction_receipt(lab.w.eth.send_raw_transaction(raw))
        assert receipt.status==1
    assert lab.nft.functions.totalSupply().call()==100
