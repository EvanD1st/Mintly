"""Receiving-wallet allowlist/signed proof, one-time opt-in and no public double copy."""
import json
import uuid
from types import SimpleNamespace
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_abi import encode
from eth_utils import keccak
from sqlalchemy import select
import pytest
from app.models import CopyWatch, CopyRule, CopyEvent, MintTask, MintAuthorization
from app.services import automatic, copy_mints
from app.services.custody import CustodyVault
from app.services.seadrop_mint import PARAM_TYPE, ALLOW_SELECTOR, SIGNED_SELECTOR, signed_mint_typed_data
from app.services.signer.base import SEADROP_V1_ADDRESS
from test_automatic_evm import lab
from test_copy_mints import copying


@pytest.fixture
async def presale(copying, monkeypatch):
    c = copying
    lab = c['lab']
    issuer = Account.create()
    state = SimpleNamespace(kind='allowlist', own_price=5, bad_proof=False, fallback=False, calls=[])
    source_params = (10, 5, lab.start, lab.end, 7, 50, 500, True)
    def own_params():
        return (state.own_price, 7, lab.start, lab.end, 7, 50, 500, True)
    def leaf(address, params):
        return keccak(encode(['address', PARAM_TYPE], [address, params]))
    def configure():
        a, b = leaf(c['source'].address, source_params), leaf(lab.owner.address, own_params())
        root = keccak(min(a,b) + max(a,b))
        bounds = (0, 20, lab.start, lab.end, 50, 500, 500)
        lab.w.eth.wait_for_transaction_receipt(lab.nft.functions.configure(root, lab.w.eth.accounts[1],
            issuer.address, bounds).transact({'from':lab.w.eth.accounts[0]}))
    configure()
    def transaction(address, quantity, source=False):
        params = source_params if source else own_params()
        fee = lab.w.eth.accounts[1]
        if state.kind == 'allowlist':
            sibling = leaf(lab.owner.address, own_params()) if source else leaf(c['source'].address, source_params)
            if not source and state.bad_proof:
                sibling = bytes(32)
            data = '0x' + ALLOW_SELECTOR + encode(['address','address','address','uint256',PARAM_TYPE,'bytes32[]'],
                [lab.nft.address, fee, address, quantity, params, [sibling]]).hex()
        else:
            salt = 17 if source else 29
            mint = dict(contract=lab.nft.address, wallet=address, fee=fee, params=params, salt=salt)
            signature = Account.sign_message(encode_typed_data(full_message=signed_mint_typed_data(mint,31337)),issuer.key).signature
            if not source and state.bad_proof:
                # Valid issuer signature for the followed address, not the receiving address.
                mint['wallet'] = c['source'].address
                signature = Account.sign_message(encode_typed_data(full_message=signed_mint_typed_data(mint,31337)),issuer.key).signature
            data = '0x' + SIGNED_SELECTOR + encode(['address','address','address','uint256',PARAM_TYPE,'uint256','bytes'],
                [lab.nft.address, fee, address, quantity, params, salt, signature]).hex()
        return {'to':SEADROP_V1_ADDRESS,'data':data,'value':str(params[0]*quantity),'chain':'local-test'}
    async def collection(self, chain, contract):
        assert chain == 31337 and contract.lower() == lab.nft.address.lower()
        return 'presale-copy'
    async def build(self, slug, address, quantity=1):
        state.calls.append((address.lower(), quantity))
        assert slug == 'presale-copy' and address.lower() == lab.owner.address.lower()
        if state.fallback:
            fee = lab.w.eth.accounts[1]
            data = lab.sea.functions.mintPublic(lab.nft.address, fee, address, quantity)._encode_transaction_data()
            return 200, dict(to=SEADROP_V1_ADDRESS,data=data,value=str(10*quantity),chain='local-test')
        return 200, transaction(address, quantity)
    monkeypatch.setattr('app.services.opensea.OpenSeaClient.collection_for_contract', collection)
    monkeypatch.setattr('app.services.opensea.OpenSeaClient.build_mint', build)
    async def mint_source():
        if lab.w.eth.get_block('latest').timestamp < lab.start:
            lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start])
        tx = transaction(c['source'].address, 1, source=True)
        receipt = lab.w.eth.wait_for_transaction_receipt(lab.w.eth.send_raw_transaction(c['source'].sign_transaction({
            'to':tx['to'],'data':tx['data'],'value':int(tx['value']),'chainId':31337,
            'nonce':lab.w.eth.get_transaction_count(c['source'].address),'gas':500000,'gasPrice':lab.w.eth.gas_price}).raw_transaction))
        assert receipt.status == 1
        for _ in range(12):
            lab.w.provider.make_request('evm_mine',[])
    c['request'].update(include_presales=True, budget_eth='0.002')
    return c, state, configure, mint_source


