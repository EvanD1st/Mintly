import copy,uuid
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import select,func
from app.models import SourcePost,Drop,MintStage,FeedWalletCheck,FeedMintApproval,MintTask,MintAuthorization,User,Wallet
from app.services import automatic,feed_automation
from app.services.custody import CustodyVault
from test_automatic_evm import lab
from test_phase_tracking_evm import detail,update


@pytest.fixture
async def free_feed(lab,monkeypatch):
    update(lab,lab.start,lab.end,price=0)
    metadata=detail(lab,price=0)
    metadata.update(collection_name='Free daily collection',collection_slug='local-test',opensea_url=lab.drop.mint_page_url,drop_type='seadrop_v1_erc721')
    provider=AsyncMock(return_value=metadata)
    monkeypatch.setattr('app.services.opensea.OpenSeaClient.get_drop',provider)
    monkeypatch.setattr('app.services.mint_plans.eth_usdt_quote',AsyncMock(return_value=None))
    monkeypatch.setattr('app.services.feed_checks.supported',lambda _:True)
    monkeypatch.setattr('app.api.drops.supported',lambda _:True)
    async def broker(key,operation='register'):
        result=await lab.signer_client.post(f'/feed-approvals/{key}/{operation}')
        result.raise_for_status();return result.json()
    monkeypatch.setattr(feed_automation,'broker',broker)
    now=datetime.now(timezone.utc)
    async with lab.factory() as db:
        post=SourcePost(post_id=str(uuid.uuid4()),author_username='lakzonevn',full_text='Daily mint drops',posted_at=now,
            list_date=now.astimezone(ZoneInfo('Africa/Lagos')).date(),parser_version=1)
        db.add(post);await db.flush()
        drop=await db.get(Drop,lab.drop.id);drop.source_post_id=post.id
        wallet=await db.get(Wallet,lab.wallet.id);wallet.supported_chains=['Local test']
        stage=await db.get(MintStage,lab.stage.id);stage.price_wei=0;stage.price_eth_str='0'
        db.add(FeedWalletCheck(user_id=lab.user.id,wallet_id=lab.wallet.id,drop_id=drop.id,status='complete',checked_at=now,
            expires_at=now+timedelta(seconds=60),attempts=0,result={'contract_address':lab.nft.address,'stages':[{
                'id':'public','name':'Public','type':'public_sale','eligibility':'eligible','remaining':20,'wallet_total_limit':20,
                'price_wei':'0','starts_at':datetime.fromtimestamp(lab.start,timezone.utc).isoformat(),
                'ends_at':datetime.fromtimestamp(lab.end,timezone.utc).isoformat(),'timing':'upcoming'}]}))
        await db.commit()
        post_id=post.id
    req={'request_id':str(uuid.uuid4()),'grant_id':lab.grant.id,'quantity':2,'fee_cap':'0.0005','native_symbol':'ETH',
        'expires_at':datetime.fromtimestamp(lab.end,timezone.utc).isoformat(),'consent':True}
    response=await lab.client.post('/api/automatic/free-drops',json=req)
    assert response.status_code==200,response.text
    return {'lab':lab,'approval':response.json(),'request':req,'post':post_id,'metadata':provider}


async def test_daily_list_to_armed_free_task_with_real_independent_approval(free_feed):
    f=free_feed;lab=f['lab']
    # Exercise materialization directly so unexpected preparation failures surface.
    from app.services.feed_sources import daily_collections
    async with lab.factory() as db:
        row=await db.get(FeedMintApproval,f['approval']['id'])
        user=await db.get(User,lab.user.id);wallet=await db.get(Wallet,lab.wallet.id)
        groups=await daily_collections(db,datetime.now(timezone.utc).astimezone(ZoneInfo('Africa/Lagos')).date(),user.id)
        check=await db.get(FeedWalletCheck,(user.id,wallet.id,lab.drop.id))
        phase=await feed_automation.arm(db,row,groups[0],check,user,wallet)
        assert phase and phase['id']=='public'
        task=(await db.scalars(select(MintTask))).one()
        auth=await db.get(MintAuthorization,task.authorization_id)
        assert task.status=='armed' and auth.snapshot['feed_approval_id']==row.id
        assert auth.snapshot['price_wei']==auth.snapshot['price_cap_wei']==0 and auth.quantity==2
        assert auth.snapshot['schedule_mode']=='phase_open'
        assert 'standing free-list approval' in auth.user_consent_text
    await feed_automation.step(lab.factory)
    async with lab.factory() as db:
        assert await db.scalar(select(func.count()).select_from(MintTask))==1


