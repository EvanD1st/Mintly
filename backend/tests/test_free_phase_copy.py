"""Real SeaDrop cross-phase execution, immutable consent and collection guards."""
from datetime import datetime, timezone
from app.models import CopyEvent, MintTask, MintAuthorization
from app.services.custody import CustodyVault
from test_copy_presales import presale
from test_copy_mints import copying
from test_automatic_evm import lab


async def setup(presale, monkeypatch, *, future=False, opt_in=True, paid=False):
    c, state, configure, mint_source = presale
    lab = c['lab']
    state.kind, state.own_price, state.own_index = 'signed', 5 if paid else 0, 8
    state.own_start = lab.start + (120 if future else 0)
    if future: state.source_end = lab.start + 60
    configure()
    async def schedule(self, slug):
        return {'stages': [{'uuid': 'free-fcfs', 'label': 'Free FCFS', 'stage_type': 'signed_presale',
            'start_time': datetime.fromtimestamp(state.own_start, timezone.utc).isoformat(),
            'end_time': datetime.fromtimestamp(lab.end, timezone.utc).isoformat(),
            'price': '0', 'max_per_wallet': 7, 'price_currency_address': '0x' + '0' * 40}]}
    monkeypatch.setattr('app.services.opensea.OpenSeaClient.get_drop', schedule)
    c['request'].update(free_only=True, quantity=100, quantity_mode='max_free', price_cap_eth='0',
        any_eligible_free_phase=opt_in)
    await c['approve'](); await mint_source()
    return c, state


async def event(c):
    return (await c['lab'].client.get('/api/copy-mints/activity')).json()['events'][0]


async def test_different_free_phase_mints_with_receiving_signature_and_original_source(presale, monkeypatch):
    c, _ = await setup(presale, monkeypatch)
    lab = c['lab']; await c['scan'](); e = await event(c)
    assert e['task_id'], e['note']
    async with lab.factory() as db:
        auth = await db.get(MintAuthorization, (await db.get(MintTask, e['task_id'])).authorization_id)
        assert auth.snapshot['onchain_stage_index'] == 8
        assert auth.snapshot['copy_source']['onchain_stage_index'] == 7
        assert auth.snapshot['copy_any_free_phase'] is True
        assert auth.snapshot['price_wei'] == 0 and auth.quantity == 7
    await lab.sign(e['task_id']); await lab.due(); await lab.tick()
    lab.w.provider.make_request('evm_mine', [])
    await lab.due(); await lab.tick()
    assert (await event(c))['status'] == 'confirmed'
    assert lab.nft.functions.totalSupply().call() == 8


async def test_future_free_phase_waits_then_mints(presale, monkeypatch):
    c, state = await setup(presale, monkeypatch, future=True)
    lab = c['lab']; await c['scan'](); e = await event(c)
    assert e['task_id'] is None and e['status'] == 'detected'
    assert 'Eligibility will be checked when it opens' in e['note']
    assert e['phase_plan']['phase'] == 'Free FCFS' and state.calls == []
    journal = CustodyVault().journal()
    assert journal.execute('SELECT count(*) FROM signed').fetchone()[0] == 0
    journal.close()
    lab.w.provider.make_request('evm_setNextBlockTimestamp', [state.own_start])
    lab.w.provider.make_request('evm_mine', [])
    async with lab.factory() as db:
        row = await db.get(CopyEvent, e['id']); row.next_attempt_at = None
        await db.commit()
    await c['scan'](); e = await event(c)
    assert e['task_id'], e['note']
    await lab.sign(e['task_id'])


async def test_legacy_approval_never_switches_phases(presale, monkeypatch):
    c, _ = await setup(presale, monkeypatch, opt_in=False)
    await c['scan'](); e = await event(c)
    assert e['task_id'] is None and 'fallback is disabled' in e['note']


async def test_paid_instructions_cannot_be_used_for_free_fallback(presale, monkeypatch):
    c, _ = await setup(presale, monkeypatch, paid=True)
    await c['scan'](); e = await event(c)
    assert e['task_id'] is None and 'Paid fallback is disabled' in e['note']