@pytest.mark.parametrize('kind', ['allowlist','signed'])
@pytest.mark.parametrize('free', [False,True])
async def test_opted_in_presale_copies_own_eligibility_price_and_maximum_then_blocks_public(presale, kind, free):
    c, state, configure, mint_source = presale
    lab = c['lab']
    state.kind = kind
    if free:
        state.own_price = 0
        configure()
        c['request'].update(free_only=True, quantity=100, quantity_mode='max_free', price_cap_eth='0', fee_cap_eth='0.001')
    # One wallet-level opt-in is saved for future settings visits.
    request = {k:v for k,v in c['request'].items() if k != 'grant_id'}
    request['grant_ids'] = [lab.grant.id]
    response = await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/wallet-rules',json=request)
    assert response.status_code == 200 and response.json()['status'] == 'active', response.text
    async with lab.factory() as db:
        assert (await db.get(CopyWatch,c['watch_id'])).preferences['presale_wallets'][lab.wallet.id] is True
    await mint_source()
    await c['scan']()
    activity = (await lab.client.get('/api/copy-mints/activity')).json()
    event = activity['events'][0]
    assert event['task_id'], event['note']
    tid = event['task_id']
    async with lab.factory() as db:
        auth = await db.get(MintAuthorization,(await db.get(MintTask,tid)).authorization_id)
        assert auth.snapshot['mint_kind'] == kind and auth.snapshot['price_wei'] == state.own_price
        assert auth.snapshot['onchain_stage_index'] == 7
        assert auth.quantity == (7 if free else 1)
    assert all(address == lab.owner.address.lower() for address, _ in state.calls)
    await lab.sign(tid)
    await lab.due()
    await lab.tick()
    lab.w.provider.make_request('evm_mine',[])
    await lab.due()
    await lab.tick()
    assert (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]['status'] == 'confirmed'
    assert lab.nft.functions.totalSupply().call() == (8 if free else 2)
    await c['mint'](1)
    await c['scan']()
    events = (await lab.client.get('/api/copy-mints/activity')).json()['events']
    public = next(e for e in events if e['observation'].get('mint_kind','public') == 'public')
    assert public['task_id'] is None and 'Public mint skipped' in public['note']
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 1
    journal.close()


@pytest.mark.parametrize('kind', ['allowlist','signed'])
async def test_foreign_proof_or_signature_never_authorizes_receiving_wallet(presale, kind):
    c, state, _, mint_source = presale
    state.kind, state.bad_proof = kind, True
    await c['approve']()
    await mint_source()
    await c['scan']()
    event = (await c['lab'].client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['task_id'] is None and event['status'] == 'skipped'
    assert 'could not be verified' in event['note']
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 0
    journal.close()


async def test_old_public_only_consent_detects_but_never_copies_a_whitelist_stage(presale):
    c, _, _, mint_source = presale
    c['request'].pop('include_presales')
    await c['approve']()
    await mint_source()
    await c['scan']()
    event = (await c['lab'].client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['observation']['mint_kind'] == 'allowlist' and event['task_id'] is None
    assert event['note'] == 'Whitelist copying is off. Enable it in Copy settings.'


async def test_provider_public_fallback_is_rejected_for_whitelist_signal(presale):
    c, state, _, mint_source = presale
    state.fallback = True
    await c['approve']()
    await mint_source()
    await c['scan']()
    event = (await c['lab'].client.get('/api/copy-mints/activity')).json()['events'][0]
    assert event['task_id'] is None and 'Public mint fallback is disabled' in event['note']


async def test_independent_journal_blocks_public_when_presale_task_signature_is_hidden(presale):
    c, _, _, mint_source = presale
    lab = c['lab']
    await c['approve']()
    await mint_source()
    await c['scan']()
    tid = (await lab.client.get('/api/copy-mints/activity')).json()['events'][0]['task_id']
    await lab.sign(tid)
    async with lab.factory() as db:
        task = await db.get(MintTask,tid)
        await automatic.release_reservation(db,task)
        task.signed_tx_raw = task.transaction_hash = None
        task.status = 'failed'
        await db.commit()
    await c['mint'](1)
    await c['scan']()
    public = next(e for e in (await lab.client.get('/api/copy-mints/activity')).json()['events']
        if e['observation'].get('mint_kind','public') == 'public')
    assert public['task_id'], public['note']
    response = await lab.signer_client.post(f'/tasks/{public["task_id"]}/prepare')
    assert response.status_code == 409 and 'Whitelist copy already signed' in response.text
    journal = CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0] == 1
    journal.close()
