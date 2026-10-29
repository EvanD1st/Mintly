"""Real pending source -> approved copy submission before source inclusion."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import asyncio
from eth_abi import encode
import pytest
from eth_account import Account
from hexbytes import HexBytes
from sqlalchemy import select
from app.models import CopyEvent, CopyRule, MintTask, MintAuthorization, OpenSeaAccess, Wallet
from app.services import automatic, copy_mints, pending_copy, fast_copy
from app.services.custody import CustodyVault
from test_automatic_evm import lab
from test_copy_mints import copying


async def pending(c):
    lab=c['lab']
    if lab.w.eth.get_block('latest').timestamp<lab.start:
        lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start])
        lab.w.provider.make_request('evm_mine',[])
    lab.w.provider.make_request('evm_setAutomine',[False])
    tx=lab.sea.functions.mintPublic(lab.nft.address,lab.w.eth.accounts[1],c['source'].address,2).build_transaction({
        'from':c['source'].address,'nonce':lab.w.eth.get_transaction_count(c['source'].address),
        'gas':400000,'gasPrice':lab.w.eth.gas_price,'value':20,'chainId':31337})
    signed=c['source'].sign_transaction(tx)
    tx_hash=lab.w.eth.send_raw_transaction(signed.raw_transaction).to_0x_hex()
    web3=await automatic.provider()
    try:observation=await pending_copy.observe(web3,31337,tx_hash,c['source'].address,lab.nft.address)
    finally:await web3.provider.disconnect()
    return observation,signed


async def arm(c,observation):
    ids=await fast_copy.record(c['lab'].factory,31337,observation,pending=True)
    async with c['lab'].factory() as db:
        for wid in ids:await copy_mints.process_copy_events(db,wid,31337)
        await db.commit()
    events=(await c['lab'].client.get('/api/copy-mints/activity')).json()['events']
    return events[0] if events else None


async def test_copy_is_signed_and_submitted_while_source_is_still_pending(copying):
    c=copying;lab=c['lab'];await c['approve']()
    try:
        observation,_=await pending(c)
        event=await arm(c,observation)
        assert event and event['task_id'],event
        await lab.sign(event['task_id'])
        await lab.due();await lab.tick()
        async with lab.factory() as db:
            task=await db.get(MintTask,event['task_id'])
            assert task.status=='submitted' and task.signed_tx_raw
            assert lab.w.eth.get_transaction(task.transaction_hash).blockHash is None
        assert lab.w.eth.get_transaction(observation['source_hash']).blockHash is None
        lab.w.provider.make_request('evm_mine',[])
        lab.w.provider.make_request('evm_mine',[])
        await lab.due();await lab.tick()
        async with lab.factory() as db:assert (await db.get(MintTask,event['task_id'])).status=='confirmed'
        assert lab.nft.functions.getMintStats(lab.owner.address).call()[0]==1
        journal=CustodyVault().journal()
        assert journal.execute('SELECT COUNT(*) FROM copy_source_nonces').fetchone()[0]==1
        journal.close()
        # Confirmation upgrades the existing event, never creates another copy.
        w=await automatic.provider()
        try:confirmed=await copy_mints.observe(w,31337,observation['source_hash'],c['source'].address,lab.nft.address)
        finally:await w.provider.disconnect()
        await fast_copy.record(lab.factory,31337,confirmed)
        events=(await lab.client.get('/api/copy-mints/activity')).json()['events']
        assert len(events)==1 and events[0]['observation'].get('source_pending') is not True
    finally:lab.w.provider.make_request('evm_setAutomine',[True])


@pytest.mark.parametrize('mode',['watch_only','paused'])
async def test_pending_stream_never_enables_copying_for_unapproved_or_paused_users(copying,mode):
    c=copying;lab=c['lab']
    if mode=='paused':
        await c['approve']()
        await lab.client.post('/api/copy-mints/pause',json={'paused':True})
    try:
        observation,_=await pending(c)
        assert await arm(c,observation) is None
        assert (await lab.client.get('/api/tasks/queue')).json()['tasks']==[]
    finally:lab.w.provider.make_request('evm_setAutomine',[True])


async def test_cancelled_source_is_rejected_before_copy_signing(copying):
    c=copying;lab=c['lab'];await c['approve']()
    try:
        observation,_=await pending(c)
        event=await arm(c,observation)
        lab.w.provider.make_request('hardhat_dropTransaction',[observation['source_hash']])
        response=await lab.signer_client.post(f'/tasks/{event["task_id"]}/prepare')
        assert response.status_code!=200
        async with lab.factory() as db:assert not (await db.get(MintTask,event['task_id'])).signed_tx_raw
    finally:lab.w.provider.make_request('evm_setAutomine',[True])


async def test_operator_stop_blocks_pending_signing_without_altering_existing_approvals(copying,monkeypatch):
    from app.config import settings
    c=copying;lab=c['lab'];rule=await c['approve']()
    try:
        observation,_=await pending(c)
        event=await arm(c,observation)
        monkeypatch.setattr(settings,'ENABLE_PENDING_COPY',False)
        response=await lab.signer_client.post(f'/tasks/{event["task_id"]}/prepare')
        assert response.status_code==409 and response.headers['X-Mintly-Reason']=='pending_source_changed'
        async with lab.factory() as db:
            assert not (await db.get(MintTask,event['task_id'])).signed_tx_raw
            assert (await db.get(CopyRule,rule['id'])).status=='active'
    finally:lab.w.provider.make_request('evm_setAutomine',[True])


async def test_pending_path_cannot_increase_independently_pinned_spending_limits(copying):
    c=copying;lab=c['lab'];await c['approve']()
    try:
        observation,_=await pending(c);event=await arm(c,observation)
        async with lab.factory() as db:
            task=await db.get(MintTask,event['task_id']);auth=await db.get(MintAuthorization,task.authorization_id)
            auth.max_fee_wei+=1;auth.total_spend_cap_wei+=1
            auth.snapshot={**auth.snapshot,'fee_cap_wei':auth.max_fee_wei,'total_cap_wei':auth.total_spend_cap_wei}
            await db.commit()
        response=await lab.signer_client.post(f'/tasks/{event["task_id"]}/prepare')
        assert response.status_code==409
        async with lab.factory() as db:assert not (await db.get(MintTask,event['task_id'])).signed_tx_raw
    finally:lab.w.provider.make_request('evm_setAutomine',[True])


async def test_same_signed_source_nonce_cannot_authorize_another_copy_after_stage_change(copying):
    import uuid
    c=copying;lab=c['lab'];c['request']['fee_cap_eth']='0.0004';await c['approve']()
    try:
        observation,signed=await pending(c)
        first=await arm(c,observation);await lab.sign(first['task_id'])
        lab.w.provider.make_request('hardhat_dropTransaction',[observation['source_hash']])
        lab.w.provider.make_request('evm_setAutomine',[True])
        opening=lab.w.eth.get_block('latest').timestamp+1
        lab.w.provider.make_request('evm_setNextBlockTimestamp',[opening])
        lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
        lab.w.eth.wait_for_transaction_receipt(lab.sea.functions.updatePublicDrop(
            (10,opening,lab.end,20,500,True)).transact({'from':lab.nft.address}))
        lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
        lab.w.provider.make_request('evm_setAutomine',[False])
        lab.w.eth.send_raw_transaction(signed.raw_transaction)
        w=await automatic.provider()
        try:second=await pending_copy.observe(w,31337,observation['source_hash'],c['source'].address,lab.nft.address)
        finally:await w.provider.disconnect()
        async with lab.factory() as db:
            # Simulate an API DB attacker assigning another event ID to the
            # same authentic source transaction under changed on-chain terms.
            event=CopyEvent(id=uuid.uuid4().hex,user_id=lab.user.id,watch_id=c['watch_id'],observation=second,status='detected')
            db.add(event);await db.commit()
            await copy_mints.process_copy_events(db,c['watch_id'],31337);await db.commit()
            assert event.task_id,event.note
            second_id=event.task_id
        response=await lab.signer_client.post(f'/tasks/{second_id}/prepare')
        assert response.status_code==409
        async with lab.factory() as db:assert not (await db.get(MintTask,second_id)).signed_tx_raw
        journal=CustodyVault().journal()
        assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0]==1
        journal.close()
    finally:lab.w.provider.make_request('evm_setAutomine',[True])


async def test_pending_transaction_sender_and_hash_are_cryptographically_verified(copying,monkeypatch):
    c=copying;lab=c['lab'];await c['approve']()
    try:
        observation,_=await pending(c)
        tx=dict(lab.w.eth.get_transaction(observation['source_hash']))
        assert pending_copy.signed_identity(tx,31337)==c['source'].address
        with pytest.raises(ValueError):pending_copy.signed_identity({**tx,'from':lab.owner.address},31337)
        with pytest.raises(ValueError):pending_copy.signed_identity({**tx,'value':21},31337)
        with pytest.raises(ValueError):pending_copy.signed_identity(tx,1)
    finally:lab.w.provider.make_request('evm_setAutomine',[True])


@pytest.mark.parametrize('kind',[0,1,2,4])
def test_pending_signature_reconstruction_supports_legacy_access_list_dynamic_fee_and_delegation_envelopes(kind):
    account=Account.create()
    tx={'nonce':0,'gas':100000,'to':'0x'+'11'*20,'value':0,'data':'0x1234','chainId':31337}
    if kind:
        tx.update(type=kind,accessList=[])
    if kind in (0,1):tx['gasPrice']=10**9
    else:tx.update(maxFeePerGas=2*10**9,maxPriorityFeePerGas=10**9)
    if kind==4:
        auth=account.sign_authorization({'chainId':31337,'address':'0x'+'22'*20,'nonce':1})
        tx['authorizationList']=[auth]
    signed=account.sign_transaction(tx)
    observed={**tx,'type':kind,'from':account.address,'hash':signed.hash,'v':signed.v,
        'r':HexBytes(signed.r.to_bytes(32,'big')),'s':HexBytes(signed.s.to_bytes(32,'big'))}
    assert pending_copy.signed_identity(observed,31337)==account.address


async def test_old_confirmed_source_cannot_be_relabelled_pending_to_bypass_approval(copying):
    c=copying;lab=c['lab']
    old_hash=await c['mint']()
    w=await automatic.provider()
    try:old=await copy_mints.observe(w,31337,old_hash,c['source'].address,lab.nft.address)
    finally:await w.provider.disconnect()
    await c['approve']();await c['mint'](1);await c['scan']()
    event=(await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['task_id']
    async with lab.factory() as db:
        task=await db.get(MintTask,event['task_id']);auth=await db.get(MintAuthorization,task.authorization_id)
        old={**old,'source_pending':True,'source_nonce':lab.w.eth.get_transaction(old_hash).nonce,
            'seen_block':lab.w.eth.block_number,'seen_at':int(datetime.now(timezone.utc).timestamp())}
        auth.snapshot={**auth.snapshot,'copy_source':old}
        await db.commit()
    response=await lab.signer_client.post(f'/tasks/{event["task_id"]}/prepare')
    assert response.status_code==409
    async with lab.factory() as db:assert not (await db.get(MintTask,event['task_id'])).signed_tx_raw


async def test_live_discovery_does_not_wait_for_a_broken_historical_cursor(copying):
    c=copying;lab=c['lab'];await c['approve']();await c['mint'](1)
    async with lab.factory() as db:
        from app.models import CopyWatch
        watch=await db.get(CopyWatch,c['watch_id'])
        watch.cursors={'31337':{'block':1,'status':'unavailable'}}
        await db.commit()
    state={}
    ids=await fast_copy.live_step(lab.factory,31337,state)
    assert ids==[c['watch_id']]
    overview=(await lab.client.get('/api/copy-mints')).json()['watches'][0]['cursors']['31337']
    assert overview['status']=='monitoring' and overview['history_status']=='unavailable'
    async with lab.factory() as db:
        await copy_mints.process_copy_events(db,c['watch_id'],31337);await db.commit()
    events=(await lab.client.get('/api/copy-mints/activity')).json()['events']
    assert len(events)==1 and events[0]['task_id']
    await c['scan']()
    async with lab.factory() as db:
        from app.models import CopyWatch
        cursor=(await db.get(CopyWatch,c['watch_id'])).cursors['31337']
        assert cursor['live_block'] and cursor['live_hash']
    assert len((await lab.client.get('/api/copy-mints/activity')).json()['events'])==1


@pytest.mark.parametrize('wrong_chain',[False,True])
async def test_pending_stream_validates_network_filters_unrelated_wallets_and_bounds_duplicate_queue(monkeypatch,wrong_chain):
    from app.services.signer.base import MINT_PUBLIC_SELECTOR,SEADROP_V1_ADDRESS
    sender='0x'+'11'*20;contract='0x'+'22'*20
    data='0x'+MINT_PUBLIC_SELECTOR+encode(['address','address','address','uint256'],
        [contract,'0x'+'33'*20,sender,1]).hex()
    tx={'from':sender,'to':SEADROP_V1_ADDRESS,'input':data,'hash':'0x'+'44'*32,'blockHash':None}
    messages=[{'result':'0x1' if wrong_chain else hex(31337)},{'result':'subscription'},
        {'params':{'subscription':'subscription','result':{**tx,'from':'0x'+'55'*20}}},
        {'params':{'subscription':'subscription','result':tx}},
        {'params':{'subscription':'subscription','result':tx}},
        {'params':{'subscription':'subscription','result':{**tx,'hash':'0x'+'66'*32}}}]
    class WS:
        closed=False
        send_json=AsyncMock()
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def receive_json(self,**kwargs):
            if messages:return messages.pop(0)
            raise asyncio.CancelledError()
    ws=WS()
    class Session:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def ws_connect(self,*args,**kwargs):return ws
    monkeypatch.setattr(fast_copy.aiohttp,'ClientSession',Session)
    queue=asyncio.Queue(maxsize=1)
    with pytest.raises(ValueError if wrong_chain else asyncio.CancelledError):
        await fast_copy.stream('wss://example.invalid',31337,
            {'watches':[{'address':sender,'active':True}]},queue)
    if wrong_chain:
        assert queue.empty() and ws.send_json.await_count==1
    else:
        assert queue.qsize()==1
        assert (await queue.get())[1]==tx['hash']
        assert ws.send_json.await_args.args[0]['method']=='eth_unsubscribe'


async def test_expired_opensea_consent_has_actionable_message_without_renewing_or_claiming_ineligibility(lab,monkeypatch):
    from app.services.mint_stage_choice import wallet_stages
    from app.services.opensea_identity import TERMS_VERSION
    from app.services.opensea import CHAINS
    monkeypatch.setitem(CHAINS,'local',(31337,'Local test'))
    detail={'chain':'local','contract_address':lab.nft.address,'stages':[
        {'uuid':'public','label':'Public','stage_type':'public_sale',
         'start_time':datetime.fromtimestamp(lab.start,timezone.utc).isoformat(),
         'end_time':datetime.fromtimestamp(lab.end,timezone.utc).isoformat(),'price':'10','max_per_wallet':'20',
         'price_currency_address':'0x'+'0'*40}]}
    broker=AsyncMock(side_effect=AssertionError('Expired consent must not authenticate'))
    monkeypatch.setattr('app.api.opensea_access.broker',broker)
    expired=datetime.now(timezone.utc)-timedelta(days=1)
    async with lab.factory() as db:
        db.add(OpenSeaAccess(wallet_id=lab.wallet.id,user_id=lab.user.id,revision=1,enabled=True,
            expires_at=expired,terms_version=TERMS_VERSION,consented_at=expired-timedelta(days=7),status='active'))
        await db.commit()
        wallet=await db.get(Wallet,lab.wallet.id)
        result,_=await wallet_stages(db,wallet,'test',31337,lab.nft.address,read_only=True,detail=detail)
        assert not result['access_enabled'] and 'expired' in result['note'] and 'reconnect' in result['note']
        assert 'does not mean you are ineligible' in result['note']
        assert result['stages'][0]['eligibility']=='eligible'
        assert (await db.get(OpenSeaAccess,lab.wallet.id)).revision==1
        broker.assert_not_awaited()
