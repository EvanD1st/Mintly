"""Real disposable EVM checks: no production wallets or mainnet spending."""
import asyncio
from datetime import datetime, timezone
import uuid
from types import SimpleNamespace
import pytest
from eth_account import Account
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.models import User, CopyWatch, CopyRule, CopyEvent, MintTask, MintAuthorization, AutomaticGrant
from app.services import automatic, automatic_signer, copy_mints
from app.services.custody import CustodyVault
from app.automatic_worker import preflight_step
from app.copy_worker import step as copy_step
from test_automatic_evm import lab
from test_copy_mints import copying


async def test_pause_all_is_owned_idempotent_and_disarms_both_bots(copying):
    c = copying; lab = c['lab']
    await c['approve'](); await c['mint'](); await c['scan']()
    scheduled = await lab.client.post('/api/tasks/arm', json=lab.request)
    assert scheduled.status_code == 200, scheduled.text
    for _ in range(2):
        result = await lab.client.post('/api/automatic/pause', json={'paused':True})
        assert result.status_code == 200 and result.json()['paused']
    async with lab.factory() as db:
        tasks = (await db.scalars(select(MintTask))).all()
        assert len(tasks) == 2 and all(task.status == 'disarmed' and task.signed_tx_raw is None for task in tasks)
        assert (await db.get(AutomaticGrant, lab.grant.id)).reserved_wei == 0
        assert (await db.get(CopyRule, c['request']['request_id'])).status == 'paused'
        assert (await db.get(User, lab.user.id)).automation_paused
    assert (await lab.client.post('/api/tasks/arm', json={**lab.request,'idempotency_key':'paused-new-intent'})).status_code == 409
    assert (await lab.client.post('/api/copy-mints/pause', json={'paused':False})).status_code == 409
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as other:
        login = await other.post('/api/auth/login', json={'username':'admin','password':'Admin test password 123'})
        other.headers['Authorization'] = 'Bearer ' + login.json()['token']
        assert (await other.get('/api/automatic/status')).json() == {'paused':False}
        await other.post('/api/automatic/pause', json={'paused':False})
    assert (await lab.client.get('/api/automatic/status')).json()['paused']
    await lab.client.post('/api/automatic/pause', json={'paused':False})
    async with lab.factory() as db:
        assert all(t.status == 'disarmed' for t in (await db.scalars(select(MintTask))).all())
        assert (await db.get(CopyRule,c['request']['request_id'])).status == 'paused'
    assert lab.nft.functions.totalSupply().call() == 2  # Only the observed source mint.


async def test_pause_holds_saved_signature_but_still_tracks_external_receipt(lab):
    response = await lab.client.post('/api/tasks/arm', json=lab.request)
    tid = response.json()['id']
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]); lab.w.provider.make_request('evm_mine',[])
    await lab.sign(tid)
    await lab.client.post('/api/automatic/pause', json={'paused':True})
    await lab.due(); await lab.tick()
    async with lab.factory() as db:
        task = await db.get(MintTask,tid)
        assert task.broadcast_attempts == 0 and task.signed_tx_raw and task.status == 'prepared'
        raw = task.signed_tx_raw
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei > 0
    lab.w.eth.send_raw_transaction(raw)
    lab.w.provider.make_request('evm_mine',[])
    await lab.due(); await lab.tick()
    async with lab.factory() as db:
        assert (await db.get(MintTask,tid)).status == 'confirmed'
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei == 0


