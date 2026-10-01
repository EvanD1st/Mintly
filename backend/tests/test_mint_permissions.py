"""No live funds: official SDK vectors and permission lifecycle isolation."""
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_abi import encode
from eth_utils import keccak
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.config import settings
from app.api.deps import get_db
from app.models import User, Wallet, MintPlan, MintPermission
from app.services.mint_permission import permission_typed_data, redeem_calldata, revoke_calldata, validate_signature, public_mint_execution, scheduled_public_execution, with_gas_reimbursement
from app.services.opensea import OpenSeaUnavailable
from app.services.signer.base import SEADROP_V1_ADDRESS, MINT_PUBLIC_SELECTOR

def calldata(contract,wallet,quantity):
    return '0x'+MINT_PUBLIC_SELECTOR+encode(['address','address','address','uint256'],[contract,'0x'+'0'*40,wallet,quantity]).hex()

def test_python_delegation_matches_official_sdk_golden_vectors():
    golden=json.loads((Path(__file__).parent/'fixtures/delegation-sdk-golden.json').read_text())
    execution={'target':SEADROP_V1_ADDRESS,'value':'37000000000000','data':'0x12345678'}
    typed=permission_typed_data(8453,'0x'+'2'*40,'0x'+'1'*40,execution,100,200,salt=42)
    signature='0x'+'11'*65
    assert [c['terms'].lower() for c in typed['message']['caveats']]==[c['terms'].lower() for c in golden['caveats']]
    message=encode_typed_data(full_message=typed)
    assert '0x'+message.body.hex()==golden['delegationHash']
    assert '0x'+keccak(b'\x19'+message.version+message.header+message.body).hex()==golden['typedHash']
    assert redeem_calldata(typed,signature,execution)==golden['redeem']
    assert revoke_calldata(typed,signature).lower()==golden['revoke'].lower()

def test_tampered_collection_quantity_recipient_or_key_is_rejected():
    account=Account.create()
    execution={'target':SEADROP_V1_ADDRESS,'value':'10','data':calldata('0x'+'2'*40,account.address,2)}
    tx={'to':execution['target'],'value':'10','data':execution['data']}
    assert public_mint_execution(tx,'0x'+'2'*40,account.address,2)==execution
    for contract,wallet,quantity in [('0x'+'3'*40,account.address,2),('0x'+'2'*40,'0x'+'4'*40,2),('0x'+'2'*40,account.address,1)]:
        with pytest.raises(OpenSeaUnavailable): public_mint_execution(tx,contract,wallet,quantity)
    typed=permission_typed_data(8453,account.address,'0x'+'1'*40,execution,100,200)
    signature='0x'+Account.sign_message(encode_typed_data(full_message=typed),account.key).signature.hex()
    validate_signature(typed,signature,account.address)
    typed['message']['caveats'][0]['terms']='0x00'
    with pytest.raises(OpenSeaUnavailable): validate_signature(typed,signature,account.address)

@pytest.mark.asyncio
async def test_future_public_mint_requires_exact_onchain_schedule_price_and_limit():
    start=datetime.now(timezone.utc)+timedelta(hours=1); end=start+timedelta(hours=1)
    plan=SimpleNamespace(contract_address='0x'+'2'*40,quantity=2,price_wei=10,starts_at=start.replace(microsecond=0),ends_at=end.replace(microsecond=0),chain_id=8453)
    wallet=SimpleNamespace(address='0x'+'1'*40)
    values=[10,int(plan.starts_at.timestamp()),int(plan.ends_at.timestamp()),2,1000,True]
    future=encode(['uint80','uint48','uint48','uint16','uint16','bool'],values)
    fees=encode(['address[]'],[['0x'+'3'*40]])
    provider=SimpleNamespace(eth=SimpleNamespace(call=AsyncMock(side_effect=[future,fees]),get_balance=AsyncMock(return_value=20)))
    tx=await scheduled_public_execution(provider,plan,wallet)
    assert public_mint_execution(tx,plan.contract_address,wallet.address,2)['value']=='20'
    values[0]=11
    provider.eth.call=AsyncMock(return_value=encode(['uint80','uint48','uint48','uint16','uint16','bool'],values))
    with pytest.raises(OpenSeaUnavailable,match='does not match'): await scheduled_public_execution(provider,plan,wallet)

