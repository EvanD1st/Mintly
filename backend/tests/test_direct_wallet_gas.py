import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from eth_abi import encode

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.config import settings
from app.api.deps import get_db
from app.models import User, Wallet, MintPlan, MintPermission
from app.services.direct_wallet_gas import Bundler, maximum_gas, validate_operation, operation_hash
from app.services.opensea import OpenSeaUnavailable
from tests.test_mint_permissions import calldata, RepeatableGasPrice


@pytest.mark.asyncio
@pytest.mark.parametrize('mint_kind',['public','allowlist','signed'])
async def test_direct_flow_requires_two_owner_signatures_without_operator(test_db,monkeypatch,mint_kind):
    owner=Account.create();other=Account.create()
    member=(await test_db.execute(select(User).where(User.username=='member'))).scalar_one()
    wallet=Wallet(user_id=member.id,address=owner.address,label='MetaMask',signing_capability='interactive',supported_chains=['Base'],is_demo=False)
    test_db.add(wallet);await test_db.flush()
    now=datetime.now(timezone.utc)
    plan=MintPlan(user_id=member.id,wallet_id=wallet.id,collection_slug='example',quantity=2,collection_name='Example',chain='Base',chain_id=8453,contract_address='0x'+'2'*40,opensea_url='https://opensea.io/collection/example',status='ready_for_approval',stage_type='public_sale',starts_at=now-timedelta(minutes=1),ends_at=now+timedelta(hours=1),mint_value_wei=20)
    test_db.add(plan);await test_db.commit()
    monkeypatch.setattr(settings,'ENABLE_MINT_PERMISSIONS',True)
    monkeypatch.setattr(settings,'ENABLE_DIRECT_WALLET_GAS',True)
    monkeypatch.setattr(settings,'ENABLE_DIRECT_WALLET_BROADCAST',True)
    monkeypatch.setattr('app.api.mint_permissions.relayer_account',lambda:pytest.fail('No operator required'))
    provider=SimpleNamespace(eth=SimpleNamespace(gas_price=RepeatableGasPrice(),get_balance=AsyncMock(return_value=10**18)),provider=SimpleNamespace(disconnect=AsyncMock()))
    monkeypatch.setattr('app.api.mint_permissions.checked_provider',AsyncMock(return_value=provider))
    op={'sender':owner.address,'nonce':'0x0','callData':'0x','callGasLimit':hex(600000),'verificationGasLimit':hex(150000),'preVerificationGas':hex(100000),'maxFeePerGas':hex(100000000),'maxPriorityFeePerGas':hex(10000000),'signature':'0x'}
    monkeypatch.setattr('app.api.mint_permissions.quote_operation',AsyncMock(return_value=op))
    async def refresh(plan,wallet,client,transaction_out):
        data=calldata(plan.contract_address,wallet.address,2)
        if mint_kind!='public':
            from eth_abi import encode
            from app.services.seadrop_mint import PARAM_TYPE,ALLOW_SELECTOR,SIGNED_SELECTOR
            plan.stage_type='presale';plan.price_wei=10
            params=(10,4,int(now.timestamp())-60,int(now.timestamp())+3600,1,100,500,True)
            types=['address','address','address','uint256',PARAM_TYPE]+(['bytes32[]'] if mint_kind=='allowlist' else ['uint256','bytes'])
            values=[plan.contract_address,'0x'+'3'*40,wallet.address,2,params]+([[]] if mint_kind=='allowlist' else [42,b'\x01'*65])
            data='0x'+(ALLOW_SELECTOR if mint_kind=='allowlist' else SIGNED_SELECTOR)+encode(types,values).hex()
        transaction_out.update(chain='base',to='0x00005EA00Ac477B1030CE78506496e8C2dE24bf5',value='20',data=data)
    monkeypatch.setattr('app.api.mint_permissions.refresh_mint_plan',refresh)
    monkeypatch.setattr('app.services.seadrop_mint.verify_presale',AsyncMock())
    monkeypatch.setattr('app.services.direct_wallet_worker.verify_presale',AsyncMock())
    async def override():yield test_db
    app.dependency_overrides[get_db]=override
    def sign(typed,key):return '0x'+Account.sign_message(encode_typed_data(full_message=typed),key).signature.hex()
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='https://test') as client:
            login=await client.post('/api/auth/login',json={'username':'member','password':'Member test password 123'})
            client.headers['Authorization']='Bearer '+login.json()['token']
            response=await client.post('/api/mint-permissions',json={'plan_id':plan.id,'max_mint_value_wei':'20'})
            assert response.status_code==200,response.text
            created=response.json();code=created['code']
            assert created['gas_mode']=='direct_wallet'
            assert int(created['total_value_wei'])==20+maximum_gas(op)
            challenge=(await client.post('/api/mint-permission-link/challenge',json={'code':code})).json()
            typed=challenge['typed_data'];signature=sign(typed,owner.key)
            assert typed['message']['delegate']==owner.address
            assert (await client.post('/api/mint-permission-link/complete',json={'code':code,'signature':signature})).status_code==409
            assert (await client.post('/api/mint-permission-link/prepare-userop',json={'code':code,'signature':sign(typed,other.key)})).status_code==400
            prepared=await client.post('/api/mint-permission-link/prepare-userop',json={'code':code,'signature':signature})
            assert prepared.status_code==200,prepared.text
            ut=prepared.json()['typed_data']
            bad=sign(ut,other.key)
            assert (await client.post('/api/mint-permission-link/complete',json={'code':code,'signature':signature,'userop_signature':bad})).status_code==400
            signed=sign(ut,owner.key)
            complete=await client.post('/api/mint-permission-link/complete',json={'code':code,'signature':signature,'userop_signature':signed})
            assert complete.json()['status']=='armed',complete.text
            p=await test_db.get(MintPermission,created['id'])
            assert validate_operation(p,8453,owner.address)['signature']==signed
            listing=(await client.get('/api/mint-permissions')).json()
            assert 'signature' not in listing[0] and 'execution' not in listing[0]
            altered=copy.deepcopy(p.execution);altered['direct_gas']['operation']['maxFeePerGas']='0x1'
            with pytest.raises((ValueError,OpenSeaUnavailable)):
                validate_operation(SimpleNamespace(execution=altered,typed_data=p.typed_data,signature=p.signature),8453,owner.address)
            # Durable preparation and immutable send, followed by receipt reconciliation.
            from app.services.direct_wallet_worker import process_direct_permission
            monkeypatch.setattr('app.services.direct_wallet_worker.checked_provider',AsyncMock(return_value=provider))
            monkeypatch.setattr('app.services.direct_wallet_worker.verify_account',AsyncMock())
            gas_estimate={k:op[k] for k in ['callGasLimit','verificationGasLimit','preVerificationGas']}
            provider.eth.gas_price=type('Price',(),{'__await__':lambda self:AsyncMock(return_value=10000000)().__await__()})()
            calls=[]
            class TestBundler:
                def __init__(self,chain):pass
                async def verify(self):pass
                async def call(self,method,params):
                    calls.append((method,copy.deepcopy(params)))
                    if method=='eth_estimateUserOperationGas':return gas_estimate
                    if method=='eth_getUserOperationReceipt':return None
                    if method=='eth_sendUserOperation':
                        assert p.status=='prepared' and p.tx_hash==operation_hash(params[0],8453)
                        return p.tx_hash
            monkeypatch.setattr('app.services.direct_wallet_worker.Bundler',TestBundler)
            monkeypatch.setattr(settings,'ENABLE_DIRECT_WALLET_BROADCAST',False)
            await process_direct_permission(test_db,p,plan,wallet,'base')
            assert p.status=='armed' and 'simulation passed' in p.note
            assert not any(method=='eth_sendUserOperation' for method,args in calls)
            monkeypatch.setattr(settings,'ENABLE_DIRECT_WALLET_BROADCAST',True)
            await process_direct_permission(test_db,p,plan,wallet,'base')
            assert p.status=='submitted'
            sent=[args[0] for method,args in calls if method=='eth_sendUserOperation']
            assert sent==[p.execution['direct_gas']['operation']]
            async def receipt(self,method,params):return {'success':True}
            monkeypatch.setattr(TestBundler,'call',receipt)
            monkeypatch.setattr('app.services.direct_wallet_worker.checked_provider',AsyncMock(side_effect=AssertionError('Receipt reconciliation must not require current wallet code or eligibility')))
            monkeypatch.setattr('app.services.direct_wallet_worker.verify_presale',AsyncMock(side_effect=AssertionError('Consumed signatures must not block receipt reconciliation')))
            await process_direct_permission(test_db,p,plan,wallet,'base')
            assert p.status=='minted'
    finally:app.dependency_overrides.pop(get_db,None)


