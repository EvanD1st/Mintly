"""Real isolated EVM and owned-session regressions for all four controls."""
import asyncio
from datetime import datetime, timezone, timedelta
import json
import uuid
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models import User, Wallet, MintTask, MintAuthorization, AutomaticGrant, DailyDebit, CopyRule, CopyCheck, CopyCheckResult, WalletAlert, ActivityEvent, CopyEvent
from app.models.activity import NotificationDevice
from app.services import automatic, daily_budget, copy_mints, wallet_alerts
from app.services.custody import CustodyVault
from app.services.mint_progress import progress
from test_automatic_evm import lab
from test_copy_mints import copying


@pytest.fixture
async def limits(lab,monkeypatch):
    async def signer(user_id,operation):
        method=lab.signer_client.post if operation=='register' else lab.signer_client.get
        result=await method(f'/account-limits/{user_id}/{operation}')
        result.raise_for_status()
        return result.json()
    monkeypatch.setattr('app.api.automatic.signer_limit',signer)
    async def set_limit(amount):
        result=await lab.client.post('/api/automatic/daily-limit',json={'limit_eth':amount,'consent':True})
        assert result.status_code==200,result.text
        return result.json()
    return set_limit


def chain_open(lab):
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start])
    lab.w.provider.make_request('evm_mine',[])


async def add_wallet(lab):
    from eth_account import Account
    from app.services.custody import private_read,private_write
    owner=Account.create()
    lab.w.provider.make_request('hardhat_setBalance',[owner.address,hex(10**18)])
    wallet=Wallet(id=str(uuid.uuid4()),user_id=lab.user.id,address=owner.address,label='Second receiving wallet',signing_capability='custodial',is_demo=False)
    gid,key_id=str(uuid.uuid4()),str(uuid.uuid4())
    policy=json.loads(private_read(lab.tmp/f'{lab.grant.id}.policy.json'))
    policy.update(grant_id=gid,key_id=key_id,wallet_id=wallet.id,account=owner.address)
    private_write(lab.tmp/f'{key_id}.keystore.json',json.dumps(Account.encrypt(owner.key,private_read(lab.tmp/'password'),kdf='scrypt',iterations=1024)))
    private_write(lab.tmp/f'{gid}.policy.json',json.dumps(policy))
    grant=AutomaticGrant(id=gid,user_id=lab.user.id,wallet_id=wallet.id,chain_id=31337,account=owner.address,
        context_hash=automatic.digest(policy),scope=lab.grant.scope,expires_at=lab.grant.expires_at,
        status='enabled',budget_wei=lab.grant.budget_wei,reserved_wei=0,spent_wei=0)
    async with lab.factory() as db:
        db.add(wallet);await db.flush();db.add(grant);await db.commit()
    return owner,wallet,grant


async def test_daily_cap_reserves_both_bots_and_does_not_reset_on_updates(copying,limits):
    c=copying;lab=c['lab']
    await limits('0.0006')
    armed=await lab.client.post('/api/tasks/arm',json=lab.request)
    assert armed.status_code==200
    _,_,receiver=await add_wallet(lab)
    c['request']['grant_id']=receiver.id
    await c['approve']();await c['mint']();await c['scan']()
    async with lab.factory() as db:
        assert len((await db.scalars(select(MintTask))).all())==1
        event=(await db.scalars(select(CopyEvent))).one()
        assert event.status=='skipped' and 'Daily spending limit' in event.note
    before=(await lab.client.get('/api/automatic/daily-limit')).json()
    after=await limits('0.0007')
    assert after['reserved_wei']==before['reserved_wei'] and after['spent_wei']==before['spent_wei']
    assert (await lab.client.post('/api/tasks/arm',json={**lab.request,'idempotency_key':'second-within-same-day'})).status_code==429
    await lab.client.post('/api/tasks/'+armed.json()['id']+'/disarm')
    assert (await lab.client.get('/api/automatic/daily-limit')).json()['reserved_wei']=='0'


async def test_daily_limit_other_account_cannot_change_or_read_it(lab,limits):
    await limits('0.0006')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as other:
        login=await other.post('/api/auth/login',json={'username':'admin','password':'Admin test password 123'})
        other.headers['Authorization']='Bearer '+login.json()['token']
        assert (await other.get('/api/automatic/daily-limit')).json()['limit_wei'] is None
        assert (await other.post('/api/automatic/daily-limit',json={'limit_eth':'0.5','consent':False})).status_code==422
    assert (await lab.client.get('/api/automatic/daily-limit')).json()['limit_wei']==str(600000000000000)