async def arm_free(f):
    lab=f['lab']
    source={'drop_id':lab.drop.id,'post_id':f['post'],'list_date':datetime.now(timezone.utc).astimezone(ZoneInfo('Africa/Lagos')).date().isoformat()}
    request={**lab.request,'price_cap_eth':'0','total_cap_eth':'0.0005','schedule_mode':'phase_open',
        'feed_approval_id':f['approval']['id'],'feed_source':source}
    response=await lab.client.post('/api/tasks/arm',json=request)
    assert response.status_code==200,response.text
    return response.json()['id'],request


async def test_free_standing_task_mints_once_and_blocks_a_second_copy_or_plan(free_feed,monkeypatch):
    f=free_feed;lab=f['lab'];task_id,request=await arm_free(f)
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromtimestamp(lab.w.eth.get_block('latest').timestamp,tz)
    monkeypatch.setattr('app.services.automatic_signer.datetime',Clock)
    first=await lab.sign(task_id);assert (await lab.sign(task_id))['hash']==first['hash']
    await lab.due();await lab.tick()
    for _ in range(4):lab.w.provider.make_request('evm_mine',[])
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert task.status=='confirmed',task.failure_reason
    assert lab.nft.functions.totalSupply().call()==2
    response=await lab.client.post('/api/tasks/arm',json={**request,'idempotency_key':'different-duplicate'})
    assert response.status_code==409 and 'already' in response.text


async def test_turning_off_cancels_unsigned_tasks_and_does_not_reset_spending(free_feed):
    f=free_feed;lab=f['lab'];task_id,_=await arm_free(f)
    response=await lab.client.delete('/api/automatic/free-drops/'+f['approval']['id'])
    assert response.status_code==200,response.text
    async with lab.factory() as db:
        assert (await db.get(MintTask,task_id)).status=='disarmed'
        assert (await db.get(FeedMintApproval,f['approval']['id'])).status=='revoked'
    journal=CustodyVault().journal()
    assert journal.execute('SELECT revoked FROM feed_approvals WHERE id=?',(f['approval']['id'],)).fetchone()[0]==1
    journal.close()


async def test_turning_off_after_signing_preserves_bytes_nonce_and_reserved_funds(free_feed,monkeypatch):
    from app.models import AutomaticGrant
    f=free_feed;lab=f['lab'];task_id,_=await arm_free(f)
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromtimestamp(lab.w.eth.get_block('latest').timestamp,tz)
    monkeypatch.setattr('app.services.automatic_signer.datetime',Clock)
    await lab.sign(task_id)
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        original=(task.signed_tx_raw,task.transaction_hash,task.assigned_nonce)
        reserved=(await db.get(AutomaticGrant,lab.grant.id)).reserved_wei
        assert reserved>0
    response=await lab.client.delete('/api/automatic/free-drops/'+f['approval']['id'])
    assert response.status_code==200,response.text
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert task.status=='uncertain' and task.broadcast_disabled_at
        assert (task.signed_tx_raw,task.transaction_hash,task.assigned_nonce)==original
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==reserved
    await lab.due();await lab.tick()
    assert lab.nft.functions.totalSupply().call()==0


