"""One receiving wallet, a shared budget, and safe funding retries on a real local EVM."""
import json
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.config import settings
from app.models import AutomaticGrant, CopyRule, CopyEvent, MintTask
from app.services import automatic, copy_mints
from app.services.custody import CustodyVault, private_write
from test_automatic_evm import lab
from test_copy_mints import copying


@pytest.fixture
async def wallet_networks(copying, monkeypatch):
    c = copying
    lab = c['lab']
    monkeypatch.setattr(settings, 'ENABLE_ETHEREUM_AUTOMATIC', True)
    monkeypatch.setattr(settings, 'RPC_ETHEREUM', 'https://isolated-test.invalid')
    # Approval metadata for a second network; execution itself stays on the real isolated EVM.
    real_provider = automatic.provider_for
    async def provider(chain):
        return await automatic.provider() if chain == 1 else await real_provider(chain)
    monkeypatch.setattr(automatic, 'provider_for', provider)
    async with lab.factory() as db:
        original = await db.get(AutomaticGrant, lab.grant.id)
        policy = CustodyVault().policy(original)
        gid = str(uuid.uuid4())
        policy = {**policy, 'grant_id': gid, 'chain_id': 1}
        private_write(lab.tmp / f'{gid}.policy.json', json.dumps(policy))
        grant = AutomaticGrant(id=gid, user_id=lab.user.id, wallet_id=lab.wallet.id, account=lab.owner.address,
            chain_id=1, context_hash=automatic.digest(policy), scope=dict(original.scope),
            budget_wei=original.budget_wei, expires_at=original.expires_at, status='enabled')
        db.add(grant)
        await db.commit()
    request = {k:v for k,v in c['request'].items() if k != 'grant_id'}
    request['grant_ids'] = [lab.grant.id, gid]
    return c, request


async def approve_group(c, request):
    response = await c['lab'].client.post(f'/api/copy-mints/watches/{c["watch_id"]}/wallet-rules', json=request)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'active'
    return response.json()


async def test_wallet_approval_pins_all_networks_one_budget_and_retry_never_resets(wallet_networks):
    c, request = wallet_networks
    lab = c['lab']
    response = await approve_group(c, request)
    assert {r['chain_id'] for r in response['rules']} == {1, 31337}
    group = response['rules'][0]['snapshot']['budget_group']
    assert group['budget_wei'] == 10**15
    assert len(group['members']) == 2
    local = next(r for r in response['rules'] if r['chain_id'] == 31337)
    async with lab.factory() as db:
        rule = await db.get(CopyRule, local['id'])
        rule.spent_wei = 123
        await db.commit()
    again = await approve_group(c, {**request, 'grant_ids': list(reversed(request['grant_ids']))})
    assert next(r for r in again['rules'] if r['chain_id'] == 31337)['spent_wei'] == '123'
    for changed in ({**request, 'budget_eth':'0.002'}, {**request, 'grant_ids':request['grant_ids'][:1]}):
        assert (await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/wallet-rules', json=changed)).status_code == 409
    await c['mint'](1)
    await c['scan']()
    tid = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]['task_id']
    await lab.sign(tid)
    await lab.due()
    await lab.tick()
    lab.w.provider.make_request('evm_mine', [])
    await lab.due()
    await lab.tick()
    assert (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]['status'] == 'confirmed'
    async with lab.factory() as db:
        rule = await db.get(CopyRule, local['id'])
        assert await copy_mints.group_remaining(db, rule) == 10**15 - rule.spent_wei
    journal = CustodyVault().journal()
    for member in group['members']:
        assert json.loads(journal.execute('SELECT snapshot FROM copy_rules WHERE id=?', (member,)).fetchone()[0])['budget_group'] == group
    journal.close()


async def test_partial_signer_registration_never_activates_any_network_and_retry_completes(wallet_networks, monkeypatch):
    c, request = wallet_networks
    lab = c['lab']
    from app.api import copy_mints as api
    real_register = api.register_rule
    count = 0
    async def fail_second(rule_id):
        nonlocal count
        count += 1
        if count == 2:
            raise HTTPException(503, 'Simulated control interruption')
        await real_register(rule_id)
    with monkeypatch.context() as patch:
        patch.setattr(api, 'register_rule', fail_second)
        response = await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/wallet-rules', json=request)
        assert response.status_code == 503
    async with lab.factory() as db:
        rules = (await db.scalars(select(CopyRule))).all()
        assert len(rules) == 2 and all(r.status == 'registering' for r in rules)
    await approve_group(c, request)
    await lab.client.post('/api/copy-mints/pause', json={'paused': True})
    retry = await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/wallet-rules', json=request)
    assert retry.status_code == 200 and retry.json()['status'] == 'inactive'


async def test_other_network_reservations_exhaust_the_shared_budget(wallet_networks):
    c, request = wallet_networks
    lab = c['lab']
    response = await approve_group(c, request)
    other = next(r for r in response['rules'] if r['chain_id'] == 1)
    async with lab.factory() as db:
        (await db.get(CopyRule, other['id'])).reserved_wei = 500000000000001
        await db.commit()
    await c['mint'](1)
    await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['status'] == 'skipped' and event['task_id'] is None
    assert event['note'] == 'Total copy budget is used or reserved by pending mints.'


