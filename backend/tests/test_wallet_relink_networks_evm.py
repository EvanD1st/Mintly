"""Fresh cross-account ownership, isolated history and atomic network consent."""
import uuid
from datetime import datetime, timezone
from eth_account import Account
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
import pytest
from app.config import settings
from app.models import Wallet, AutomaticGrant, MintTask, CopyRule
from app.services import automatic
from app.services.custody import CustodyVault
from app.custody_import import app as import_app
from test_automatic_evm import lab, importer
from test_copy_mints import copying


async def admin_importer(lab):
    login = await lab.client.post('/api/auth/login', json={
        'username': 'admin', 'password': 'Admin test password 123'})
    return AsyncClient(transport=ASGITransport(app=import_app), base_url='https://import',
        headers={'Authorization': 'Bearer ' + login.json()['token']})


def new_wallet_request(base, account, password='Member test password 123'):
    request = {k: v for k, v in base.items() if k not in ('wallet_id', 'contract')}
    return {**request, 'request_id': str(uuid.uuid4()), 'private_key': '0x' + account.key.hex(),
        'account_address': account.address, 'collection_scope': 'reviewed_mints', 'password': password}


async def test_transfer_requires_unlink_and_settlement_and_never_moves_history(copying, importer):
    c = copying
    lab = c['lab']
    _, base = importer
    request = new_wallet_request(base, lab.owner, 'Admin test password 123')
    async with await admin_importer(lab) as second:
        assert (await second.post('/api/automatic/import', json=request)).status_code == 409
        await c['approve']()
        await c['mint'](1)
        await c['scan']()
        tid = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]['task_id']
        await lab.sign(tid)
        async with lab.factory() as db:
            raw = (await db.get(MintTask, tid)).signed_tx_raw
        assert (await lab.client.delete('/api/wallets/' + lab.wallet.id)).status_code == 200
        hold = await second.post('/api/automatic/import', json=request)
        assert hold.status_code == 409 and 'unresolved' in hold.text
        # Local EVM only: settle the old signed mint. Unlink itself never broadcasts it.
        lab.w.eth.send_raw_transaction(raw)
        lab.w.provider.make_request('evm_mine', [])
        await lab.due()
        await lab.tick()
        linked = await second.post('/api/automatic/import', json=request)
        assert linked.status_code == 200, linked.text
        fresh = linked.json()
        assert fresh['wallet_id'] != lab.wallet.id
        assert (await second.post('/api/automatic/import', json=request)).json()['id'] == fresh['id']
        assert (await lab.client.get('/api/wallets')).json() == []
        assert len((await lab.client.get('/api/history?section=mints')).json()['records']) == 1
        assert len((await lab.client.get('/api/history?section=copies')).json()['records']) == 1
        for section in ('mints', 'copies', 'plans'):
            assert (await lab.client.get('/api/history?section=' + section,
                headers=dict(second.headers))).json()['records'] == []
        # Old owner cannot bypass the new active owner by explicitly naming their archived row.
        first, original = importer
        back = await first.post('/api/automatic/import', json={**original, 'request_id': str(uuid.uuid4())})
        assert back.status_code == 409
        async with lab.factory() as db:
            old_wallet = await db.get(Wallet, lab.wallet.id)
            new_wallet = await db.get(Wallet, fresh['wallet_id'])
            assert old_wallet.archived_at and old_wallet.user_id == lab.user.id
            assert new_wallet.user_id != lab.user.id and new_wallet.archived_at is None
            assert (await db.get(MintTask, tid)).wallet_id == lab.wallet.id
            assert (await db.get(AutomaticGrant, lab.grant.id)).status == 'disabled'
            assert (await db.get(CopyRule, c['request']['request_id'])).status == 'revoked'
            assert (await db.get(AutomaticGrant, fresh['id'])).status == 'enabled'


@pytest.fixture
def networks(lab, monkeypatch):
    # Consent/policy integration uses real EVM account inspection for each requested network.
    # Network-specific transaction execution remains covered by the existing signer tests.
    requested = []
    for name in ('ETHEREUM', 'BASE', 'ROBINHOOD'):
        monkeypatch.setattr(settings, 'ENABLE_' + name + '_AUTOMATIC', True)
        monkeypatch.setattr(settings, 'RPC_' + name, 'https://isolated-test.invalid')
    async def provider(chain):
        requested.append(chain)
        return await automatic.provider()
    monkeypatch.setattr(automatic, 'provider_for', provider)
    return requested


def bundle_request(base, account):
    request = new_wallet_request(base, account)
    request.pop('budget_eth')
    request.pop('max_task_eth')
    request['networks'] = [{'chain_id': chain, 'budget_eth': budget, 'max_task_eth': '0.001'}
        for chain, budget in ((1, '0.002'), (8453, '0.003'), (4663, '0.004'))]
    return request


