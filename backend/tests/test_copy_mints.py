"""Real public source mint -> finite copy approval -> isolated signature -> receipt."""
from datetime import datetime, timezone, timedelta
import uuid
from eth_account import Account
from httpx import AsyncClient, ASGITransport
import pytest
from sqlalchemy import select
from app.models import CopyEvent, CopyWatch, CopyRule, MintTask, MintAuthorization, AutomaticGrant
from app.services import automatic, copy_mints
from app.services.custody import CustodyVault
from app.config import settings
from app.main import app
from test_automatic_evm import lab


@pytest.fixture
async def copying(lab, monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_COPY_MINTS', True)
    async def register(rule_id):
        response = await lab.signer_client.post(f'/copy-rules/{rule_id}/register')
        response.raise_for_status()
    monkeypatch.setattr('app.api.copy_mints.register_rule', register)
    source = Account.create()
    lab.w.provider.make_request('hardhat_setBalance', [source.address, hex(10**18)])
    follow = await lab.client.post('/api/copy-mints/watches', json={'address': source.address,
        'label': 'Source wallet', 'chains': [31337]})
    assert follow.status_code == 200, follow.text
    watch_id = follow.json()['id']
    request = dict(request_id=str(uuid.uuid4()), grant_id=lab.grant.id, quantity=1,
        price_cap_eth='0.00000000000000001', fee_cap_eth='0.0005', budget_eth='0.001',
        free_only=False, expires_at=datetime.fromtimestamp(lab.end, timezone.utc).isoformat(), consent=True)
    async def approve():
        result = await lab.client.post(f'/api/copy-mints/watches/{watch_id}/rules', json=request)
        assert result.status_code == 200, result.text
        return result.json()
    async def mint(quantity=2, watched=source):
        if lab.w.eth.get_block('latest').timestamp < lab.start:
            lab.w.provider.make_request('evm_setNextBlockTimestamp', [lab.start])
        fee = lab.w.eth.accounts[1]
        tx = lab.sea.functions.mintPublic(lab.nft.address, fee, watched.address, quantity).build_transaction({
            'from': watched.address, 'nonce': lab.w.eth.get_transaction_count(watched.address),
            'gas': 400000, 'gasPrice': lab.w.eth.gas_price, 'value': 10 * quantity, 'chainId': 31337})
        result = lab.w.eth.send_raw_transaction(watched.sign_transaction(tx).raw_transaction)
        receipt = lab.w.eth.wait_for_transaction_receipt(result)
        assert receipt.status == 1
        for _ in range(12): lab.w.provider.make_request('evm_mine', [])
        return '0x' + bytes(result).hex()
    async def scan():
        async with lab.factory() as db:
            watch = await db.get(CopyWatch, watch_id)
            await copy_mints.scan_watch(db, watch, 31337)
            await db.commit()
    return dict(lab=lab, source=source, watch_id=watch_id, request=request, approve=approve, mint=mint, scan=scan)


async def test_source_to_copy_receipt_limits_history_and_duplicate_signal(copying):
    c = copying; lab = c['lab']
    assert (await c['approve']())['status'] == 'active'
    source_hash = await c['mint']()
    web3 = await automatic.provider()
    try:
        observed = await copy_mints.observe(web3, 31337, source_hash, c['source'].address, lab.nft.address)
        assert observed['source_quantity'] == 2
    finally:
        await web3.provider.disconnect()
    await c['scan']()
    async with lab.factory() as db:
        event = await db.scalar(select(CopyEvent).where(CopyEvent.watch_id == c['watch_id']))
        assert event and event.task_id, event.note if event else (await db.get(CopyWatch, c['watch_id'])).cursors
        task_id = event.task_id
        auth = await db.get(MintAuthorization, (await db.get(MintTask, task_id)).authorization_id)
        assert auth.quantity == 1 and auth.snapshot['copy_source']['source_hash'] == source_hash
    await lab.sign(task_id)
    await lab.due(); await lab.tick()
    lab.w.provider.make_request('evm_mine', [])
    await lab.due(); await lab.tick()
    async with lab.factory() as db:
        task = await db.get(MintTask, task_id)
        assert task.status == 'confirmed', task.failure_reason
        rule = await db.get(CopyRule, c['request']['request_id'])
        assert rule.spent_wei == task.actual_total_cost_wei and rule.reserved_wei == 0
        assert task.actual_total_cost_wei <= auth.total_spend_cap_wei
    assert lab.nft.functions.totalSupply().call() == 3
    assert lab.nft.functions.ownerOf(3).call() == lab.owner.address
    await c['mint'](1); await c['scan']()
    activity = (await lab.client.get('/api/copy-mints/activity')).json()
    assert activity['copied_mints'] == 1 and len(activity['events']) == 2
    assert {e['status'] for e in activity['events']} == {'confirmed','skipped'}
    removed = await lab.client.delete(f'/api/copy-mints/watches/{c["watch_id"]}')
    assert removed.status_code == 200 and removed.json()['history_retained']
    assert len((await lab.client.get('/api/copy-mints/activity')).json()['events']) == 2
    history = (await lab.client.get('/api/history?section=copies')).json()['records']
    assert history[0]['status'] == 'revoked' and history[0]['authorization']['quantity'] == 1
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM copy_signed').fetchone()[0] == 1
    journal.close()


async def test_monitoring_never_spends_before_approval_and_recent_copy_requires_review(copying):
    c = copying; lab = c['lab']
    await c['mint'](); await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['status'] == 'detected' and event['task_id'] is None
    assert (await lab.client.get('/api/tasks/queue')).json()['tasks'] == []
    await c['approve'](); await c['scan']()
    assert (await lab.client.get('/api/tasks/queue')).json()['tasks'] == []
    context = await lab.client.get(f'/api/copy-mints/events/{event["id"]}/context')
    assert context.status_code == 200, context.text
    drop = context.json()['drop']
    request = {**lab.request, 'drop_id': drop['id'], 'stage_id': drop['stages'][0]['id'], 'copy_event_id': event['id']}
    arm = await lab.client.post('/api/tasks/arm', json=request)
    assert arm.status_code == 200, arm.text
    await lab.sign(arm.json()['id'])
    assert (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]['status'] == 'prepared'


async def test_signer_rejects_historical_auto_copy_even_if_database_cursor_is_changed(copying):
    c = copying; lab = c['lab']
    await c['mint'](); await c['scan']()
    await c['approve']()
    async with lab.factory() as db:
        rule = await db.get(CopyRule, c['request']['request_id'])
        rule.resume_after_block = -1
        await db.commit()
    await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['task_id'] is not None
    response = await lab.signer_client.post(f'/tasks/{event["task_id"]}/prepare')
    assert response.status_code == 409, response.text
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 0
    journal.close()


async def test_failed_network_discovery_preserves_other_network_monitoring(copying, monkeypatch):
    from unittest.mock import AsyncMock
    c = copying; lab = c['lab']
    async with lab.factory() as db:
        watch = await db.get(CopyWatch, c['watch_id'])
        with monkeypatch.context() as patch:
            patch.setattr(automatic, 'provider_for', AsyncMock(side_effect=ValueError('RPC unavailable')))
            await copy_mints.scan_watch(db, watch, 1)
            await db.commit()
        assert watch.cursors['1']['status'] == 'unavailable'
    await c['mint'](); await c['scan']()
    activity = (await lab.client.get('/api/copy-mints/activity')).json()
    assert len(activity['events']) == 1 and activity['events'][0]['task_id'] is None


@pytest.mark.parametrize('signed', [False, True])
async def test_pause_releases_only_unsigned_copies_and_remove_retains_records(copying, signed):
    c = copying; lab = c['lab']
    await c['approve'](); await c['mint'](); await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    if signed: await lab.sign(event['task_id'])
    response = await lab.client.post('/api/copy-mints/pause', json={'paused': True})
    assert response.status_code == 200, response.text
    async with lab.factory() as db:
        task = await db.get(MintTask, event['task_id'])
        grant = await db.get(AutomaticGrant, lab.grant.id)
        rule = await db.get(CopyRule, c['request']['request_id'])
        assert rule.status == 'paused'
        assert task.status == ('prepared' if signed else 'disarmed')
        assert bool(grant.reserved_wei) == signed and bool(rule.reserved_wei) == signed
    if signed:
        await lab.due(); await lab.tick(); lab.w.provider.make_request('evm_mine', [])
        await lab.due(); await lab.tick()
        assert (await lab.client.get('/api/copy-mints/activity')).json()['copied_mints'] == 1


@pytest.mark.parametrize('change', ['quantity','fee','source','budget','context'])
async def test_independent_copy_pin_rejects_database_tampering(copying, change):
    c = copying; lab = c['lab']
    await c['approve'](); await c['mint'](); await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    async with lab.factory() as db:
        rule = await db.get(CopyRule, c['request']['request_id'])
        r = dict(rule.snapshot)
        if change == 'context': rule.context_hash = 'f' * 64
        else:
            key = {'quantity':'quantity','fee':'fee_cap_wei','source':'source_address','budget':'budget_wei'}[change]
            r[key] = '0x' + '1'*40 if change == 'source' else r[key] + 1
            rule.snapshot, rule.context_hash = r, automatic.digest(r)
        await db.commit()
    response = await lab.signer_client.post(f'/tasks/{event["task_id"]}/prepare')
    assert response.status_code == 409, response.text
    assert lab.nft.functions.totalSupply().call() == 2
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 0
    journal.close()


async def test_copy_endpoints_are_owner_scoped_and_require_explicit_finite_consent(copying):
    c = copying; lab = c['lab']
    bad = await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/rules', json={**c['request'], 'consent': False})
    assert bad.status_code == 422
    bad = await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/rules', json={**c['request'], 'budget_eth':'1'})
    assert bad.status_code == 409
    await c['mint'](); await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as other:
        login = await other.post('/api/auth/login', json={'username':'admin','password':'Admin test password 123'})
        other.headers['Authorization'] = 'Bearer ' + login.json()['token']
        assert (await other.get('/api/copy-mints')).json()['watches'] == []
        assert (await other.get('/api/copy-mints/activity')).json()['events'] == []
        assert (await other.get(f'/api/copy-mints/events/{event["id"]}/context')).status_code == 404
        assert (await other.delete(f'/api/copy-mints/watches/{c["watch_id"]}')).status_code == 404


async def test_resume_skips_paused_interval_and_does_not_reset_approval(copying):
    c = copying; lab = c['lab']
    rule = await c['approve']()
    assert (await lab.client.post('/api/copy-mints/pause', json={'paused':True})).status_code == 200
    await c['mint'](); await c['scan']()
    assert (await lab.client.get('/api/tasks/queue')).json()['tasks'] == []
    assert (await lab.client.post('/api/copy-mints/pause', json={'paused':False})).status_code == 200
    await c['scan']()
    assert (await lab.client.get('/api/tasks/queue')).json()['tasks'] == []
    assert (await c['approve']())['id'] == rule['id']
    await c['mint'](1); await c['scan']()
    assert len((await lab.client.get('/api/tasks/queue')).json()['tasks']) == 1


async def test_copy_journal_prevents_database_spend_reset_from_adding_another_mint(copying):
    c = copying; lab = c['lab']
    c['request']['budget_eth'] = '0.00050000000000001'
    await c['approve'](); await c['mint'](); await c['scan']()
    first = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    await lab.sign(first['task_id']); await lab.due(); await lab.tick()
    lab.w.provider.make_request('evm_mine', []); await lab.due(); await lab.tick()
    # A new stage is distinct from duplicate-stage protection, but cannot reset an old allowance.
    next_start = lab.w.eth.get_block('latest').timestamp
    lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
    lab.sea.functions.updatePublicDrop((10,next_start,lab.end,20,500,True)).transact({'from':lab.nft.address})
    lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
    async with lab.factory() as db:
        rule = await db.get(CopyRule,c['request']['request_id'])
        assert rule.spent_wei > 0
        rule.spent_wei = 0  # The trusted API never does this; simulate corrupted mutable accounting.
        await db.commit()
    await c['mint'](1); await c['scan']()
    latest = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert latest['task_id'] and latest['task_id'] != first['task_id']
    response = await lab.signer_client.post(f'/tasks/{latest["task_id"]}/prepare')
    assert response.status_code == 409
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 1
    journal.close()


async def test_copy_feature_deactivation_stops_unsigned_signing(copying, monkeypatch):
    c = copying; lab = c['lab']
    await c['approve'](); await c['mint'](); await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    monkeypatch.setattr(settings,'ENABLE_COPY_MINTS',False)
    assert (await lab.signer_client.post(f'/tasks/{event["task_id"]}/prepare')).status_code == 409
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 0
    journal.close()


async def test_base_inclusion_overrun_keeps_real_charge_and_disables_future_copying(copying):
    c = copying; lab = c['lab']
    await c['approve'](); await c['mint'](); await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    async with lab.factory() as db:
        task = await db.get(MintTask,event['task_id'])
        grant = await db.get(AutomaticGrant,lab.grant.id)
        grant.chain_id = 8453  # Exercise Base settlement without sending a mainnet transaction.
        actual = grant.budget_wei + 1
        task.status = 'confirmed'
        await automatic.release_reservation(db,task,actual)
        await db.commit()
        rule = await db.get(CopyRule,c['request']['request_id'])
        assert grant.status == 'disabled' and grant.spent_wei == actual and grant.reserved_wei == 0
        assert rule.status == 'paused' and rule.spent_wei == actual and rule.reserved_wei == 0
