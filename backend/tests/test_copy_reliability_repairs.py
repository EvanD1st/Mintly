"""Regressions for production free-budget skips and opaque wallet approval failures."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import CopyRule, MintTask, MintAuthorization, MintAttemptDiagnostic
from app.services import automatic, copy_mints, mint_diagnostics
from app.services.custody import CustodyVault
from app.services.custody_accounts import WalletApprovalChanged
from test_automatic_evm import lab
from test_copy_mints import copying, free_stage
from test_copy_wallet_networks import wallet_networks, approve_group


async def settle(c, task_id):
    lab = c['lab']
    await lab.sign(task_id)
    await lab.due(); await lab.tick()
    lab.w.provider.make_request('evm_mine', [])
    await lab.due(); await lab.tick()
    async with lab.factory() as db:
        assert (await db.get(MintTask, task_id)).status == 'confirmed'


def next_free_stage(lab):
    lab.w.provider.make_request('hardhat_impersonateAccount', [lab.nft.address])
    lab.w.eth.wait_for_transaction_receipt(lab.sea.functions.updatePublicDrop(
        (0, lab.w.eth.get_block('latest').timestamp, lab.end, 2, 500, True)
    ).transact({'from': lab.nft.address}))
    lab.w.provider.make_request('hardhat_stopImpersonatingAccount', [lab.nft.address])


@pytest.mark.parametrize('mode', ['fixed', 'max_free'])
async def test_free_copy_can_use_budget_remaining_after_a_confirmed_mint(copying, mode):
    c = copying; lab = c['lab']
    free_stage(lab, limit=1)
    c['request'].update(quantity=100 if mode == 'max_free' else 1, quantity_mode=mode,
        free_only=True, price_cap_eth='0', fee_cap_eth='0.0005', budget_eth='0.0005')
    original = await c['approve']()
    await c['mint'](1); await c['scan']()
    first = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    await settle(c, first['task_id'])
    async with lab.factory() as db:
        rule = await db.get(CopyRule, original['id'])
        assert 0 < rule.spent_wei < rule.budget_wei
        remaining = rule.budget_wei - rule.spent_wei
        original_hash = rule.context_hash
    next_free_stage(lab)
    await c['mint'](1); await c['scan']()
    second = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert second['task_id'], second['note']
    async with lab.factory() as db:
        task = await db.get(MintTask, second['task_id'])
        auth = await db.get(MintAuthorization, task.authorization_id)
        rule = await db.get(CopyRule, original['id'])
        assert auth.total_spend_cap_wei == auth.max_fee_wei == remaining
        assert rule.context_hash == original_hash
        assert rule.snapshot['total_cap_wei'] == 5 * 10**14
        assert rule.reserved_wei == remaining
    await settle(c, second['task_id'])
    async with lab.factory() as db:
        rule = await db.get(CopyRule, original['id'])
        assert rule.reserved_wei == 0 and rule.spent_wei < rule.budget_wei


async def test_private_journal_still_blocks_free_copy_when_api_spending_is_reset(copying):
    c = copying; lab = c['lab']; free_stage(lab, limit=1)
    c['request'].update(quantity=100, quantity_mode='max_free', free_only=True,
        price_cap_eth='0', fee_cap_eth='0.0005', budget_eth='0.0005')
    original = await c['approve']()
    await c['mint'](1); await c['scan']()
    first = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    await settle(c, first['task_id'])
    async with lab.factory() as db:
        (await db.get(CopyRule, original['id'])).spent_wei = 0
        await db.commit()
    next_free_stage(lab)
    await c['mint'](1); await c['scan']()
    second = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert second['task_id']
    response = await lab.signer_client.post(f'/tasks/{second["task_id"]}/prepare')
    assert response.status_code == 409
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 1
    journal.close()


async def test_free_copy_narrows_to_shared_budget_after_another_network_reservation(wallet_networks):
    c, request = wallet_networks; lab = c['lab']; free_stage(lab, limit=1)
    request.update(quantity=100, quantity_mode='max_free', free_only=True,
        price_cap_eth='0', fee_cap_eth='0.001', budget_eth='0.001')
    result = await approve_group(c, request)
    other = next(r for r in result['rules'] if r['chain_id'] == 1)
    async with lab.factory() as db:
        (await db.get(CopyRule, other['id'])).reserved_wei = 6 * 10**14
        await db.commit()
    await c['mint'](1); await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['task_id'], event['note']
    async with lab.factory() as db:
        task = await db.get(MintTask, event['task_id'])
        auth = await db.get(MintAuthorization, task.authorization_id)
        assert auth.total_spend_cap_wei == auth.max_fee_wei == 4 * 10**14
    await lab.sign(event['task_id'])


async def test_changed_wallet_stays_unsigned_and_explains_required_approval(copying, monkeypatch):
    c = copying; lab = c['lab']
    await c['approve'](); await c['mint'](1); await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    lab.w.provider.make_request('hardhat_setCode', [lab.owner.address, '0xef0100' + '22' * 20])
    await lab.due(); await lab.tick()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['status'] == 'failed'
    assert event['note'] == WalletApprovalChanged.message
    async with lab.factory() as db:
        task = await db.get(MintTask, event['task_id'])
        assert task.signed_tx_raw is None and task.transaction_hash is None
        diagnostic = await db.scalar(select(MintAttemptDiagnostic).where(
            MintAttemptDiagnostic.task_id == task.id))
        assert diagnostic.error_category == 'wallet_approval_changed'
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 0
    journal.close()
    from app import automatic_notifications
    from app.services.notifier import NotificationService
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(automatic_notifications, 'AsyncSessionLocal', lab.factory)
    monkeypatch.setattr(NotificationService, 'send_notification', send)
    await automatic_notifications.deliver_one()
    assert send.await_args.args[:2] == ('Copy mint skipped', WalletApprovalChanged.message)


async def test_watching_without_approval_explains_that_no_copy_was_requested(copying):
    c = copying; await c['mint'](1); await c['scan']()
    event = (await c['lab'].client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['status'] == 'detected' and event['task_id'] is None
    assert event['last_error_category'] == 'copy_not_enabled'
    assert 'Watching only' in event['note'] and 'Manage' in event['note']


@pytest.mark.parametrize('chain,confirmations,expected_head', [(1,2,999), (1,13,988), (1,1,999), (4663,2,999)])
async def test_source_confirmation_setting_changes_scan_horizon_without_allowing_one_confirmation(monkeypatch, chain, confirmations, expected_head):
    class Eth:
        @property
        async def block_number(self): return 1000
        get_logs = AsyncMock(return_value=[])
        get_block = AsyncMock(return_value=SimpleNamespace(hash=b'x'))
    web3 = SimpleNamespace(eth=Eth(), provider=SimpleNamespace(disconnect=AsyncMock()))
    monkeypatch.setattr(settings, 'COPY_ETHEREUM_SOURCE_CONFIRMATIONS', confirmations)
    monkeypatch.setattr(automatic, 'provider_for', AsyncMock(return_value=web3))
    watch = SimpleNamespace(cursors={str(chain): {'block':980}}, address='0x'+'11'*20)
    cursor, observations = await copy_mints.discover_watch(watch, chain)
    assert cursor['block'] == expected_head and observations == []
    assert web3.eth.get_logs.call_args.args[0]['toBlock'] == expected_head
    web3.provider.disconnect.assert_awaited_once()


def test_reason_headers_are_allowlisted_and_persist_specific_wallet_failures():
    for reason, expected in [('wallet_approval_changed','wallet_approval_changed'),
                             ('private-wallet-secret','signer_validation_rejected')]:
        request = httpx.Request('POST','http://signer/tasks/example/prepare')
        response = httpx.Response(409, headers={'X-Mintly-Reason':reason}, request=request)
        error = httpx.HTTPStatusError('rejected', request=request, response=response)
        assert mint_diagnostics.category([],409,error) == expected


def test_old_generic_failure_is_explained_without_claiming_a_specific_cause():
    old = 'Independent signer rejected task policy, identity, budget or chain readiness.'
    note = mint_diagnostics.public_note(old)
    assert 'No transaction was sent' in note and 'Wallet' in note
    assert note != WalletApprovalChanged.message
    assert mint_diagnostics.public_note('Not enough ETH on Robinhood for gas.') == 'Not enough ETH on Robinhood for gas.'


async def test_free_task_cannot_increase_independently_approved_gas_ceiling(copying):
    c = copying; lab = c['lab']; free_stage(lab)
    c['request'].update(free_only=True, price_cap_eth='0')
    await c['approve'](); await c['mint'](1); await c['scan']()
    event = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    async with lab.factory() as db:
        task = await db.get(MintTask, event['task_id'])
        auth = await db.get(MintAuthorization, task.authorization_id)
        ceiling = auth.max_fee_wei + 1
        auth.max_fee_wei = auth.total_spend_cap_wei = ceiling
        auth.snapshot = {**auth.snapshot,'fee_cap_wei':ceiling,'total_cap_wei':ceiling}
        await db.commit()
    response = await lab.signer_client.post(f'/tasks/{event["task_id"]}/prepare')
    assert response.status_code == 409
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 0
    journal.close()
