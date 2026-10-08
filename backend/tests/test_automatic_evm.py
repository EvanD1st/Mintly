"""Authenticated arming -> isolated signer -> scheduler -> real SeaDrop receipts.

Only the upstream presale data provider is replaced. Signing and EVM execution are real.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import urlparse
import uuid

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_abi import encode
from eth_utils import keccak
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from web3 import Web3

from app.config import settings
from app.api.deps import get_db
from app.main import app
from app.models import User, Wallet, Drop, MintStage, AutomaticGrant, MintTask, MintAuthorization, AutomaticNonce
from app.automatic_worker import step
from app.services import automatic
from app.services.custody import private_write
from app.services.seadrop_mint import PARAM_TYPE, ALLOW_SELECTOR, SIGNED_SELECTOR, signed_mint_typed_data
from app.services.signer.base import SEADROP_V1_ADDRESS
from app.models import MintRecovery
from app.services.custody import CustodyVault
from app.services.custody_recovery import recover_task


@pytest.fixture
def recovery_clock(lab, monkeypatch):
    # EVM time is deliberately advanced by local stage/reorg tests. Snapshot
    # restoration does not restore Hardhat's wall-clock offset; align the test
    # consent clock with chain time without relaxing production expiry checks.
    class ChainClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(max(int(datetime.now(timezone.utc).timestamp()),
                lab.w.eth.get_block('latest').timestamp), tz)
    monkeypatch.setattr('app.services.custody_recovery.datetime', ChainClock)


async def unresolved(lab):
    response = await lab.client.post('/api/tasks/arm', json={**lab.request,
        'expires_at': datetime.fromtimestamp(lab.start + 30, timezone.utc).isoformat()})
    assert response.status_code == 200, response.text
    task_id = response.json()['id']
    lab.w.provider.make_request('evm_setNextBlockTimestamp', [lab.start])
    lab.w.provider.make_request('evm_mine', [])
    await lab.sign(task_id)
    lab.w.provider.make_request('evm_setNextBlockTimestamp', [lab.start + 45])
    lab.w.provider.make_request('evm_mine', [])  # original finite submission authorization is now expired
    async with lab.factory() as db:
        task = await db.get(MintTask, task_id)
        task.status, task.broadcast_attempts = 'uncertain', 4
        previous = (task.transaction_hash, task.signed_tx_raw, task.assigned_nonce, task.expires_at_utc)
        await db.commit()
    return task_id, previous


@pytest.mark.parametrize('winner', ['replacement', 'original', 'replacement_reverted'])
async def test_recovery_mints_once_same_nonce_and_reconciles_either_hash(lab, winner, recovery_clock):
    task_id, previous = await unresolved(lab)
    expiry = datetime.fromtimestamp(lab.end, timezone.utc)
    async with lab.factory() as db:
        result = await recover_task(db, task_id, lab.user.id, expiry, 'explicit-local-owner-consent')
        retry = await recover_task(db, task_id, lab.user.id, expiry, 'explicit-local-owner-consent')
        assert retry['hash'] == result['hash'] and result['hash'] != previous[0]
        task = await db.get(MintTask, task_id)
        assert task.assigned_nonce == previous[2] and task.broadcast_attempts == 4
        assert task.expires_at_utc == previous[3]
        assert Account.recover_transaction(task.signed_tx_raw) == lab.owner.address
        from eth_account._utils.legacy_transactions import Transaction
        replacement = Transaction.from_bytes(bytes.fromhex(task.signed_tx_raw[2:]))
        old = Transaction.from_bytes(bytes.fromhex(previous[1][2:]))
        assert (replacement.nonce, replacement.to, replacement.data, replacement.value) == (old.nonce, old.to, old.data, old.value)
        assert replacement.gasPrice > old.gasPrice
        assert replacement.gas * replacement.gasPrice <= (await db.get(MintAuthorization, task.authorization_id)).max_fee_wei
        assert (await db.get(AutomaticGrant, lab.grant.id)).reserved_wei == 500000000000020
    journal = CustodyVault().journal()
    assert journal.execute('SELECT count(*) FROM signed').fetchone()[0] == 1
    assert journal.execute('SELECT count(*) FROM recoveries').fetchone()[0] == 1
    journal.close()
    if winner == 'original':
        lab.w.eth.send_raw_transaction(previous[1])
    elif winner == 'replacement_reverted':
        # Price changes after signing; chain reverts the saved mint without a second attempt.
        lab.w.provider.make_request('hardhat_impersonateAccount', [lab.nft.address])
        lab.sea.functions.updatePublicDrop((11, lab.start, lab.end, 20, 500, True)).transact({'from': lab.nft.address})
        lab.w.provider.make_request('hardhat_stopImpersonatingAccount', [lab.nft.address])
    await lab.due(); await lab.tick()
    lab.w.provider.make_request('evm_mine', [])
    await lab.due(); await lab.tick()
    async with lab.factory() as db:
        task = await db.get(MintTask, task_id)
        recovery = await db.scalar(select(MintRecovery).where(MintRecovery.task_id == task_id))
        expected = 'reverted' if winner == 'replacement_reverted' else 'confirmed'
        assert task.status == expected, task.failure_reason
        assert recovery.status == ('superseded' if winner == 'original' else expected)
        assert task.transaction_hash == (previous[0] if winner == 'original' else result['hash'])
        assert (await db.get(AutomaticGrant, lab.grant.id)).reserved_wei == 0
    assert lab.nft.functions.totalSupply().call() == (0 if winner == 'replacement_reverted' else 2)
    if winner != 'replacement_reverted':
        assert lab.nft.functions.ownerOf(1).call() == lab.owner.address
    else:
        receipt = lab.w.eth.get_transaction_receipt(result['hash'])
        assert task.actual_total_cost_wei == receipt.gasUsed * receipt.effectiveGasPrice
        # Restore eligibility for the later distinct task, not a retry of this one.
        lab.w.provider.make_request('hardhat_impersonateAccount', [lab.nft.address])
        lab.sea.functions.updatePublicDrop((10, lab.start, lab.end, 20, 500, True)).transact({'from': lab.nft.address})
        lab.w.provider.make_request('hardhat_stopImpersonatingAccount', [lab.nft.address])
    history = (await lab.client.get('/api/history?section=mints')).json()['records'][0]
    assert history['recoveries'][0]['previous_hash'] == previous[0]
    assert history['recoveries'][0]['replacement_hash'] == result['hash']
    assert 'signed_tx_raw' not in json.dumps(history) and previous[1] not in json.dumps(history)
    # A later task settles the single independent liability against either winner.
    other = await lab.client.post('/api/tasks/arm', json={**lab.request, 'idempotency_key': 'later-fresh-task'})
    assert other.status_code == 200, other.text
    await lab.sign(other.json()['id'])
    journal = CustodyVault().journal()
    actual = journal.execute('SELECT actual FROM signed WHERE task=?', (task_id,)).fetchone()[0]
    assert actual == history['actual_total_cost_wei']
    journal.close()


async def test_recovery_journal_reuses_signature_after_database_commit_loss(lab, monkeypatch, recovery_clock):
    task_id, previous = await unresolved(lab)
    expiry = datetime.fromtimestamp(lab.end, timezone.utc)
    async with lab.factory() as db:
        real_commit = db.commit
        count = 0
        async def fail_activation():
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError('simulated crash after journal fsync')
            await real_commit()
        monkeypatch.setattr(db, 'commit', fail_activation)
        with pytest.raises(RuntimeError):
            await recover_task(db, task_id, lab.user.id, expiry, 'crash-proof-owner-consent')
        await db.rollback()
    journal = CustodyVault().journal()
    saved = dict(journal.execute('SELECT * FROM recoveries').fetchone())
    journal.close()
    async with lab.factory() as db:
        result = await recover_task(db, task_id, lab.user.id, expiry, 'crash-proof-owner-consent')
        assert result['hash'] == saved['hash'] and result['nonce'] == previous[2]
        assert (await db.get(MintTask, task_id)).signed_tx_raw == saved['raw']


@pytest.mark.parametrize('invalid', ['owner', 'expired', 'fee_cap', 'consumed_nonce', 'expensive_gas'])
async def test_recovery_rejects_unapproved_or_unaffordable_scope_without_signing(lab, invalid, monkeypatch, recovery_clock):
    task_id, _ = await unresolved(lab)
    expiry = datetime.fromtimestamp(lab.end, timezone.utc)
    owner = lab.user.id
    if invalid == 'owner': owner = str(uuid.uuid4())
    if invalid == 'expired': expiry = datetime.now(timezone.utc) - timedelta(seconds=1)
    if invalid == 'fee_cap':
        async with lab.factory() as db:
            task = await db.get(MintTask, task_id)
            (await db.get(MintAuthorization, task.authorization_id)).max_fee_wei = 1
            await db.commit()
    if invalid == 'consumed_nonce':
        lab.w.provider.make_request('hardhat_setNonce', [lab.owner.address, '0x1'])
    if invalid == 'expensive_gas':
        async def expensive(*args): return 1000000, 10**12
        monkeypatch.setattr('app.services.custody_recovery.quote_gas', expensive)
    async with lab.factory() as db:
        with pytest.raises(ValueError):
            await recover_task(db, task_id, owner, expiry, 'rejected-consent')
    journal = CustodyVault().journal()
    assert journal.execute('SELECT count(*) FROM recoveries').fetchone()[0] == 0
    journal.close()


async def test_recovery_retries_are_finite_and_never_extend_original_consent(lab, monkeypatch, recovery_clock):
    task_id, previous = await unresolved(lab)
    expiry = datetime.fromtimestamp(lab.end, timezone.utc)
    async with lab.factory() as db:
        await recover_task(db, task_id, lab.user.id, expiry, 'finite-recovery-owner-consent')
    real_provider = automatic.provider
    attempted = []
    async def rejecting_provider():
        web3 = await real_provider()
        async def reject(raw):
            attempted.append(bytes(raw))
            raise RuntimeError('simulated RPC rejection')
        web3.eth.send_raw_transaction = reject
        return web3
    monkeypatch.setattr(automatic, 'provider', rejecting_provider)
    for _ in range(4):
        await lab.due(); await lab.tick()
    assert len(attempted) == 2 and attempted[0] == attempted[1]
    async with lab.factory() as db:
        task = await db.get(MintTask, task_id)
        assert task.status == 'uncertain' and task.broadcast_attempts == 6
        assert task.expires_at_utc == previous[3] and task.assigned_nonce == previous[2]
        assert (await db.get(AutomaticGrant, lab.grant.id)).reserved_wei == 500000000000020


@pytest.fixture
async def lab(test_db, monkeypatch, tmp_path):
    rpc = os.environ.get('MINTLY_TEST_RPC')
    if not rpc:
        pytest.skip('MINTLY_TEST_RPC is required for real local execution')
    assert urlparse(rpc).hostname in ('127.0.0.1','localhost')
    w = Web3(Web3.HTTPProvider(rpc)); assert w.eth.chain_id == 31337
    checkpoint = w.provider.make_request('evm_snapshot', [])
    assert 'result' in checkpoint, checkpoint
    artifacts = json.loads((Path(__file__).parent/'fixtures/seadrop-presale.json').read_text())['contracts']
    funding, fee = w.eth.accounts[:2]
    def deploy(name, *args):
        spec = artifacts[name]
        r = w.eth.wait_for_transaction_receipt(w.eth.contract(abi=spec['abi'], bytecode=spec['bytecode']).constructor(*args).transact({'from':funding}))
        assert r.status == 1
        return w.eth.contract(address=r.contractAddress, abi=spec['abi'])
    real = deploy('SeaDrop')
    def domain(address):
        return keccak(encode(['bytes32','bytes32','bytes32','uint256','address'], [keccak(text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)'),keccak(text='SeaDrop'),keccak(text='1.0'),31337,address])).hex()
    code = w.eth.get_code(real.address).hex().replace(domain(real.address),domain(SEADROP_V1_ADDRESS))
    w.provider.make_request('hardhat_setCode', [SEADROP_V1_ADDRESS, '0x'+code])
    w.provider.make_request('hardhat_setStorageAt', [SEADROP_V1_ADDRESS, '0x0', '0x'+(1).to_bytes(32,'big').hex()])
    sea = w.eth.contract(address=SEADROP_V1_ADDRESS, abi=artifacts['SeaDrop']['abi'])
    nft = deploy('PresaleTestNFT', SEADROP_V1_ADDRESS)
    owner, presale_signer = Account.create(), Account.create()
    w.provider.make_request('hardhat_setBalance', [owner.address, hex(10**18)])
    now = max(int(datetime.now(timezone.utc).timestamp()), w.eth.get_block('latest').timestamp)
    start, end = now+120, now+900
    params = (10, 20, start, end, 1, 100, 500, True)
    leaf = keccak(encode(['address',PARAM_TYPE],[owner.address,params]))
    bounds = (10,20,start,end,100,500,500)
    w.eth.wait_for_transaction_receipt(nft.functions.configure(leaf,fee,presale_signer.address,bounds).transact({'from':funding}))
    # Test-only impersonation configures the real public drop through the NFT address.
    w.provider.make_request('hardhat_impersonateAccount',[nft.address])
    w.provider.make_request('hardhat_setBalance',[nft.address,hex(10**18)])
    w.eth.wait_for_transaction_receipt(sea.functions.updatePublicDrop((10,start,end,20,500,True)).transact({'from':nft.address}))
    w.provider.make_request('hardhat_stopImpersonatingAccount',[nft.address])
    user = (await test_db.execute(select(User).where(User.username=='member'))).scalar_one()
    wallet = Wallet(id=str(uuid.uuid4()),user_id=user.id,address=owner.address,label='Imported test wallet',signing_capability='custodial',is_demo=False)
    drop = Drop(id=str(uuid.uuid4()),name='Real SeaDrop local test',chain='Local EVM',chain_id=31337,
        contract_address=nft.address,mint_page_url='https://opensea.io/collection/local-test',is_supported_integration=True,is_demo=False)
    stage = MintStage(id=str(uuid.uuid4()),drop_id=drop.id,stage_name='Exact selected stage',
        start_time_utc=datetime.fromtimestamp(start,timezone.utc),end_time_utc=datetime.fromtimestamp(end,timezone.utc),
        price_wei=10,price_eth_str='0.00000000000000001',limit_per_wallet=20)
    key_id, grant_id = str(uuid.uuid4()), str(uuid.uuid4())
    password = secrets.token_urlsafe(40)
    private_write(tmp_path/'password', password)
    private_write(tmp_path/'token', secrets.token_urlsafe(40))
    # Cheap KDF only for fresh ephemeral test keys; production provisioning pins 262144.
    private_write(tmp_path/f'{key_id}.keystore.json', json.dumps(Account.encrypt(owner.key,password,kdf='scrypt',iterations=1024)))
    policy = dict(grant_id=grant_id,key_id=key_id,user_id=user.id,wallet_id=wallet.id,account=owner.address,
        chain_id=31337,contracts=[nft.address],mint_kinds=['public','allowlist','signed'],budget_wei=10**16,max_task_wei=10**15,expires_at=end)
    private_write(tmp_path/f'{grant_id}.policy.json',json.dumps(policy))
    grant = AutomaticGrant(id=grant_id,user_id=user.id,wallet_id=wallet.id,chain_id=31337,account=owner.address,
        context_hash=automatic.digest(policy),scope={k:policy[k] for k in ('contracts','mint_kinds','max_task_wei')},
        budget_wei=policy['budget_wei'],expires_at=datetime.fromtimestamp(end,timezone.utc),status='enabled')
    test_db.add_all([wallet,drop]); await test_db.flush()
    test_db.add_all([stage,grant]); await test_db.commit()
    for name,value in dict(ENABLE_CUSTODIAL_AUTOMATIC=True,AUTOMATIC_CHAIN_ID=31337,AUTOMATIC_RPC=rpc,
        CUSTODY_VAULT_DIR=str(tmp_path),CUSTODY_PASSWORD_FILE=str(tmp_path/'password'),CUSTODY_JOURNAL_FILE=str(tmp_path/'journal.sqlite'),
        AUTOMATIC_SIGNER_TOKEN_FILE=str(tmp_path/'token'),AUTOMATIC_CONFIRMATIONS=2).items():
        monkeypatch.setattr(settings,name,value)
    factory=async_sessionmaker(test_db.bind,expire_on_commit=False)
    async def dependency():
        async with factory() as db:
            try: yield db
            except Exception: await db.rollback(); raise
    app.dependency_overrides[get_db]=dependency
    from app.services.automatic_signer import app as signer_app
    signer_app.dependency_overrides[get_db]=dependency
    client=AsyncClient(transport=ASGITransport(app=app),base_url='http://test')
    login=await client.post('/api/auth/login',json={'username':'member','password':'Member test password 123'})
    client.headers['Authorization']='Bearer '+login.json()['token']
    signer_client=AsyncClient(transport=ASGITransport(app=signer_app),base_url='http://signer',
        headers={'Authorization':'Bearer '+(tmp_path/'token').read_text()})
    async def sign(task_id):
        r=await signer_client.post(f'/tasks/{task_id}/prepare');r.raise_for_status();return r.json()
    async def signer_ready(grant_id):
        r=await signer_client.get(f'/policies/{grant_id}/ready');r.raise_for_status()
    monkeypatch.setattr(automatic,'signer_ready',signer_ready)
    async def due():
        async with factory() as db:
            await db.execute(update(MintTask).values(next_attempt_at=None))
            await db.commit()
    async def tick(signing=sign):
        # Advance only the test clock with the EVM; immutable task timing is unchanged.
        return await step(factory, signing, now=datetime.fromtimestamp(w.eth.get_block('latest').timestamp, timezone.utc))
    async def build_mint(self,slug,address,quantity):
        kind=state.kind
        if kind=='allowlist':
            data='0x'+ALLOW_SELECTOR+encode(['address','address','address','uint256',PARAM_TYPE,'bytes32[]'],[nft.address,fee,address,quantity,params,[]]).hex()
        else:
            mint=dict(contract=nft.address,wallet=address,fee=fee,params=params,salt=17)
            sig=Account.sign_message(encode_typed_data(full_message=signed_mint_typed_data(mint,31337)),presale_signer.key).signature
            data='0x'+SIGNED_SELECTOR+encode(['address','address','address','uint256',PARAM_TYPE,'uint256','bytes'],[nft.address,fee,address,quantity,params,17,sig]).hex()
        return 200,dict(to=SEADROP_V1_ADDRESS,data=data,value=str(quantity*10),chain='local-test')
    monkeypatch.setattr('app.services.opensea.OpenSeaClient.build_mint',build_mint)
    monkeypatch.setitem(automatic.CHAINS,'local-test',(31337,'Local EVM'))
    state=SimpleNamespace(w=w,sea=sea,nft=nft,owner=owner,user=user,grant=grant,stage=stage,drop=drop,wallet=wallet,
        factory=factory,client=client,sign=sign,signer_client=signer_client,due=due,tick=tick,start=start,end=end,kind='public',tmp=tmp_path)
    state.request=dict(wallet_id=wallet.id,drop_id=drop.id,stage_id=stage.id,quantity=2,fee_cap_eth='0.0005',
        grant_id=grant.id,price_cap_eth='0.00000000000000001',total_cap_eth='0.00050000000000002',
        user_consent_confirmed=True,idempotency_key='test-intent-0001',mint_kind='public')
    yield state
    await client.aclose();await signer_client.aclose()
    app.dependency_overrides.pop(get_db,None);signer_app.dependency_overrides.pop(get_db,None)
    restored = w.provider.make_request('evm_revert', [checkpoint['result']])
    assert restored.get('result') is True, restored


@pytest.mark.parametrize('delegated',[False, True])
@pytest.mark.parametrize('kind',['public','allowlist','signed'])
async def test_future_api_mint_runs_unattended_with_real_receipt(lab,kind,delegated):
    if delegated:
        # Real type-4 authorization on local Prague EVM, followed by ordinary
        # owner-signed SeaDrop transactions. No impersonation of the owner.
        from app.services.custody_accounts import inspect_account
        delegate = lab.w.eth.accounts[4]
        # ERC721 receiver response for test-only delegate callbacks.
        receiver = '0x63150b7a0260e01b60005260206000f3'
        assert 'result' in lab.w.provider.make_request('hardhat_setCode', [delegate, receiver])
        authorization = lab.owner.sign_authorization({'chainId':31337, 'address':delegate,
            'nonce':lab.w.eth.get_transaction_count(lab.owner.address)})
        upgrade = lab.w.eth.send_transaction({'from':lab.w.eth.accounts[0], 'to':lab.w.eth.accounts[0],
            'type':4, 'authorizationList':[authorization], 'gas':100000})
        assert lab.w.eth.wait_for_transaction_receipt(upgrade).status == 1
        assert bytes(lab.w.eth.get_code(lab.owner.address)) == bytes.fromhex('ef0100'+delegate[2:])
        web3 = await automatic.provider()
        try:
            adapter = await inspect_account(web3, lab.owner.address, 'eip7702-direct')
        finally:
            await web3.provider.disconnect()
        path = lab.tmp / f'{lab.grant.id}.policy.json'
        policy = json.loads(path.read_text())
        policy['account_adapter'] = adapter
        path.write_text(json.dumps(policy))
        async with lab.factory() as db:
            (await db.get(AutomaticGrant, lab.grant.id)).context_hash = automatic.digest(policy)
            await db.commit()
    lab.kind=kind;lab.request['mint_kind']=kind
    preview=await lab.client.post('/api/tasks/draft',json=lab.request);assert preview.status_code==200,preview.text
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);assert armed.status_code==200,armed.text
    task_id=armed.json()['id']
    again=await lab.client.post('/api/tasks/arm',json=lab.request);assert again.json()['id']==task_id
    assert lab.nft.functions.totalSupply().call()==0
    assert await lab.tick() is False, 'Future task must wait without signing'
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.due()
    before=lab.w.eth.get_balance(lab.owner.address)
    # No client interactions from this point onward.
    await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert task.status=='prepared',task.failure_reason
        assert Account.recover_transaction(task.signed_tx_raw)==lab.owner.address
        tx_hash=task.transaction_hash
    await lab.due();await lab.tick()
    lab.w.provider.make_request('evm_mine',[])
    await lab.due();await lab.tick()
    receipt=lab.w.eth.get_transaction_receipt(tx_hash)
    assert receipt.status==1 and receipt['from']==lab.owner.address
    assert lab.nft.functions.ownerOf(1).call()==lab.owner.address
    assert lab.nft.functions.ownerOf(2).call()==lab.owner.address
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);grant=await db.get(AutomaticGrant,lab.grant.id)
        assert task.status=='confirmed',task.failure_reason
        assert before-lab.w.eth.get_balance(lab.owner.address)==task.actual_total_cost_wei
        assert grant.reserved_wei==0 and grant.spent_wei==task.actual_total_cost_wei
    assert await lab.tick() is False
    assert lab.nft.functions.totalSupply().call()==2


@pytest.fixture
async def importer(lab, monkeypatch):
    from app.custody_import import app as import_app
    monkeypatch.setattr(settings, 'ENABLE_CUSTODY_IMPORT', True)
    async def signer_relink_ready(address):
        response = await lab.signer_client.get(f'/accounts/{address}/relink-ready')
        assert response.status_code == 200
        if response.json() != {'ready': True}:
            from fastapi import HTTPException
            raise HTTPException(409, 'Independent signer has an unresolved signature.')
    monkeypatch.setattr('app.custody_import.signer_relink_ready', signer_relink_ready)
    async def dependency():
        async with lab.factory() as db:
            yield db
    import_app.dependency_overrides[get_db] = dependency
    client = AsyncClient(transport=ASGITransport(app=import_app), base_url='https://import',
        headers={'Authorization':lab.client.headers['Authorization']})
    request = dict(request_id=str(uuid.uuid4()),wallet_id=lab.wallet.id,
        private_key='0x'+lab.owner.key.hex(),password='Member test password 123',
        contract=lab.nft.address,budget_eth='0.001',max_task_eth='0.001',
        expires_at=datetime.fromtimestamp(lab.end,timezone.utc).isoformat(),consent=True)
    yield client, request
    await client.aclose()
    import_app.dependency_overrides.clear()


@pytest.mark.parametrize('automatic_collections', [False, True])
async def test_import_encrypts_and_runs_unattended_without_duplicate_allowance(lab, importer, automatic_collections):
    client, request = importer
    if automatic_collections:
        request.pop('contract')
        request['collection_scope'] = 'reviewed_mints'
    response = await client.post('/api/automatic/import', json=request)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert request['private_key'] not in response.text and request['password'] not in response.text
    grant_id = response.json()['id']
    unlink = await lab.client.delete('/api/wallets/'+str(uuid.uuid4()))
    assert unlink.status_code == 404
    keyfile = json.loads((lab.tmp/f'{grant_id}.keystore.json').read_text())
    assert keyfile['crypto']['kdfparams']['n'] == 262144
    assert Account.from_key(Account.decrypt(keyfile,(lab.tmp/'password').read_text())).address == lab.owner.address
    again = await client.post('/api/automatic/import', json=request)
    assert again.status_code == 200 and again.json()['id'] == grant_id
    assert (await client.post('/api/automatic/import', json={**request,'budget_eth':'0.002'})).status_code == 409
    armed = await lab.client.post('/api/tasks/arm',json={**lab.request,'grant_id':grant_id})
    assert armed.status_code == 200, armed.text
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.due();await lab.tick()
    await lab.due();await lab.tick()
    lab.w.provider.make_request('evm_mine',[])
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        task = await db.get(MintTask,armed.json()['id'])
        assert task.status == 'confirmed', task.failure_reason
    assert lab.nft.functions.ownerOf(1).call() == lab.owner.address


@pytest.mark.parametrize('failure',['wrong_key','wrong_password','other_wallet','consent','expired','malformed','oversized','empty_scope','mixed_scope','unknown_scope'])
async def test_import_rejects_invalid_input_without_echoing_secrets(lab, importer, failure):
    client, request = importer
    if failure == 'wrong_key': request['private_key'] = '0x'+Account.create().key.hex()
    if failure == 'wrong_password': request['password'] = 'not-the-password'
    if failure == 'other_wallet': request['wallet_id'] = str(uuid.uuid4())
    if failure == 'consent': request['consent'] = False
    if failure == 'expired': request['expires_at'] = '2020-01-01T00:00:00Z'
    if failure == 'malformed': request['budget_eth'] = {'secret':request['private_key']}
    if failure == 'oversized': request['private_key'] *= 100
    if failure == 'empty_scope': request.pop('contract')
    if failure == 'mixed_scope': request['collection_scope'] = 'reviewed_mints'
    if failure == 'unknown_scope':
        request.pop('contract'); request['collection_scope'] = 'all_transactions'
    response = await client.post('/api/automatic/import',json=request)
    assert response.status_code in (403,404,409,413,422), response.text
    assert request['private_key'] not in response.text and request['password'] not in response.text
    assert not (lab.tmp/f"{request['request_id']}.keystore.json").exists()


async def test_import_requires_session_and_rate_limits_password_attempts(lab, importer):
    client, request = importer
    response = await client.post('/api/automatic/import',json=request,headers={'Authorization':''})
    assert response.status_code == 401
    request['password'] = 'wrong-password'
    for _ in range(5):
        assert (await client.post('/api/automatic/import',json=request)).status_code == 403
    assert (await client.post('/api/automatic/import',json=request)).status_code == 429


async def test_import_rejects_other_owner_disabled_service_and_plaintext_production(lab, importer, monkeypatch):
    client, request = importer
    async with lab.factory() as db:
        admin = (await db.execute(select(User).where(User.username=='admin'))).scalar_one()
        other = Wallet(id=str(uuid.uuid4()), user_id=admin.id, address=lab.owner.address, label='Other owner')
        db.add(other); await db.commit()
    response = await client.post('/api/automatic/import', json={**request,'wallet_id':other.id})
    assert response.status_code == 404
    monkeypatch.setattr(settings,'ENABLE_CUSTODY_IMPORT',False)
    assert (await client.get('/api/automatic/import/config')).status_code == 409
    assert (await client.post('/api/automatic/import',json=request)).status_code == 409
    monkeypatch.setattr(settings,'APP_ENV','production')
    response = await client.post('http://import/api/automatic/import',json=request)
    assert response.status_code == 400
    assert request['private_key'] not in response.text


async def test_budgets_duplicate_arming_owner_binding_and_cancel(lab):
    request=lab.request
    armed=await lab.client.post('/api/tasks/arm',json=request);assert armed.status_code==200,armed.text
    changed=await lab.client.post('/api/tasks/arm',json={**request,'quantity':3});assert changed.status_code==409
    results=await asyncio.gather(*[lab.client.post('/api/tasks/arm',json=request) for _ in range(3)])
    assert all(r.json()['id']==armed.json()['id'] for r in results)
    unauthorized=AsyncClient(transport=ASGITransport(app=app),base_url='http://test')
    login=await unauthorized.post('/api/auth/login',json={'username':'admin','password':'Admin test password 123'})
    unauthorized.headers['Authorization']='Bearer '+login.json()['token']
    assert (await unauthorized.post('/api/tasks/arm',json=request)).status_code==404
    await unauthorized.aclose()
    assert (await lab.client.post('/api/tasks/'+armed.json()['id']+'/disarm')).status_code==200
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.due();assert await lab.tick() is False
    assert lab.nft.functions.totalSupply().call()==0
    async with lab.factory() as db:
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==0


async def test_crash_after_signing_and_accepted_then_timeout_never_re_mints(lab,monkeypatch):
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);assert armed.status_code==200,armed.text
    task_id=armed.json()['id']
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);original=(task.transaction_hash,task.assigned_nonce,task.signed_tx_raw)
    assert (await lab.client.post(f'/api/tasks/{task_id}/disarm')).status_code==409
    # New signer request / process restart retrieves the same journal record.
    await lab.sign(task_id)
    from web3.eth import AsyncEth
    send=AsyncEth.send_raw_transaction
    async def accepted_then_timeout(self, raw):
        await send(self,raw)
        raise TimeoutError('accepted but response lost')
    monkeypatch.setattr(AsyncEth,'send_raw_transaction',accepted_then_timeout)
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);grant=await db.get(AutomaticGrant,lab.grant.id)
        assert task.status=='uncertain' and grant.reserved_wei>0
        assert (task.transaction_hash,task.assigned_nonce,task.signed_tx_raw)==original
    lab.w.provider.make_request('evm_mine',[])
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        assert (await db.get(MintTask,task_id)).status=='confirmed'
    assert lab.nft.functions.totalSupply().call()==2


@pytest.mark.parametrize('failure',['funds','gas','revoked','expired','stage','proof','signer_binding'])
async def test_fail_closed_before_broadcast(lab, failure):
    if failure == 'proof':
        lab.kind = 'allowlist'; lab.request['mint_kind'] = 'allowlist'
    if failure == 'gas': lab.request['fee_cap_eth'] = '0.000000000000000001'
    armed = await lab.client.post('/api/tasks/arm', json=lab.request)
    assert armed.status_code == 200, armed.text
    task_id = armed.json()['id']
    if failure == 'funds': lab.w.provider.make_request('hardhat_setBalance',[lab.owner.address,'0x0'])
    if failure == 'proof':
        lab.w.eth.wait_for_transaction_receipt(lab.nft.functions.replaceRoot(bytes(32)).transact({'from':lab.w.eth.accounts[0]}))
    if failure == 'stage':
        lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
        lab.w.eth.wait_for_transaction_receipt(lab.sea.functions.updatePublicDrop((11,lab.start,lab.end,20,500,True)).transact({'from':lab.nft.address}))
        lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
    if failure == 'signer_binding':
        path = next(lab.tmp.glob('*.keystore.json'))
        path.write_text(json.dumps(Account.encrypt(Account.create().key,(lab.tmp/'password').read_text(),kdf='scrypt',iterations=1024)))
    if failure == 'revoked':
        result=await lab.client.post(f'/api/automatic/policies/{lab.grant.id}/disable');assert result.status_code==200
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.end+1 if failure=='expired' else lab.start])
    lab.w.provider.make_request('evm_mine',[])
    await lab.due(); await lab.tick()
    async with lab.factory() as db:
        task = await db.get(MintTask,task_id)
        assert task.status in ('failed','expired','disarmed'), (failure,task.status,task.failure_reason)
        assert task.transaction_hash is None
    assert lab.nft.functions.totalSupply().call()==0


async def test_simultaneous_distinct_tasks_reserve_one_wallet_nonce_each(lab):
    one=await lab.client.post('/api/tasks/arm',json=lab.request)
    two=await lab.client.post('/api/tasks/arm',json={**lab.request,'idempotency_key':'second-distinct-intent'})
    assert one.status_code==two.status_code==200
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    for _ in range(6):
        await lab.due()
        await asyncio.gather(lab.tick(),lab.tick())
        lab.w.provider.make_request('evm_mine',[])
    async with lab.factory() as db:
        tasks=(await db.execute(select(MintTask))).scalars().all()
        assert {t.assigned_nonce for t in tasks}=={0,1}
        assert all(t.status=='confirmed' for t in tasks)
    assert lab.nft.functions.totalSupply().call()==4


async def test_concurrent_budget_reservations_cannot_overspend(lab):
    async with lab.factory() as db:
        grant=await db.get(AutomaticGrant,lab.grant.id)
        grant.budget_wei=automatic.wei(lab.request['total_cap_eth'])
        path=lab.tmp/f'{grant.id}.policy.json'
        policy=json.loads(path.read_text());policy['budget_wei']=grant.budget_wei
        path.write_text(json.dumps(policy));grant.context_hash=automatic.digest(policy)
        await db.commit()
    results=await asyncio.gather(*[lab.client.post('/api/tasks/arm',json={**lab.request,'idempotency_key':f'budget-race-{i}'}) for i in range(3)])
    assert sorted(r.status_code for r in results)==[200,409,409]


async def test_real_separate_signer_process_recovers_without_key_in_worker(lab):
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);assert armed.status_code==200
    task_id=armed.json()['id']
    env={**os.environ, 'APP_ENV':'test', 'DEBUG':'false', 'DATABASE_URL':lab.factory.kw['bind'].url.render_as_string(hide_password=False),
        'ENABLE_CUSTODIAL_AUTOMATIC':'true','AUTOMATIC_CHAIN_ID':'31337','AUTOMATIC_RPC':settings.AUTOMATIC_RPC,
        'CUSTODY_VAULT_DIR':str(lab.tmp),'CUSTODY_PASSWORD_FILE':str(lab.tmp/'password'),
        'CUSTODY_JOURNAL_FILE':str(lab.tmp/'journal.sqlite'),'AUTOMATIC_SIGNER_TOKEN_FILE':str(lab.tmp/'token')}
    # No key value occurs in environment, arguments, HTTP request or API DB.
    assert all(lab.owner.key.hex() not in value for value in env.values())
    process=subprocess.Popen([sys.executable,'-m','uvicorn','app.services.automatic_signer:app','--host','127.0.0.1','--port','18767','--no-access-log'],
        env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        async with AsyncClient(base_url='http://127.0.0.1:18767',headers={'Authorization':'Bearer '+(lab.tmp/'token').read_text()}) as client:
            for _ in range(50):
                try:
                    r=await client.get('/readyz')
                    if r.status_code==200:break
                except Exception:pass
                await asyncio.sleep(.2)
            else:pytest.fail('Isolated signer process did not become ready')
            denied=await client.post(f'/tasks/{task_id}/prepare',headers={'Authorization':'Bearer invalid'})
            assert denied.status_code==401
            lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
            async def sign(task):
                r=await client.post(f'/tasks/{task}/prepare');r.raise_for_status();return r.json()
            await lab.due();await lab.tick(sign)
            await lab.due();await lab.tick(sign)
            lab.w.provider.make_request('evm_mine',[])
            await lab.due();await lab.tick(sign)
            assert lab.nft.functions.totalSupply().call()==2
    finally:
        process.terminate();process.wait(timeout=10)


async def test_review_hash_prevents_silent_metadata_changes(lab):
    preview=await lab.client.post('/api/tasks/draft',json=lab.request)
    assert preview.status_code==200,preview.text
    async with lab.factory() as db:
        stage=await db.get(MintStage,lab.stage.id)
        stage.stage_name='Changed stage description'
        await db.commit()
    result=await lab.client.post('/api/tasks/arm',json={**lab.request,'review_hash':preview.json()['review_hash']})
    assert result.status_code==409 and 'Review again' in result.text
    async with lab.factory() as db:
        assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==0


@pytest.mark.parametrize('mode',['free','reverted','reorg'])
async def test_real_receipt_accounting_and_unconfirmed_reorg(lab,mode):
    if mode=='free':
        lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
        lab.w.eth.wait_for_transaction_receipt(lab.sea.functions.updatePublicDrop((0,lab.start,lab.end,20,500,True)).transact({'from':lab.nft.address}))
        lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
        async with lab.factory() as db:
            stage=await db.get(MintStage,lab.stage.id);stage.price_wei=0;stage.price_eth_str='0'
            await db.commit()
        lab.request['price_cap_eth']='0'
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);assert armed.status_code==200,armed.text
    task_id=armed.json()['id']
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        original=(task.transaction_hash,task.assigned_nonce,task.signed_tx_raw)
    checkpoint=lab.w.provider.make_request('evm_snapshot',[])['result']
    if mode=='reverted':
        # Change the real contract after signing, so the saved transaction reverts.
        lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
        lab.w.eth.wait_for_transaction_receipt(lab.sea.functions.updatePublicDrop((11,lab.start,lab.end,20,500,True)).transact({'from':lab.nft.address}))
        lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
    before=lab.w.eth.get_balance(lab.owner.address)
    await lab.due();await lab.tick()
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert task.status=='submitted' and (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei>0
    if mode=='reorg':
        assert lab.w.provider.make_request('evm_revert',[checkpoint])['result'] is True
        assert lab.nft.functions.totalSupply().call()==0
        await lab.due();await lab.tick()  # same bytes recover the orphaned receipt
    lab.w.provider.make_request('evm_mine',[])
    await lab.due();await lab.tick()
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);grant=await db.get(AutomaticGrant,lab.grant.id)
        assert (task.transaction_hash,task.assigned_nonce,task.signed_tx_raw)==original
        assert task.status==('reverted' if mode=='reverted' else 'confirmed')
        assert task.actual_total_cost_wei==before-lab.w.eth.get_balance(lab.owner.address)>0
        if mode in ('free','reverted'):
            assert task.actual_total_cost_wei==task.actual_gas_used*task.actual_effective_gas_price
        assert grant.reserved_wei==0 and grant.spent_wei==task.actual_total_cost_wei
    assert lab.nft.functions.totalSupply().call()==(0 if mode=='reverted' else 2)


async def test_journal_recovers_signature_when_database_commit_was_lost(lab):
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);assert armed.status_code==200
    task_id=armed.json()['id']
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    await lab.sign(task_id)
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        original=(task.transaction_hash,task.signed_tx_raw,task.assigned_nonce)
        task.status='armed';task.signed_tx_raw=None;task.transaction_hash=None;task.assigned_nonce=None
        await db.delete(await db.get(AutomaticNonce,task_id));await db.commit()
    await lab.sign(task_id)
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert (task.transaction_hash,task.signed_tx_raw,task.assigned_nonce)==original
    await lab.due();await lab.tick()
    lab.w.provider.make_request('evm_mine',[])
    await lab.due();await lab.tick()
    assert lab.nft.functions.totalSupply().call()==2


async def test_cancellation_race_and_external_wallet_nonce(lab):
    # An ordinary wallet transaction consumes nonce 0 before Mintly starts.
    signed=lab.owner.sign_transaction(dict(to=lab.w.eth.accounts[0],value=1,nonce=0,gas=21000,gasPrice=lab.w.eth.gas_price,chainId=31337))
    lab.w.eth.wait_for_transaction_receipt(lab.w.eth.send_raw_transaction(signed.raw_transaction))
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);assert armed.status_code==200
    task_id=armed.json()['id']
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    cancel,sign=await asyncio.gather(lab.client.post(f'/api/tasks/{task_id}/disarm'),lab.signer_client.post(f'/tasks/{task_id}/prepare'))
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        if task.status=='disarmed':
            assert cancel.status_code==200 and sign.status_code==409 and task.signed_tx_raw is None
        else:
            assert cancel.status_code==409 and sign.status_code==200 and task.assigned_nonce==1


@pytest.mark.parametrize('tamper',['contract','chain','policy'])
async def test_independent_signer_rejects_database_tampering(lab,tamper):
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);assert armed.status_code==200
    task_id=armed.json()['id']
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);auth=await db.get(MintAuthorization,task.authorization_id)
        s=dict(auth.snapshot)
        if tamper=='contract': s['contract']=lab.w.eth.accounts[3]
        if tamper=='chain': s['chain_id']=1
        if tamper=='policy': (await db.get(AutomaticGrant,lab.grant.id)).budget_wei+=1
        auth.snapshot=s;await db.commit()
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[lab.start]);lab.w.provider.make_request('evm_mine',[])
    result=await lab.signer_client.post(f'/tasks/{task_id}/prepare')
    assert result.status_code==409
    async with lab.factory() as db:
        assert (await db.get(MintTask,task_id)).signed_tx_raw is None


async def test_notification_failures_and_concurrent_status_change_preserve_outbox(lab,monkeypatch):
    from app import automatic_notifications as notifications
    armed=await lab.client.post('/api/tasks/arm',json=lab.request);assert armed.status_code==200
    task_id=armed.json()['id']
    async with lab.factory() as db:
        (await db.get(MintTask,task_id)).notification_pending=True
        await db.commit()
    monkeypatch.setattr(notifications,'AsyncSessionLocal',lab.factory)
    calls=[]
    async def fail(*args,**kwargs):
        calls.append(kwargs['user_id']);raise RuntimeError('FCM unavailable')
    monkeypatch.setattr(notifications.NotificationService,'send_notification',fail)
    await notifications.deliver_one()
    async with lab.factory() as db:
        assert (await db.get(MintTask,task_id)).notification_pending
    async def concurrent_change(*args,**kwargs):
        async with lab.factory() as db:
            (await db.get(MintTask,task_id)).status='preparing';await db.commit()
        return True
    monkeypatch.setattr(notifications.NotificationService,'send_notification',concurrent_change)
    await notifications.deliver_one()
    async with lab.factory() as db:
        assert (await db.get(MintTask,task_id)).notification_pending
    async def success(*args,**kwargs):
        calls.append(kwargs['user_id']);return True
    monkeypatch.setattr(notifications.NotificationService,'send_notification',success)
    await notifications.deliver_one()
    async with lab.factory() as db:
        assert not (await db.get(MintTask,task_id)).notification_pending
    assert calls==[lab.user.id,lab.user.id]


async def plan_context(lab, monkeypatch):
    async with lab.factory() as db:
        wallet = await db.get(Wallet, lab.wallet.id)
        wallet.supported_chains = ['Local EVM']
        await db.commit()
    from app.models import MintPlan
    from app.services.opensea import OpenSeaClient
    detail = {'collection_slug': 'example', 'collection_name': 'Plan collection',
        'opensea_url': 'https://opensea.io/collection/example', 'chain': 'local-test',
        'contract_address': lab.nft.address, 'drop_type': 'seadrop_v1_erc721',
        'stages': [{'uuid': 'exact-public', 'stage_type': 'public_sale', 'label': 'Selected plan stage',
            'start_time': datetime.fromtimestamp(lab.start, timezone.utc).isoformat(),
            'end_time': datetime.fromtimestamp(lab.end, timezone.utc).isoformat(),
            'price': '10', 'max_per_wallet': '20', 'price_currency_address': '0x' + '0' * 40}]}
    async def get_drop(self, slug):
        assert slug == 'example'
        return detail
    async def quote():
        return '2500', datetime.now(timezone.utc)
    monkeypatch.setattr(OpenSeaClient, 'get_drop', get_drop)
    monkeypatch.setattr('app.services.mint_plans.eth_usdt_quote', quote)
    r = await lab.client.post('/api/mint-plans', json={'url': detail['opensea_url'],
        'wallet_id': lab.wallet.id, 'quantity': 2})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan['status'] == 'scheduled'
    r = await lab.client.post('/api/mint-plans/' + plan['id'] + '/automatic-context')
    assert r.status_code == 200, r.text
    context = r.json()
    assert context['plan']['quantity'] == 2
    assert context['drop']['contract_address'] == lab.nft.address
    request = {**lab.request, 'plan_id': plan['id'], 'drop_id': context['drop']['id'],
        'stage_id': context['drop']['stages'][0]['id']}
    r = await lab.client.post('/api/tasks/draft', json=request)
    assert r.status_code == 200, r.text
    request['review_hash'] = r.json()['review_hash']
    return plan, request


async def test_remove_plan_cancels_before_signing_preserves_owner_history_and_reimport(lab, monkeypatch):
    from app.models import MintPlan, MintPlanRecord
    plan, request = await plan_context(lab, monkeypatch)
    r = await lab.client.post('/api/tasks/arm', json=request)
    assert r.status_code == 200, r.text
    task_id = r.json()['id']
    duplicate = await lab.client.post('/api/tasks/arm', json={**request, 'idempotency_key': 'another-intent-key'})
    assert duplicate.status_code == 409
    assert (await lab.client.post('/api/tasks/arm', json=request)).json()['id'] == task_id
    # Another account cannot see, arm, remove or read this plan's records.
    other = await lab.client.post('/api/auth/login', json={'username': 'admin', 'password': 'Admin test password 123'})
    headers = {'Authorization': 'Bearer ' + other.json()['token']}
    assert (await lab.client.delete('/api/mint-plans/' + plan['id'], headers=headers)).status_code == 404
    assert (await lab.client.get('/api/history?section=plans', headers=headers)).json()['records'] == []
    removed = await lab.client.delete('/api/mint-plans/' + plan['id'])
    assert removed.status_code == 200 and removed.json()['in_flight'] is False
    assert (await lab.client.delete('/api/mint-plans/' + plan['id'])).status_code == 200
    assert (await lab.client.get('/api/mint-plans')).json() == []
    assert (await lab.client.get('/api/tasks/queue')).json()['tasks'] == []
    history = (await lab.client.get('/api/history?section=mints')).json()['records']
    assert history[0]['id'] == task_id and history[0]['status'] == 'disarmed'
    assert history[0]['archived_at'] and 'signed_tx_raw' not in history[0]
    page = (await lab.client.get('/api/history?section=plans&limit=1')).json()
    assert page['records'][0]['event'] == 'removed' and page['next_offset'] == 1
    earlier = (await lab.client.get('/api/history?section=plans&limit=1&offset=1')).json()
    assert earlier['records'][0]['snapshot']['quantity'] == 2
    async with lab.factory() as db:
        assert (await db.get(AutomaticGrant, lab.grant.id)).reserved_wei == 0
        assert (await db.get(MintTask, task_id)).signed_tx_raw is None
        assert await db.get(MintPlan, plan['id']) is not None
    lab.w.provider.make_request('evm_setNextBlockTimestamp', [lab.start]); lab.w.provider.make_request('evm_mine', [])
    assert await lab.tick() is False
    assert lab.nft.functions.totalSupply().call() == 0
    # Reimport retains earlier quantity/removal records instead of overwriting history.
    # Keep stage future relative to wall time; do not request live calldata here.
    r = await lab.client.post('/api/mint-plans', json={'url': plan['opensea_url'], 'quantity': 1})
    assert r.status_code == 200, r.text
    records = (await lab.client.get('/api/history?section=plans')).json()['records']
    assert any(x['event'] == 'removed' and x['snapshot']['quantity'] == 2 for x in records)
    assert records[0]['event'] == 'saved' and records[0]['snapshot']['quantity'] == 1


async def test_remove_prepared_plan_keeps_same_nonce_receipt_and_accounting_in_history(lab, monkeypatch):
    plan, request = await plan_context(lab, monkeypatch)
    r = await lab.client.post('/api/tasks/arm', json=request)
    assert r.status_code == 200, r.text
    task_id = r.json()['id']
    lab.w.provider.make_request('evm_setNextBlockTimestamp', [lab.start]); lab.w.provider.make_request('evm_mine', [])
    await lab.due(); await lab.tick()
    async with lab.factory() as db:
        task = await db.get(MintTask, task_id)
        assert task.status == 'prepared'
        original = task.transaction_hash, task.assigned_nonce, task.signed_tx_raw
    r = await lab.client.delete('/api/mint-plans/' + plan['id'])
    assert r.json()['in_flight'] is True
    assert (await lab.client.get('/api/tasks/queue')).json()['tasks'] == []
    async with lab.factory() as db:
        assert (await db.get(AutomaticGrant, lab.grant.id)).reserved_wei > 0
    await lab.due(); await lab.tick()
    lab.w.provider.make_request('evm_mine', [])
    await lab.due(); await lab.tick()
    history = (await lab.client.get('/api/history?section=mints')).json()['records'][0]
    assert history['id'] == task_id and history['status'] == 'confirmed'
    assert history['transaction_hash'] == original[0] and history['actual_total_cost_wei'] > 0
    assert lab.nft.functions.ownerOf(1).call() == lab.owner.address
    assert lab.nft.functions.totalSupply().call() == 2
    async with lab.factory() as db:
        task = await db.get(MintTask, task_id)
        assert (task.transaction_hash, task.assigned_nonce, task.signed_tx_raw) == original
        assert (await db.get(AutomaticGrant, lab.grant.id)).reserved_wei == 0
    assert await lab.tick() is False


async def test_task_remove_is_idempotent_and_history_pagination_is_owner_scoped(lab):
    r = await lab.client.post('/api/tasks/arm', json=lab.request)
    assert r.status_code == 200, r.text
    task_id = r.json()['id']
    for _ in range(2):
        assert (await lab.client.delete('/api/tasks/' + task_id)).json()['history_retained']
    assert (await lab.client.get('/api/tasks/queue')).json()['tasks'] == []
    async with lab.factory() as db:
        assert (await db.get(AutomaticGrant, lab.grant.id)).reserved_wei == 0
    assert (await lab.client.get('/api/history?section=activity&limit=0')).status_code == 422
    assert (await lab.client.get('/api/history?section=activity&offset=-1')).status_code == 422
    assert (await lab.client.get('/api/history?section=unknown')).status_code == 422
    records = (await lab.client.get('/api/history?section=activity')).json()['records']
    assert len([r for r in records if r['event_type'] == 'task_removed']) == 1


async def test_low_balance_covers_mint_and_authorized_gas_without_block_gas_default(lab, monkeypatch):
    # Hardhat omits Nitro's eth_call affordability check; emulate that RPC rule using real chain balances.
    real_provider = automatic.provider
    async def nitro_provider():
        web3 = await real_provider()
        call = web3.eth.call
        async def affordable_call(tx, *args, **kwargs):
            if tx.get('gasPrice') and tx.get('from', '').lower() == lab.owner.address.lower():
                gas = tx.get('gas', (await web3.eth.get_block('latest')).gasLimit)
                required = gas * tx['gasPrice'] + tx.get('value', 0)
                if required > await web3.eth.get_balance(lab.owner.address, 'pending'):
                    raise ValueError('RPC simulation requires sufficient balance for its supplied gas limit')
            return await call(tx, *args, **kwargs)
        web3.eth.call = affordable_call
        return web3
    monkeypatch.setattr(automatic, 'provider', nitro_provider)
    # Enough for this bounded mint, far below the default RPC simulation's block-sized gas budget.
    r = await lab.client.post('/api/tasks/arm', json=lab.request)
    assert r.status_code == 200, r.text
    task_id = r.json()['id']
    lab.w.provider.make_request('hardhat_setBalance', [lab.owner.address, hex(10**15)])
    lab.w.provider.make_request('evm_setNextBlockTimestamp', [lab.start]); lab.w.provider.make_request('evm_mine', [])
    await lab.due(); await lab.tick()
    async with lab.factory() as db:
        task = await db.get(MintTask, task_id)
        assert task.status == 'prepared', task.failure_reason
    await lab.due(); await lab.tick()
    lab.w.provider.make_request('evm_mine', [])
    await lab.due(); await lab.tick()
    async with lab.factory() as db:
        task = await db.get(MintTask, task_id)
        assert task.status == 'confirmed', task.failure_reason
        assert task.actual_total_cost_wei <= 10**15
    assert lab.nft.functions.ownerOf(1).call() == lab.owner.address