@pytest.mark.asyncio
async def test_permission_is_private_single_use_cancellable_and_never_imports_user_key(test_db,monkeypatch):
    user=(await test_db.execute(select(User).where(User.username=='member'))).scalar_one()
    account=Account.create(); operator=Account.create()
    wallet=Wallet(user_id=user.id,address=account.address,label='MetaMask',signing_capability='interactive',supported_chains=['Base'],is_demo=False)
    test_db.add(wallet); await test_db.flush()
    plan=MintPlan(user_id=user.id,wallet_id=wallet.id,collection_slug='example',quantity=2,collection_name='Example',chain='Base',chain_id=8453,contract_address='0x'+'2'*40,opensea_url='https://opensea.io/collection/example',status='ready_for_approval',status_note='Ready',stage_type='public_sale',mint_value_wei=20,starts_at=datetime.now(timezone.utc)-timedelta(minutes=1),ends_at=datetime.now(timezone.utc)+timedelta(minutes=20))
    test_db.add(plan); await test_db.commit()
    monkeypatch.setattr(settings,'ENABLE_MINT_PERMISSIONS',True)
    monkeypatch.setattr('app.api.mint_permissions.relayer_account',lambda:operator)
    provider=SimpleNamespace(provider=SimpleNamespace(disconnect=AsyncMock()),eth=SimpleNamespace(get_balance=AsyncMock(return_value=10**18),gas_price=__import__('asyncio').sleep(0,result=1000000000)))
    monkeypatch.setattr('app.api.mint_permissions.checked_provider',AsyncMock(return_value=provider))
    async def refresh(plan,wallet,client,transaction_out):
        transaction_out.update(chain='base',to=SEADROP_V1_ADDRESS,value='20',data=calldata(plan.contract_address,wallet.address,2))
    monkeypatch.setattr('app.api.mint_permissions.refresh_mint_plan',refresh)
    monkeypatch.setattr('app.api.mint_plans.OpenSeaClient',lambda:SimpleNamespace(get_drop=AsyncMock(return_value={
        'chain':'base','contract_address':plan.contract_address,'opensea_url':plan.opensea_url})))
    async def db_override(): yield test_db
    app.dependency_overrides[get_db]=db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='https://test') as client:
            login=await client.post('/api/auth/login',json={'username':'member','password':'Member test password 123'})
            client.headers['Authorization']='Bearer '+login.json()['token']
            req={'plan_id':plan.id,'max_mint_value_wei':'20'}
            too_low=await client.post('/api/mint-permissions',json={**req,'max_mint_value_wei':'19'})
            assert too_low.status_code==409
            provider.eth.gas_price=__import__('asyncio').sleep(0,result=1000000000)
            created=await client.post('/api/mint-permissions',json=req)
            assert created.status_code==200,created.text
            payload=created.json(); code=payload['code']; pid=payload['id']
            assert 'signature' not in payload and 'typed_data' not in payload
            assert (await client.post('/api/mint-permissions',json=req)).status_code==409
            challenge=await client.post('/api/mint-permission-link/challenge',json={'code':code})
            assert challenge.status_code==200
            typed=challenge.json()['typed_data']
            signature='0x'+Account.sign_message(encode_typed_data(full_message=typed),account.key).signature.hex()
            bad='0x'+Account.sign_message(encode_typed_data(full_message=typed),operator.key).signature.hex()
            assert (await client.post('/api/mint-permission-link/complete',json={'code':code,'signature':bad})).status_code==400
            approved=await client.post('/api/mint-permission-link/complete',json={'code':code,'signature':signature})
            assert approved.json()['status']=='armed'
            assert (await client.post('/api/mint-permission-link/complete',json={'code':code,'signature':signature})).status_code==404
            assert (await client.post('/api/mint-plans',json={'url':plan.opensea_url,'quantity':1})).status_code in [409,503]
            login=await client.post('/api/auth/login',json={'username':'admin','password':'Admin test password 123'})
            client.headers['Authorization']='Bearer '+login.json()['token']
            assert (await client.get('/api/mint-permissions')).json()==[]
            assert (await client.post(f'/api/mint-permissions/{pid}/cancel')).status_code==404
            login=await client.post('/api/auth/login',json={'username':'member','password':'Member test password 123'})
            client.headers['Authorization']='Bearer '+login.json()['token']
            cancelled=await client.post(f'/api/mint-permissions/{pid}/cancel')
            assert cancelled.json()['status']=='cancelled'
            revoke=await client.post(f'/api/mint-permissions/{pid}/revocation')
            challenge=await client.post('/api/mint-permission-link/challenge',json={'code':revoke.json()['code']})
            assert challenge.json()['mode']=='revoke'
            assert challenge.json()['transaction']['value']=='0x0'
            assert (await client.post(f'/api/mint-permissions/{pid}/cancel')).status_code==409
    finally: app.dependency_overrides.pop(get_db,None)


def test_batch_permission_matches_official_sdk():
    golden=json.loads((Path(__file__).parent/'fixtures/delegation-batch-sdk-golden.json').read_text())
    execution=with_gas_reimbursement({'target':SEADROP_V1_ADDRESS,'value':'37000000000000','data':'0x12345678'},'0x'+'1'*40,1000)
    typed=permission_typed_data(8453,'0x'+'2'*40,'0x'+'1'*40,execution,100,200,salt=42)
    assert [c['terms'].lower() for c in typed['message']['caveats']]==[c['terms'].lower() for c in golden['caveats']]
    message=encode_typed_data(full_message=typed)
    assert '0x'+keccak(b'\x19'+message.version+message.header+message.body).hex()==golden['typedHash']
    assert redeem_calldata(typed,'0x'+'11'*65,execution)==golden['redeem']