async def test_independent_journal_blocks_overspend_even_when_database_sibling_accounting_is_reset(wallet_networks):
    c, request = wallet_networks
    lab = c['lab']
    response = await approve_group(c, request)
    other = next(r for r in response['rules'] if r['chain_id'] == 1)
    await c['mint'](1)
    await c['scan']()
    tid = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]['task_id']
    journal = CustodyVault().journal()
    journal.execute('INSERT INTO signed(task,policy,intent,address,chain,nonce,liability,raw,hash) VALUES(?,?,?,?,?,?,?,?,?)',
        ('synthetic-other-network', other['snapshot']['grant_id'], 'test', lab.owner.address.lower(), 1, 41,
            500000000000001, '0xdead', '0x' + '11' * 32))
    journal.execute('INSERT INTO copy_signed(task,rule,stage) VALUES(?,?,?)',
        ('synthetic-other-network', other['id'], 'synthetic-stage'))
    journal.commit()
    journal.close()
    response = await lab.signer_client.post(f'/tasks/{tid}/prepare')
    assert response.status_code == 409 and 'shared copy budget' in response.text
    async with lab.factory() as db:
        assert (await db.get(MintTask, tid)).signed_tx_raw is None


@pytest.mark.parametrize('free', [False, True])
async def test_empty_balance_skips_without_a_task_then_funded_retry_mints_once(copying, monkeypatch, free):
    c = copying
    lab = c['lab']
    if free:
        from test_copy_mints import free_stage
        free_stage(lab)
        c['request'].update(quantity=100, quantity_mode='max_free', free_only=True, price_cap_eth='0')
    await c['approve']()
    await c['mint'](1)
    lab.w.provider.make_request('hardhat_setBalance', [lab.owner.address, '0x0'])
    await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['status'] == 'skipped' and event['task_id'] is None and event['retryable']
    assert event['note'] == copy_mints.funding_note(31337, not free)
    retry = f'/api/copy-mints/events/{event["id"]}/retry'
    assert (await lab.client.post(retry, json={})).status_code == 409
    lab.w.provider.make_request('hardhat_setBalance', [lab.owner.address, hex(10**18)])
    first = await lab.client.post(retry, json={})
    assert first.status_code == 200, first.text
    tid = first.json()['task_id']
    assert (await lab.client.post(retry, json={})).json()['task_id'] == tid
    await lab.sign(tid)
    assert (await lab.client.post(retry, json={})).status_code == 409
    await lab.due()
    await lab.tick()
    lab.w.provider.make_request('evm_mine', [])
    await lab.due()
    await lab.tick()
    assert (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]['status'] == 'confirmed'
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 1
    journal.close()


async def test_balance_drained_after_arming_has_short_note_and_retry_reuses_unsigned_task(copying, monkeypatch):
    c = copying
    lab = c['lab']
    await c['approve']()
    await c['mint'](1)
    await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    tid = event['task_id']
    lab.w.provider.make_request('hardhat_setBalance', [lab.owner.address, '0x0'])
    await lab.due()
    await lab.tick()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['status'] == 'skipped' and event['retryable'] and event['note'] == copy_mints.funding_note(31337, True)
    async def confirm_unsigned(task_id):
        assert (await lab.signer_client.get(f'/tasks/{task_id}/unsigned')).json() == {'unsigned': True}
    monkeypatch.setattr('app.api.copy_mints.confirm_unsigned', confirm_unsigned)
    lab.w.provider.make_request('hardhat_setBalance', [lab.owner.address, hex(10**18)])
    retry = await lab.client.post(f'/api/copy-mints/events/{event["id"]}/retry', json={})
    assert retry.status_code == 200 and retry.json()['task_id'] == tid
    await lab.sign(tid)
    async with lab.factory() as db:
        assert (await db.get(MintTask, tid)).signed_tx_raw


async def test_funding_retry_never_rearms_a_signature_lost_from_the_database(copying, monkeypatch):
    c = copying
    lab = c['lab']
    await c['approve']()
    await c['mint'](1)
    await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    tid = event['task_id']
    await lab.sign(tid)
    async with lab.factory() as db:
        task = await db.get(MintTask, tid)
        task.signed_tx_raw = task.transaction_hash = None
        await automatic.release_reservation(db, task)
        task.status, task.failure_reason = 'failed', copy_mints.funding_note(31337, True)
        await db.commit()
    async def unsigned(task_id):
        response = await lab.signer_client.get(f'/tasks/{task_id}/unsigned')
        assert response.json() == {'unsigned': False}
        raise HTTPException(409, 'Independent journal contains a signature')
    monkeypatch.setattr('app.api.copy_mints.confirm_unsigned', unsigned)
    retry = await lab.client.post(f'/api/copy-mints/events/{event["id"]}/retry', json={})
    assert retry.status_code == 409
    async with lab.factory() as db:
        assert (await db.get(MintTask, tid)).status == 'failed'
        assert (await db.get(AutomaticGrant, lab.grant.id)).reserved_wei == 0


@pytest.mark.parametrize('block', ['paused', 'unlinked', 'expired', 'foreign'])
async def test_funding_retry_respects_current_owner_and_approval(copying, block):
    c = copying
    lab = c['lab']
    await c['approve']()
    await c['mint'](1)
    lab.w.provider.make_request('hardhat_setBalance', [lab.owner.address, '0x0'])
    await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    if block == 'paused':
        await lab.client.post('/api/copy-mints/pause', json={'paused': True})
    if block == 'unlinked':
        await lab.client.delete('/api/wallets/' + lab.wallet.id)
    if block == 'expired':
        lab.w.provider.make_request('evm_setNextBlockTimestamp', [lab.end + 1])
        lab.w.provider.make_request('evm_mine', [])
    headers = {}
    if block == 'foreign':
        login = await lab.client.post('/api/auth/login', json={'username':'admin','password':'Admin test password 123'})
        headers['Authorization'] = 'Bearer ' + login.json()['token']
    lab.w.provider.make_request('hardhat_setBalance', [lab.owner.address, hex(10**18)])
    response = await lab.client.post(f'/api/copy-mints/events/{event["id"]}/retry', json={}, headers=headers)
    assert response.status_code in (404, 409)
    assert (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]['task_id'] is None