async def test_advance_checks_never_sign_or_reserve_nonce_and_keep_time_gate(lab, monkeypatch):
    selected = lab.start + 60
    request = {**lab.request,'scheduled_for_utc':datetime.fromtimestamp(selected,timezone.utc).isoformat()}
    tid = (await lab.client.post('/api/tasks/arm',json=request)).json()['id']
    def forbidden_key(*args):
        pytest.fail('Advance checks must never decrypt a private key')
    with monkeypatch.context() as scope:
        scope.setattr(CustodyVault,'account',forbidden_key)
        response = await lab.signer_client.post(f'/tasks/{tid}/preflight')
        assert response.status_code == 200, response.text
    async with lab.factory() as db:
        task = await db.get(MintTask,tid)
        assert task.preflight_checked_at and 'passed' in task.preflight_note
        assert task.signed_tx_raw is None and task.assigned_nonce is None
        before = (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 0
    journal.close()
    assert (await lab.sign(tid))['status'] == 'armed'
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[selected]); lab.w.provider.make_request('evm_mine',[])
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(selected, timezone.utc)
    monkeypatch.setattr(automatic_signer,'datetime',Clock)
    async def no_repeat(*args):
        pytest.fail('A fresh successful advance reconciliation should remove that RPC work at signing time')
    monkeypatch.setattr(automatic_signer,'reconcile_policy',no_repeat)
    assert (await lab.sign(tid))['status'] == 'prepared'
    async with lab.factory() as db:
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei == before


async def test_changed_stage_is_rechecked_after_successful_preflight(lab):
    tid = (await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    assert (await lab.signer_client.post(f'/tasks/{tid}/preflight')).status_code == 200
    lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
    lab.sea.functions.updatePublicDrop((11,lab.start,lab.end,20,500,True)).transact({'from':lab.nft.address})
    lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]); lab.w.provider.make_request('evm_mine',[])
    result = await lab.signer_client.post(f'/tasks/{tid}/prepare')
    assert result.status_code == 409
    async with lab.factory() as db:
        assert (await db.get(MintTask,tid)).signed_tx_raw is None


async def test_conditional_whitelist_proof_is_prepared_ahead_and_revalidated(lab, monkeypatch):
    from app.services.opensea import OpenSeaUnavailable
    lab.kind = 'allowlist'
    request = {**lab.request,'mint_kind':'allowlist','conditional_eligibility':True,'onchain_stage_index':1}
    async def unavailable(*args):
        raise OpenSeaUnavailable('Provider not ready',503)
    with monkeypatch.context() as scope:
        scope.setattr(automatic,'prepare_mint',unavailable)
        response = await lab.client.post('/api/tasks/arm',json=request)
    assert response.status_code == 200,response.text
    tid = response.json()['id']
    result = await lab.signer_client.post(f'/tasks/{tid}/preflight')
    assert result.status_code == 200 and 'passed' in result.json()['note']
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]); lab.w.provider.make_request('evm_mine',[])
    async def no_lookup(*args):
        pytest.fail('A fresh cached wallet-specific proof should avoid another provider lookup')
    monkeypatch.setattr(automatic,'prepare_mint',no_lookup)
    assert (await lab.sign(tid))['status'] == 'prepared'
    await lab.due(); await lab.tick()
    assert lab.nft.functions.ownerOf(1).call() == lab.owner.address


async def test_pause_during_advance_rpc_cannot_restore_or_sign_task(lab, monkeypatch):
    tid = (await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    original = automatic.validate_mint
    async def checked(*args):
        await lab.client.post('/api/automatic/pause',json={'paused':True})
        return await original(*args)
    monkeypatch.setattr(automatic,'validate_mint',checked)
    assert (await lab.signer_client.post(f'/tasks/{tid}/preflight')).status_code == 503
    async with lab.factory() as db:
        task = await db.get(MintTask,tid)
        assert task.status == 'disarmed' and task.signed_tx_raw is None and task.preflight_checked_at is None


async def test_concurrent_discovery_serializes_same_collection_reservations(copying, monkeypatch):
    c = copying; lab = c['lab']
    await c['approve']()
    second = Account.create()
    lab.w.provider.make_request('hardhat_setBalance',[second.address,hex(10**18)])
    watch = (await lab.client.post('/api/copy-mints/watches',json={'address':second.address,'label':'Second source','chains':[31337]})).json()
    approved = await lab.client.post(f'/api/copy-mints/watches/{watch["id"]}/rules',
        json={**c['request'],'request_id':str(uuid.uuid4())})
    assert approved.status_code == 200, approved.text
    await c['mint'](1); await c['mint'](1,second)
    reached = 0
    barrier = asyncio.Event()
    original = copy_mints.discover_watch
    async def discover(watch,chain):
        nonlocal reached
        reached += 1
        if reached == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(),5)
        return await original(watch,chain)
    monkeypatch.setattr(copy_mints,'discover_watch',discover)
    assert await copy_step(lab.factory)
    async with lab.factory() as db:
        events = (await db.scalars(select(CopyEvent))).all()
        tasks = (await db.scalars(select(MintTask))).all()
        assert reached == 2 and len(events) == 2 and len(tasks) == 1
        auth = await db.get(MintAuthorization,tasks[0].authorization_id)
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei == auth.total_spend_cap_wei
        assert sum(r.reserved_wei for r in (await db.scalars(select(CopyRule))).all()) == auth.total_spend_cap_wei
        assert all(w.cursors['31337']['status'] == 'monitoring' for w in (await db.scalars(select(CopyWatch))).all())