@pytest.mark.asyncio
async def test_bundler_rejects_wrong_network_and_entrypoint(monkeypatch):
    bundler=object.__new__(Bundler);bundler.chain_id=4663
    bundler.call=AsyncMock(return_value='0x2105')
    with pytest.raises(OpenSeaUnavailable,match='network'):await bundler.verify()
    bundler.call=AsyncMock(side_effect=['0x1237',[]])
    with pytest.raises(OpenSeaUnavailable,match='EntryPoint'):await bundler.verify()


@pytest.mark.asyncio
async def test_quote_respects_bundler_priority_floor_and_does_not_sign(monkeypatch):
    from app.services.direct_wallet_gas import quote_operation, ENTRY_POINT
    owner=Account.create()
    provider=SimpleNamespace(eth=SimpleNamespace(call=AsyncMock(side_effect=[encode(['address'],[ENTRY_POINT]),encode(['uint256'],[123])]),get_code=AsyncMock(return_value=b'code'),gas_price=RepeatableGasPrice()))
    monkeypatch.setattr(settings,'MINT_RELAYER_MAX_FEE_WEI',10**17)
    class TestBundler:
        def __init__(self,chain):pass
        async def verify(self):pass
        async def call(self,method,params):
            assert method=='rundler_maxPriorityFeePerGas'
            return hex(2_000_000_000)
    monkeypatch.setattr('app.services.direct_wallet_gas.Bundler',TestBundler)
    op=await quote_operation(provider,4663,owner.address)
    assert int(op['maxPriorityFeePerGas'],16)==2_000_000_000
    assert int(op['maxFeePerGas'],16)==4_000_000_000
    assert op['signature']=='0x' and op['nonce']=='0x7b'