@pytest.mark.parametrize('tamper',['limit','revision','remove_pin_reference'])
async def test_independent_daily_pin_rejects_database_relaxation(lab,limits,tamper):
    await limits('0.0006')
    tid=(await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    async with lab.factory() as db:
        user=await db.get(User,lab.user.id)
        if tamper=='limit':user.daily_limit_wei=10**18
        elif tamper=='revision':user.daily_limit_revision+=1
        else:user.daily_limit_wei,user.daily_limit_revision=None,0
        await db.commit()
    chain_open(lab)
    result=await lab.signer_client.post(f'/tasks/{tid}/prepare')
    assert result.status_code==409
    async with lab.factory() as db:
        assert (await db.get(MintTask,tid)).signed_tx_raw is None
    assert lab.nft.functions.totalSupply().call()==0


async def test_private_daily_cap_survives_deleted_api_reservations_and_restart(lab,limits,monkeypatch):
    await limits('0.0006')
    first=(await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    chain_open(lab);await lab.sign(first)
    async with lab.factory() as db:
        await db.delete(await db.get(DailyDebit,first))
        await db.commit()
    second=await lab.client.post('/api/tasks/arm',json={**lab.request,'idempotency_key':'deleted-reservation-bypass'})
    assert second.status_code==200
    from app.services import automatic_signer
    automatic_signer._preflights.clear();automatic_signer._reconciled.clear()
    blocked=await lab.signer_client.post(f'/tasks/{second.json()["id"]}/prepare')
    assert blocked.status_code==429,blocked.text
    journal=CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0]==1
    assert journal.execute('SELECT COUNT(*) FROM daily_signed').fetchone()[0]==1
    journal.close()


async def test_daily_cap_is_shared_between_different_real_wallet_keys(lab,limits):
    from eth_account import Account
    from app.services.custody import private_read,private_write
    await limits('0.0006')
    first=(await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    chain_open(lab);await lab.sign(first)
    owner=Account.create()
    lab.w.provider.make_request('hardhat_setBalance',[owner.address,hex(10**18)])
    wallet=Wallet(id=str(uuid.uuid4()),user_id=lab.user.id,address=owner.address,label='Second receiving wallet',signing_capability='custodial',is_demo=False)
    gid,key_id=str(uuid.uuid4()),str(uuid.uuid4())
    policy=json.loads(private_read(lab.tmp/f'{lab.grant.id}.policy.json'))
    policy.update(grant_id=gid,key_id=key_id,wallet_id=wallet.id,account=owner.address)
    private_write(lab.tmp/f'{key_id}.keystore.json',json.dumps(Account.encrypt(owner.key,private_read(lab.tmp/'password'),kdf='scrypt',iterations=1024)))
    private_write(lab.tmp/f'{gid}.policy.json',json.dumps(policy))
    grant=AutomaticGrant(id=gid,user_id=lab.user.id,wallet_id=wallet.id,chain_id=31337,account=owner.address,
        context_hash=automatic.digest(policy),scope=lab.grant.scope,expires_at=lab.grant.expires_at,
        status='enabled',budget_wei=lab.grant.budget_wei,reserved_wei=0,spent_wei=0)
    async with lab.factory() as db:
        db.add(wallet);await db.flush();db.add(grant)
        await db.delete(await db.get(DailyDebit,first))
        await db.commit()
    second=await lab.client.post('/api/tasks/arm',json={**lab.request,'wallet_id':wallet.id,'grant_id':gid,'idempotency_key':'second-real-key'})
    assert second.status_code==200,second.text
    assert (await lab.signer_client.post(f'/tasks/{second.json()["id"]}/prepare')).status_code==429
    assert lab.w.eth.get_transaction_count(owner.address)==0


def test_private_daily_usage_sums_networks_and_carries_uncertain_costs(tmp_path):
    import sqlite3
    journal=sqlite3.connect(tmp_path/'disposable-budget.sqlite');journal.row_factory=sqlite3.Row
    journal.execute('CREATE TABLE signed(task TEXT,actual INTEGER,liability INTEGER,chain INTEGER)')
    journal.execute('CREATE TABLE daily_signed(task TEXT,user_id TEXT,day TEXT)')
    for tid,uid,chain,day,actual,maximum in [('eth','member',1,'2026-10-09',100,200),
            ('base','member',8453,'2026-10-08',None,300),('rh','member',4663,'2026-10-09',50,100),
            ('old','member',1,'2026-10-08',500,600),('foreign','admin',1,'2026-10-09',None,999)]:
        journal.execute('INSERT INTO signed VALUES(?,?,?,?)',(tid,actual,maximum,chain))
        journal.execute('INSERT INTO daily_signed VALUES(?,?,?)',(tid,uid,day))
    assert daily_budget.private_usage(journal,'member','2026-10-09')=={'spent_wei':150,'reserved_wei':300}
    journal.close()


async def test_daily_journal_commit_loss_cannot_create_a_second_liability(lab,limits,monkeypatch):
    from app.services.automatic_signer import prepare_task
    await limits('0.0006')
    tid=(await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    chain_open(lab)
    async with lab.factory() as db:
        async def lost_commit():raise RuntimeError('Database commit lost after journal fsync')
        monkeypatch.setattr(db,'commit',lost_commit)
        with pytest.raises(RuntimeError):await prepare_task(db,tid)
        await db.rollback()
    recovered=await lab.sign(tid)
    assert recovered['status']=='prepared'
    journal=CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM daily_signed').fetchone()[0]==1
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0]==1
    journal.close()


@pytest.mark.parametrize('settled',[False,True])
async def test_preupgrade_signatures_are_backfilled_without_resetting_costs(lab,limits,settled):
    tid=(await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    chain_open(lab);await lab.sign(tid)
    if settled:
        await lab.due();await lab.tick();lab.w.provider.make_request('evm_mine',[])
        await lab.due();await lab.tick()
    journal=CustodyVault().journal()
    journal.execute('DELETE FROM daily_signed');journal.commit();journal.close()
    result=await limits('0.0006')
    assert int(result['spent_wei'])>0 if settled else int(result['reserved_wei'])==500000000000020
    journal=CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM daily_signed').fetchone()[0]==1
    journal.close()


async def test_resolved_daily_signature_charges_actual_once_and_releases_unused_cap(lab,limits):
    await limits('0.0006')
    tid=(await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    chain_open(lab);await lab.sign(tid);await lab.due();await lab.tick()
    lab.w.provider.make_request('evm_mine',[]);await lab.due();await lab.tick()
    first=(await lab.client.get('/api/automatic/daily-limit')).json()
    second=(await lab.client.get('/api/automatic/daily-limit')).json()
    assert first['spent_wei']==second['spent_wei'] and first['reserved_wei']=='0'
    assert 0<int(first['spent_wei'])<600000000000000
    async with lab.factory() as db:
        task=await db.get(MintTask,tid)
        assert task.included_at and (await db.get(DailyDebit,tid)).actual_wei==task.actual_total_cost_wei


async def test_pending_limit_registration_blocks_signing_and_can_retry_same_revision(lab,limits,monkeypatch):
    tid=(await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    async def unavailable(*args):raise RuntimeError('Signer response unavailable')
    with monkeypatch.context() as scope:
        scope.setattr('app.api.automatic.signer_limit',unavailable)
        assert (await lab.client.post('/api/automatic/daily-limit',json={'limit_eth':'0.0006','consent':True})).status_code==503
    async with lab.factory() as db:
        revision=(await db.get(User,lab.user.id)).daily_limit_revision
    chain_open(lab)
    assert (await lab.signer_client.post(f'/tasks/{tid}/prepare')).status_code==503
    await limits('0.0006')
    async with lab.factory() as db:
        assert (await db.get(User,lab.user.id)).daily_limit_revision==revision
    assert (await lab.sign(tid))['status']=='prepared'


def test_wat_day_is_not_utc_day():
    assert daily_budget.day_key(datetime(2026,10,8,22,59,59,tzinfo=timezone.utc))=='2026-10-08'
    assert daily_budget.day_key(datetime(2026,10,8,23,0,0,tzinfo=timezone.utc))=='2026-10-09'


async def test_unresolved_signatures_carry_across_midnight_and_disabled_cap_keeps_history(lab,limits):
    await limits('0.0006')
    tid=(await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    chain_open(lab);await lab.sign(tid)
    journal=CustodyVault().journal()
    journal.execute('UPDATE daily_signed SET day=? WHERE task=?',('2026-10-01',tid));journal.commit()
    used=daily_budget.private_usage(journal,lab.user.id,'2026-10-09')
    assert used['reserved_wei']==500000000000020 and used['spent_wei']==0
    journal.close()
    before=(await lab.client.get('/api/automatic/daily-limit')).json()['reserved_wei']
    disabled=await limits(None)
    assert disabled['limit_wei'] is None and disabled['reserved_wei']==before


async def test_daily_budget_concurrent_arms_cannot_overbook(lab,limits):
    await limits('0.0006')
    results=await asyncio.gather(*[lab.client.post('/api/tasks/arm',json={**lab.request,'idempotency_key':f'daily-race-{i}'}) for i in range(3)])
    assert sorted(r.status_code for r in results)==[200,429,429]
    async with lab.factory() as db:
        assert await db.scalar(select(func.count()).select_from(DailyDebit))==1
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==500000000000020


@pytest.mark.parametrize('status,index,label',[
    ('armed',0,'Waiting for mint time'),('prepared',1,'Preparing'),('submitted',2,'Sent'),
    ('uncertain',2,'Checking transaction status'),('confirmed',4,'Confirmed'),('failed',0,'Preparation stopped')])
def test_progress_labels_follow_evidence(status,index,label):
    task=SimpleNamespace(status=status,included_at=None,inclusion_result=None,preparation_started_at=None,
        signed_tx_raw='saved' if status=='prepared' else None,broadcast_attempts=1 if status in ('submitted','uncertain') else 0,
        confirmed_at=None,failure_reason=None,transaction_hash=None)
    value=progress(task)
    assert value['label']==label and value['key']==('checking','preparing','sent','included','confirmed')[index]
    if status!='confirmed':assert value['steps'][-1]['state']=='pending'


@pytest.mark.parametrize('outcome',['success','reverted'])
def test_inclusion_is_not_confirmation(outcome):
    task=SimpleNamespace(status='submitted',included_at=datetime.now(timezone.utc),inclusion_result=outcome,
        preparation_started_at=None,signed_tx_raw='saved',broadcast_attempts=1,confirmed_at=None,failure_reason=None,transaction_hash=None)
    value=progress(task)
    assert 'waiting for confirmations' in value['label'] and value['steps'][-1]['state']=='pending'


async def test_real_receipt_progress_waits_for_confirmations_and_reorg_clears_inclusion(lab,monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings,'AUTOMATIC_CONFIRMATIONS',12)
    tid=(await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    chain_open(lab);await lab.sign(tid)
    checkpoint=lab.w.provider.make_request('evm_snapshot',[])['result']
    await lab.due();await lab.tick()
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,tid)
        assert task.included_at is not None and task.confirmed_at is None
        assert progress(task)['label']=='Included — waiting for confirmations'
    assert lab.w.provider.make_request('evm_revert',[checkpoint])['result']
    await lab.client.post('/api/automatic/pause',json={'paused':True})
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,tid)
        assert task.included_at is None and task.confirmed_at is None
        assert progress(task)['steps'][-1]['state']=='pending'


@pytest.fixture
async def checks(copying):
    c=copying;lab=c['lab']
    request={'request_id':str(uuid.uuid4()),'wallet_id':lab.wallet.id,'quantity':1,'quantity_mode':'fixed',
        'price_cap_eth':'0.00000000000000001','fee_cap_eth':'0.0005','budget_eth':'0.001',
        'free_only':False,'include_presales':False,'expires_at':datetime.fromtimestamp(lab.end,timezone.utc).isoformat()}
    async def enable():
        result=await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/checks',json=request)
        assert result.status_code==200,result.text
        return result.json()
    return c,request,enable


async def test_check_only_has_no_authorization_reservation_nonce_signature_or_spend(checks,monkeypatch):
    c,request,enable=checks;lab=c['lab']
    def forbidden(*args):pytest.fail('Check-only cannot decrypt a wallet key')
    monkeypatch.setattr(CustodyVault,'account',forbidden)
    await enable();await c['mint'](1);await c['scan']()
    results=(await lab.client.get('/api/copy-mints/check-results')).json()['results']
    assert len(results)==1 and results[0]['status']=='would_copy',results[0]['note'] if results else results
    assert results[0]['transaction_sent'] is False
    async with lab.factory() as db:
        assert await db.scalar(select(func.count()).select_from(MintTask))==0
        assert await db.scalar(select(func.count()).select_from(MintAuthorization))==0
        assert await db.scalar(select(func.count()).select_from(DailyDebit))==0
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==0
    journal=CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0]==0
    journal.close()
    assert lab.nft.functions.totalSupply().call()==1 and lab.w.eth.get_transaction_count(lab.owner.address)==0


async def test_entering_check_mode_pauses_existing_rules_and_unsigned_tasks(checks):
    c,request,enable=checks;lab=c['lab']
    await c['approve']();await c['mint'](1);await c['scan']()
    await enable()
    async with lab.factory() as db:
        assert (await db.get(CopyRule,c['request']['request_id'])).status=='paused'
        task=await db.scalar(select(MintTask))
        assert task.status=='disarmed' and task.signed_tx_raw is None
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==0
    assert (await lab.client.post('/api/copy-mints/pause',json={'paused':False})).status_code==409
    await lab.client.delete(f'/api/copy-mints/watches/{c["watch_id"]}/checks')
    async with lab.factory() as db:
        assert (await db.get(CopyRule,c['request']['request_id'])).status=='paused'


async def test_funding_retry_restores_the_same_daily_reservation(copying,limits,monkeypatch):
    c=copying;lab=c['lab']
    await limits('0.0006')
    await c['approve']();await c['mint'](1);await c['scan']()
    async with lab.factory() as db:
        event=await db.scalar(select(CopyEvent));tid=event.task_id;eid=event.id
    lab.w.provider.make_request('hardhat_setBalance',[lab.owner.address,'0x0'])
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        assert (await db.get(MintTask,tid)).status=='failed'
        assert (await db.get(DailyDebit,tid)).actual_wei==0
    lab.w.provider.make_request('hardhat_setBalance',[lab.owner.address,hex(10**18)])
    async def unsigned(task_id):
        result=await lab.signer_client.get(f'/tasks/{task_id}/unsigned')
        assert result.json()=={'unsigned':True}
    monkeypatch.setattr('app.api.copy_mints.confirm_unsigned',unsigned)
    retry=await lab.client.post('/api/copy-mints/events/'+eid+'/retry')
    assert retry.status_code==200,retry.text
    async with lab.factory() as db:
        row=await db.get(DailyDebit,tid)
        assert row.actual_wei is None and row.maximum_wei==500000000000010
        assert await db.scalar(select(func.count()).select_from(DailyDebit))==1


@pytest.mark.parametrize('reason',['price','gas','funding','stage_ended'])
async def test_check_only_explains_skips_without_creating_tasks(checks,reason):
    c,request,enable=checks;lab=c['lab']
    if reason=='price':request['price_cap_eth']='0'
    if reason=='gas':request['fee_cap_eth']='0.00000000000000001'
    await enable();await c['mint'](1)
    if reason=='funding':lab.w.provider.make_request('hardhat_setBalance',[lab.owner.address,'0x0'])
    if reason=='stage_ended':
        lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.end+1]);lab.w.provider.make_request('evm_mine',[])
    await c['scan']()
    results=(await lab.client.get('/api/copy-mints/check-results')).json()['results']
    assert results and results[0]['status']=='would_skip',results
    async with lab.factory() as db:assert await db.scalar(select(func.count()).select_from(MintTask))==0


async def test_check_config_and_results_are_owned_and_unlink_stops_checks(checks):
    c,request,enable=checks;lab=c['lab']
    await enable();await c['mint'](1);await c['scan']()
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as other:
        login=await other.post('/api/auth/login',json={'username':'admin','password':'Admin test password 123'})
        other.headers['Authorization']='Bearer '+login.json()['token']
        assert (await other.get('/api/copy-mints/check-results')).json()['results']==[]
        assert (await other.delete(f'/api/copy-mints/watches/{c["watch_id"]}/checks')).status_code==404
    await lab.client.delete('/api/wallets/'+lab.wallet.id)
    async with lab.factory() as db:assert not (await db.get(CopyCheck,c['watch_id'])).active
    assert len((await lab.client.get('/api/copy-mints/check-results')).json()['results'])==1


async def test_check_only_can_be_started_without_signing_policy(checks):
    c,request,enable=checks;lab=c['lab']
    async with lab.factory() as db:
        (await db.get(AutomaticGrant,lab.grant.id)).status='disabled'
        await db.commit()
    await enable();await c['mint'](1);await c['scan']()
    assert (await lab.client.get('/api/copy-mints/check-results')).json()['results'][0]['status']=='would_copy'


async def test_check_only_cannot_be_bypassed_by_manual_copy_review(checks):
    c,request,enable=checks;lab=c['lab']
    await enable();await c['mint'](1);await c['scan']()
    event=(await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    context=(await lab.client.get('/api/copy-mints/events/'+event['id']+'/context')).json()
    body={**lab.request,'copy_event_id':event['id'],'drop_id':context['drop']['id'],'stage_id':context['drop']['stages'][0]['id']}
    assert (await lab.client.post('/api/tasks/arm',json=body)).status_code==409
    async with lab.factory() as db:assert await db.scalar(select(func.count()).select_from(MintTask))==0


async def test_wallet_alerts_dedupe_recover_and_stay_on_owned_devices(lab,monkeypatch):
    tid=(await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    async with lab.factory() as db:
        db.add(NotificationDevice(user_id=lab.user.id,device_token='owner-alert-token-long-enough',platform='android',is_active=True,
            preferences={'wallet_alerts':True,'mint_status':True}))
        await db.commit()
    amount=0
    async def balance(*args):return amount
    delivered=[]
    async def notify(title,body,**kwargs):
        delivered.append((title,body,kwargs));return True
    await wallet_alerts.poll(lab.factory,balance);await wallet_alerts.deliver(lab.factory,notify)
    assert len(delivered)==2 and all(d[2]['user_id']==lab.user.id for d in delivered)
    await wallet_alerts.poll(lab.factory,balance);await wallet_alerts.deliver(lab.factory,notify)
    assert len(delivered)==2
    amount=10**18
    await wallet_alerts.poll(lab.factory,balance)
    amount=0
    await wallet_alerts.poll(lab.factory,balance);await wallet_alerts.deliver(lab.factory,notify)
    assert len(delivered)==3 and 'ETH' in delivered[-1][0]
    async def outage(*args):raise RuntimeError('RPC outage')
    await wallet_alerts.poll(lab.factory,outage);await wallet_alerts.deliver(lab.factory,notify)
    assert len(delivered)==3
    await lab.client.post('/api/tasks/'+tid+'/disarm')
    await wallet_alerts.poll(lab.factory,balance)
    async with lab.factory() as db:
        low=await db.scalar(select(WalletAlert).where(WalletAlert.kind=='low_funds'))
        assert not low.active and not low.pending


async def test_muted_alerts_and_removed_wallets_do_not_send(lab):
    await lab.client.post('/api/tasks/arm',json=lab.request)
    async with lab.factory() as db:
        db.add(NotificationDevice(user_id=lab.user.id,device_token='muted-alert-token-long-enough',platform='android',is_active=True,
            preferences={'mint_status':False}))
        await db.commit()
    async def balance(*args):return 0
    async def forbidden(*args,**kwargs):pytest.fail('Muted/removed owner cannot receive alerts')
    await wallet_alerts.poll(lab.factory,balance);await wallet_alerts.deliver(lab.factory,forbidden)
    await lab.client.delete('/api/wallets/'+lab.wallet.id)
    await wallet_alerts.poll(lab.factory,balance);await wallet_alerts.deliver(lab.factory,forbidden)
    async with lab.factory() as db:assert not any(a.pending for a in (await db.scalars(select(WalletAlert))).all())


async def test_renewed_approval_clears_expiry_alert_without_sending_stale_message(lab):
    async def balance(*args):return 10**18
    await wallet_alerts.poll(lab.factory,balance)
    async with lab.factory() as db:
        assert (await db.scalar(select(WalletAlert).where(WalletAlert.kind=='approval_expiry'))).active
        (await db.get(AutomaticGrant,lab.grant.id)).expires_at=datetime.now(timezone.utc)+timedelta(days=3)
        await db.commit()
    await wallet_alerts.poll(lab.factory,balance)
    async with lab.factory() as db:
        alert=await db.scalar(select(WalletAlert).where(WalletAlert.kind=='approval_expiry'))
        assert not alert.active and not alert.pending


async def test_alert_version_change_during_delivery_does_not_acknowledge_new_alert(lab):
    async def balance(*args):return 10**18
    async with lab.factory() as db:
        db.add(NotificationDevice(user_id=lab.user.id,device_token='versioned-alert-token-long',platform='android',is_active=True,preferences={'wallet_alerts':True}))
        await db.commit()
    await wallet_alerts.poll(lab.factory,balance)
    async def notify(*args,**kwargs):
        async with lab.factory() as db:
            alert=await db.scalar(select(WalletAlert).where(WalletAlert.kind=='approval_expiry'))
            alert.version+=1
            alert.pending=True
            await db.commit()
        return True
    await wallet_alerts.deliver(lab.factory,notify)
    async with lab.factory() as db:
        assert (await db.scalar(select(WalletAlert).where(WalletAlert.kind=='approval_expiry'))).pending


async def test_no_wallet_alert_can_be_broadcast_without_an_owner():
    from app.services.notifier import NotificationService
    assert await NotificationService.send_notification('Private alert','Private wallet funding',category='wallet_alerts') is False