async def test_readiness_separates_balance_budget_and_outage_and_excludes_foreign_wallets(lab, monkeypatch):
    async with lab.factory() as db:
        (await db.get(AutomaticGrant,lab.grant.id)).chain_id = 1
        await db.commit()
    class Eth:
        async def get_balance(self,address,block):
            return 0
    async def disconnect():
        pass
    async def provider(chain):
        if chain == 8453:
            raise RuntimeError('RPC unavailable')
        return SimpleNamespace(eth=Eth(),provider=SimpleNamespace(disconnect=disconnect))
    monkeypatch.setattr(automatic,'provider_for',provider)
    result = await lab.client.get('/api/wallets/readiness')
    assert result.status_code == 200
    wallets = result.json()['wallets']
    assert [w['wallet_id'] for w in wallets] == [lab.wallet.id]
    networks = {n['chain_id']:n for n in wallets[0]['networks']}
    assert networks[1]['balance_wei'] == '0' and networks[1]['gas_status'] == 'Add ETH for gas'
    assert networks[1]['approval_status'] == 'active' and int(networks[1]['approved_remaining_wei']) > 0
    assert networks[8453]['balance_wei'] is None and networks[8453]['balance_status'] == 'unavailable'
    assert networks[8453]['approved_remaining_wei'] == '0'
    assert 'private' not in result.text and lab.owner.key.hex() not in result.text


async def test_preflight_worker_does_not_delay_due_tasks_or_run_for_paused_user(lab):
    tid = (await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']
    checked = []
    async def check(task_id):
        checked.append(task_id)
    before = datetime.fromtimestamp(lab.start-60,timezone.utc)
    assert await preflight_step(lab.factory,check,now=before) == 1 and checked == [tid]
    assert await preflight_step(lab.factory,check,now=datetime.fromtimestamp(lab.start,timezone.utc)) == 0
    await lab.client.post('/api/automatic/pause',json={'paused':True})
    assert await preflight_step(lab.factory,check,now=before) == 0


async def test_parallel_network_updates_preserve_each_others_cursor(copying, monkeypatch):
    c = copying; lab = c['lab']
    async with lab.factory() as db:
        (await db.get(CopyWatch,c['watch_id'])).chains = [31337,1]
        await db.commit()
    barrier = asyncio.Event()
    reached = 0
    async def discover(watch,chain):
        nonlocal reached
        reached += 1
        if reached == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(),5)
        if chain == 1:
            raise RuntimeError('One network failed')
        return {'block':42,'hash':'read-only-test','status':'monitoring'}, []
    monkeypatch.setattr(copy_mints,'discover_watch',discover)
    assert await copy_step(lab.factory)
    async with lab.factory() as db:
        watch = await db.get(CopyWatch,c['watch_id'])
        assert watch.cursors['31337']['block'] == 42
        assert watch.cursors['1']['status'] == 'unavailable'