@pytest.mark.parametrize('field,value',[('eligibility','unverified'),('eligibility','not_eligible'),('price_wei','1'),('remaining',None)])
async def test_no_automatic_arm_for_paid_or_unverified_phase(free_feed,field,value):
    from app.services.feed_sources import daily_collections
    f=free_feed;lab=f['lab']
    async with lab.factory() as db:
        row=await db.get(FeedMintApproval,f['approval']['id'])
        user=await db.get(User,lab.user.id);wallet=await db.get(Wallet,lab.wallet.id)
        groups=await daily_collections(db,datetime.now(ZoneInfo('Africa/Lagos')).date(),user.id)
        check=await db.get(FeedWalletCheck,(user.id,wallet.id,lab.drop.id))
        result=copy.deepcopy(check.result);result['stages'][0][field]=value;check.result=result
        assert await feed_automation.arm(db,row,groups[0],check,user,wallet) is None
        assert await db.scalar(select(func.count()).select_from(MintTask))==0


async def test_private_signer_rejects_daily_source_claim_for_another_collection(free_feed):
    f=free_feed;lab=f['lab'];task_id,_=await arm_free(f)
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);auth=await db.get(MintAuthorization,task.authorization_id)
        forged={**auth.snapshot,'contract':'0x'+'1'*40}
        journal=CustodyVault().journal()
        try:
            with pytest.raises(ValueError,match='approved daily list'):
                await feed_automation.verify_task(db,journal,task,forged,lab.grant)
        finally:journal.close()

from test_copy_presales import presale
from test_copy_mints import copying


@pytest.mark.parametrize('kind',['allowlist','signed'])
async def test_free_wl_and_fcfs_use_receiving_wallet_proof_and_confirm(presale,free_feed,monkeypatch,kind):
    from app.models import OpenSeaAccess
    from app.services.feed_sources import daily_collections
    c,state,configure,_=presale
    f=free_feed;lab=f['lab']
    state.kind=kind;state.own_price=0;state.own_index=8;configure()
    metadata=copy.deepcopy(f['metadata'].return_value)
    metadata['collection_slug']='presale-copy'
    metadata['opensea_url']='https://opensea.io/collection/presale-copy'
    metadata['stages'][0].update(uuid='free-wl',stage_type='allowlist' if kind=='allowlist' else 'signed_presale',label='Free WL / FCFS',max_per_wallet='7')
    f['metadata'].return_value=metadata
    monkeypatch.setattr('app.services.opensea.OpenSeaClient._key',AsyncMock(return_value='disposable-test-key'))
    monkeypatch.setattr('app.api.opensea_access.broker',AsyncMock(return_value={'address':lab.owner.address,'stages':[{
        'stage_uuid':'free-wl','eligible':True,'remaining':7,'max_total_mintable_by_wallet':7,'price_wei':0}]}))
    async with lab.factory() as db:
        drop=await db.get(Drop,lab.drop.id);drop.mint_page_url=metadata['opensea_url']
        check=await db.get(FeedWalletCheck,(lab.user.id,lab.wallet.id,lab.drop.id))
        result=copy.deepcopy(check.result)
        result['stages'][0].update(id='free-wl',type='allowlist' if kind=='allowlist' else 'signed_presale',name='Free WL / FCFS',remaining=7,wallet_total_limit=7)
        check.result=result
        now=datetime.now(timezone.utc)
        db.add(OpenSeaAccess(wallet_id=lab.wallet.id,user_id=lab.user.id,enabled=True,status='active',
            expires_at=now+timedelta(hours=1),terms_version='test',consented_at=now))
        await db.commit()
        row=await db.get(FeedMintApproval,f['approval']['id']);user=await db.get(User,lab.user.id);wallet=await db.get(Wallet,lab.wallet.id)
        groups=await daily_collections(db,now.astimezone(ZoneInfo('Africa/Lagos')).date(),user.id)
        phase=await feed_automation.arm(db,row,groups[0],check,user,wallet)
        assert phase and phase['id']=='free-wl'
        task=(await db.scalars(select(MintTask))).one();task_id=task.id
        auth=await db.get(MintAuthorization,task.authorization_id)
        assert auth.snapshot['mint_kind']==kind
        original=copy.deepcopy(auth.snapshot)
    # The project delays this same restricted phase after it was armed.
    state.own_start=lab.start+30;configure()
    metadata=copy.deepcopy(metadata)
    metadata['stages'][0]['start_time']=datetime.fromtimestamp(state.own_start,timezone.utc).isoformat()
    f['metadata'].return_value=metadata
    refreshed=await lab.signer_client.post(f'/tasks/{task_id}/refresh-schedule')
    assert refreshed.status_code==200,refreshed.text
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert (await db.get(MintAuthorization,task.authorization_id)).snapshot==original
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[state.own_start]);lab.w.provider.make_request('evm_mine',[])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromtimestamp(lab.w.eth.get_block('latest').timestamp,tz)
    monkeypatch.setattr('app.services.automatic_signer.datetime',Clock)
    await lab.sign(task_id)
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        receipt=lab.w.eth.wait_for_transaction_receipt(lab.w.eth.send_raw_transaction(task.signed_tx_raw))
        assert receipt.status==1
    assert lab.nft.functions.totalSupply().call()==2