async def test_one_key_three_independent_policies_idempotent_and_unlink_disables_all(lab, importer, networks):
    client, base = importer
    account = Account.create()
    request = bundle_request(base, account)
    config = (await client.get('/api/automatic/import/config')).json()
    assert config['multi_network_import'] is True
    before = set(lab.tmp.glob('*.keystore.json'))
    linked = await client.post('/api/automatic/import', json=request)
    assert linked.status_code == 200, linked.text
    response = linked.json()
    assert response['id'] == request['request_id']
    assert set(networks) == {1, 8453, 4663}
    assert len(set(lab.tmp.glob('*.keystore.json')) - before) == 1
    assert {g['chain_id']: g['budget_wei'] for g in response['grants']} == {
        1: '2000000000000000', 8453: '3000000000000000', 4663: '4000000000000000'}
    assert len({g['wallet_id'] for g in response['grants']}) == 1
    async with lab.factory() as db:
        for item in response['grants']:
            grant = await db.get(AutomaticGrant, item['id'])
            policy = CustodyVault().policy(grant)
            assert policy['key_id'] == request['request_id'] and len(policy['network_approvals']) == 3
        changed = await db.get(AutomaticGrant, response['grants'][0]['id'])
        changed.spent_wei = 123
        await db.commit()
    retry = await client.post('/api/automatic/import', json={**request, 'networks': list(reversed(request['networks']))})
    assert retry.status_code == 200 and retry.json()['grants'][0]['spent_wei'] == '123'
    altered = [{**n, 'budget_eth': '0.008'} for n in request['networks']]
    assert (await client.post('/api/automatic/import', json={**request, 'networks': altered})).status_code == 409
    assert (await client.post('/api/automatic/import', json={**request, 'networks': request['networks'][:1]})).status_code == 409
    assert (await lab.client.delete('/api/wallets/' + response['wallet_id'])).status_code == 200
    async with lab.factory() as db:
        grants = (await db.scalars(select(AutomaticGrant).where(AutomaticGrant.wallet_id == response['wallet_id']))).all()
        assert len(grants) == 3 and all(g.status == 'disabled' for g in grants)


@pytest.mark.parametrize('failure', ['duplicate', 'mixed', 'over_budget', 'disabled', 'rpc'])
async def test_bundle_failures_create_no_wallet_key_or_enabled_partial_grants(lab, importer, networks, monkeypatch, failure):
    client, base = importer
    account = Account.create()
    request = bundle_request(base, account)
    before = set(lab.tmp.glob('*.json'))
    if failure == 'duplicate':
        request['networks'][1]['chain_id'] = 1
    elif failure == 'mixed':
        request['budget_eth'] = '0.01'
    elif failure == 'over_budget':
        request['networks'][1]['max_task_eth'] = '0.1'
    elif failure == 'disabled':
        monkeypatch.setattr(settings, 'ENABLE_BASE_AUTOMATIC', False)
    else:
        real_provider = automatic.provider_for
        async def fail_last(chain):
            if chain == 8453:
                raise ValueError('RPC unavailable')
            return await real_provider(chain)
        monkeypatch.setattr(automatic, 'provider_for', fail_last)
    result = await client.post('/api/automatic/import', json=request)
    assert result.status_code in (409, 422)
    assert set(lab.tmp.glob('*.json')) == before
    async with lab.factory() as db:
        assert await db.scalar(select(Wallet).where(Wallet.address == account.address)) is None
        assert await db.get(AutomaticGrant, request['request_id']) is None


async def test_bundle_commit_loss_retries_same_immutable_key_and_all_policies(lab, importer, networks, monkeypatch):
    client, base = importer
    request = bundle_request(base, Account.create())
    from sqlalchemy.ext.asyncio import AsyncSession
    real_commit = AsyncSession.commit
    count = 0
    async def fail_activation(db):
        nonlocal count
        count += 1
        if count == 2:  # attempt-rate commit succeeds; activation commit fails after files are fsynced
            raise RuntimeError('Simulated database loss')
        await real_commit(db)
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, 'commit', fail_activation)
        assert (await client.post('/api/automatic/import', json=request)).status_code == 409
    before = {p.name: p.read_bytes() for p in lab.tmp.glob('*.json')}
    response = await client.post('/api/automatic/import', json=request)
    assert response.status_code == 200, response.text
    assert len(response.json()['grants']) == 3
    assert {p.name: p.read_bytes() for p in lab.tmp.glob('*.json')} == before


async def test_signature_lost_from_database_still_blocks_new_owner_in_independent_journal(copying, importer):
    c = copying
    lab = c['lab']
    _, base = importer
    await c['approve']()
    await c['mint'](1)
    await c['scan']()
    tid = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]['task_id']
    await lab.sign(tid)
    async with lab.factory() as db:
        task = await db.get(MintTask, tid)
        task.signed_tx_raw = task.transaction_hash = None
        task.status = 'armed'  # Simulate loss of the DB commit after independent signature fsync.
        await db.commit()
    await lab.client.delete('/api/wallets/' + lab.wallet.id)
    async with await admin_importer(lab) as second:
        result = await second.post('/api/automatic/import', json=new_wallet_request(base,
            lab.owner, 'Admin test password 123'))
        assert result.status_code == 409 and 'Independent signer' in result.text
    assert (await lab.signer_client.get(f'/accounts/{lab.owner.address}/relink-ready')).json() == {'ready': False}
    unauthenticated = await lab.signer_client.get(f'/accounts/{lab.owner.address}/relink-ready',
        headers={'Authorization': ''})
    assert unauthenticated.status_code == 401


async def test_old_archived_row_cannot_create_second_active_link_for_same_owner(lab, importer):
    client, base = importer
    async with lab.factory() as db:
        archived = Wallet(id=str(uuid.uuid4()), user_id=lab.user.id, address=lab.owner.address,
            label='Historical link', archived_at=datetime.now(timezone.utc))
        db.add(archived)
        await db.commit()
    before = set(lab.tmp.glob('*.json'))
    result = await client.post('/api/automatic/import', json={**base, 'wallet_id': archived.id})
    assert result.status_code == 409 and 'already linked' in result.text
    assert set(lab.tmp.glob('*.json')) == before
    async with lab.factory() as db:
        assert (await db.get(Wallet, archived.id)).archived_at is not None
        assert (await db.get(Wallet, lab.wallet.id)).archived_at is None