async def test_external_mint_stops_collection_copy(presale, monkeypatch):
    c, _ = await setup(presale, monkeypatch)
    await c['mint'](1, watched=c['lab'].owner)
    await c['scan'](); e = await event(c)
    assert e['task_id'] is None and 'Already minted 1' in e['note']


async def test_signer_rejects_scope_tampering_before_signing(presale, monkeypatch):
    c, _ = await setup(presale, monkeypatch)
    lab = c['lab']; await c['scan'](); e = await event(c)
    async with lab.factory() as db:
        task = await db.get(MintTask, e['task_id'])
        auth = await db.get(MintAuthorization, task.authorization_id)
        auth.snapshot = {k: v for k, v in auth.snapshot.items() if k != 'copy_any_free_phase'}
        await db.commit()
    response = await lab.signer_client.post(f'/tasks/{e["task_id"]}/prepare')
    assert response.status_code == 409
    journal = CustodyVault().journal()
    assert journal.execute('SELECT count(*) FROM signed').fetchone()[0] == 0
    journal.close()


async def test_invalid_opt_in_and_account_scoped_notice(presale):
    c, _, _, _ = presale
    request = {**c['request'], 'any_eligible_free_phase': True}
    client = c['lab'].client
    response = await client.post(f'/api/copy-mints/watches/{c["watch_id"]}/rules', json=request)
    assert response.status_code == 422
    assert (await client.get('/api/copy-mints/update-notice')).json()['show'] is True
    assert (await client.post('/api/copy-mints/update-notice/seen')).status_code == 200
    assert (await client.get('/api/copy-mints/update-notice')).json()['show'] is False


async def test_signer_rechecks_external_mint_after_copy_was_armed(presale, monkeypatch):
    c, _ = await setup(presale, monkeypatch)
    lab = c['lab']; await c['scan'](); e = await event(c)
    assert e['task_id']
    await c['mint'](1, watched=lab.owner)
    response = await lab.signer_client.post(f'/tasks/{e["task_id"]}/prepare')
    assert response.status_code == 409 and 'Already minted' in response.text
    journal = CustodyVault().journal()
    assert journal.execute('SELECT count(*) FROM signed').fetchone()[0] == 0
    journal.close()


async def test_journal_blocks_hidden_regular_mint_before_cross_phase_copy(presale, monkeypatch):
    from app.services import automatic
    c, _ = await setup(presale, monkeypatch)
    lab = c['lab']
    armed = await lab.client.post('/api/tasks/arm', json=lab.request)
    assert armed.status_code == 200, armed.text
    tid = armed.json()['id']; await lab.sign(tid)
    async with lab.factory() as db:
        task = await db.get(MintTask, tid)
        await automatic.release_reservation(db, task)
        task.status = 'failed'; task.signed_tx_raw = task.transaction_hash = None
        await db.commit()
    await c['scan'](); e = await event(c)
    assert e['task_id'], e['note']
    response = await lab.signer_client.post(f'/tasks/{e["task_id"]}/prepare')
    assert response.status_code == 409 and 'already signed' in response.text
    journal = CustodyVault().journal()
    assert journal.execute('SELECT count(*) FROM signed').fetchone()[0] == 1
    journal.close()


async def test_paused_future_signal_never_mints_on_resuming(presale, monkeypatch):
    c, state = await setup(presale, monkeypatch, future=True)
    lab = c['lab']; await c['scan'](); e = await event(c)
    response = await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/pause', json={'paused': True})
    assert response.status_code == 200
    assert (await event(c))['status'] == 'skipped'
    lab.w.provider.make_request('evm_setNextBlockTimestamp', [state.own_start])
    lab.w.provider.make_request('evm_mine', [])
    response = await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/pause', json={'paused': False})
    assert response.status_code == 200
    await c['scan']()
    assert (await event(c))['task_id'] is None