async def test_reservation_shortage_waits_then_arms_without_increasing_budget(free_feed):
    from app.models import AutomaticGrant
    from app.services.feed_sources import daily_collections
    f=free_feed;lab=f['lab']
    async with lab.factory() as db:
        row=await db.get(FeedMintApproval,f['approval']['id'])
        user=await db.get(User,lab.user.id);wallet=await db.get(Wallet,lab.wallet.id)
        grant=await db.get(AutomaticGrant,lab.grant.id)
        budget=grant.budget_wei;grant.reserved_wei=budget
        groups=await daily_collections(db,datetime.now(ZoneInfo('Africa/Lagos')).date(),user.id)
        check=await db.get(FeedWalletCheck,(user.id,wallet.id,lab.drop.id))
        assert await feed_automation.arm(db,row,groups[0],check,user,wallet) is None
        assert 'reservations' in row.note
        assert await db.scalar(select(func.count()).select_from(MintTask))==0
        grant.reserved_wei=0;await db.commit()
        assert await feed_automation.arm(db,row,groups[0],check,user,wallet)
        assert grant.budget_wei==budget


async def test_other_user_cannot_read_or_disable_standing_approval(free_feed):
    f=free_feed;lab=f['lab']
    login=await lab.client.post('/api/auth/login',json={'username':'admin','password':'Admin test password 123'})
    headers={'Authorization':'Bearer '+login.json()['token']}
    response=await lab.client.get('/api/automatic/free-drops',headers=headers)
    assert response.status_code==200 and response.json()['approvals']==[]
    response=await lab.client.delete('/api/automatic/free-drops/'+f['approval']['id'],headers=headers)
    assert response.status_code==404
    async with lab.factory() as db:
        assert (await db.get(FeedMintApproval,f['approval']['id'])).status=='active'

async def test_inflight_list_keeps_original_wat_day_during_preparation(free_feed):
    from app.services.feed_sources import daily_collections
    f=free_feed;lab=f['lab']
    day=datetime.now(ZoneInfo('Africa/Lagos')).date()-timedelta(days=1)
    async with lab.factory() as db:
        post=await db.get(SourcePost,f['post']);post.list_date=day
        row=await db.get(FeedMintApproval,f['approval']['id']);row.created_at=datetime.now(timezone.utc)-timedelta(days=1)
        await db.commit()
        user=await db.get(User,lab.user.id);wallet=await db.get(Wallet,lab.wallet.id)
        groups=await daily_collections(db,day,user.id);groups[0]['list_date']=day
        check=await db.get(FeedWalletCheck,(user.id,wallet.id,lab.drop.id))
        assert await feed_automation.arm(db,row,groups[0],check,user,wallet)
        task=(await db.scalars(select(MintTask))).one();auth=await db.get(MintAuthorization,task.authorization_id)
        assert auth.snapshot['feed_source']['list_date']==day.isoformat()
        journal=CustodyVault().journal()
        try:await feed_automation.verify_task(db,journal,task,auth.snapshot,lab.grant)
        finally:journal.close()
