"""Real MetaMask contracts on an isolated local Prague EVM. Never a live RPC."""
import os, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3
from eth_abi import encode
from sqlalchemy import select
from app.config import settings
from app.models import User, Wallet, MintPlan, MintPermission
from app.services.mint_permission import REGISTRY, with_gas_reimbursement, permission_typed_data, redeem_calldata, revoke_calldata
from app.services.permission_relayer import process_one_permission
from app.services.opensea import CHAINS
from app.services.signer.base import SEADROP_V1_ADDRESS, MINT_PUBLIC_SELECTOR

@pytest.mark.asyncio
async def test_real_enforcers_execute_once_reject_changes_expiry_and_revocation(monkeypatch,test_db):
    rpc=os.environ.get('MINTLY_TEST_RPC')
    if not rpc: pytest.skip('MINTLY_TEST_RPC is required for the isolated EVM integration test')
    assert urlparse(rpc).hostname in ['127.0.0.1','localhost']
    w3=Web3(Web3.HTTPProvider(rpc,request_kwargs={'timeout':15}))
    assert w3.eth.chain_id==31337, 'Only the isolated chain may run this test'
    accounts=w3.eth.accounts
    artifacts=json.loads((Path(__file__).parent/'fixtures/metamask-delegation-contracts.json').read_text())['contracts']
    def deploy(name,*args):
        spec=artifacts[name]
        contract=w3.eth.contract(abi=spec['abi'],bytecode=spec['bytecode'])
        receipt=w3.eth.wait_for_transaction_receipt(contract.constructor(*args).transact({'from':accounts[0]}))
        assert receipt.status==1
        return receipt.contractAddress
    manager=deploy('DelegationManager',accounts[0])
    implementation=deploy('EIP7702StatelessDeleGator',manager,accounts[0])
    enforcers={name:deploy(name) for name in ['ExactExecutionEnforcer','ExactExecutionBatchEnforcer','TimestampEnforcer','LimitedCallsEnforcer']}
    monkeypatch.setitem(REGISTRY,'31337',{'manager':manager,'implementation':implementation,'enforcers':enforcers})
    user=Account.create()
    w3.eth.wait_for_transaction_receipt(w3.eth.send_transaction({'from':accounts[0],'to':user.address,'value':10**18}))
    auth=Account.sign_authorization({'chainId':31337,'address':implementation,'nonce':0},user.key)
    auth_dict={'chainId':auth.chain_id,'address':auth.address,'nonce':auth.nonce,'yParity':auth.y_parity,'r':auth.r,'s':auth.s}
    receipt=w3.eth.wait_for_transaction_receipt(w3.eth.send_transaction({'from':accounts[0],'to':user.address,'value':0,'authorizationList':[auth_dict],'type':4}))
    assert receipt.status==1
    assert bytes(w3.eth.get_code(user.address))==bytes.fromhex('ef0100'+implementation[2:])
    mocks=json.loads((Path(__file__).parent/'fixtures/mock-seadrop.json').read_text())
    w3.provider.make_request('hardhat_setCode',[SEADROP_V1_ADDRESS,'0x'+mocks['MockSeaDrop']['evm']['deployedBytecode']['object']])
    nft=w3.eth.contract(abi=mocks['MockNFT']['abi'],bytecode='0x'+mocks['MockNFT']['evm']['bytecode']['object'])
    receipt=w3.eth.wait_for_transaction_receipt(nft.constructor().transact({'from':accounts[0]}))
    nft=w3.eth.contract(address=receipt.contractAddress,abi=mocks['MockNFT']['abi'])
    mint_data='0x'+MINT_PUBLIC_SELECTOR+encode(['address','address','address','uint256'],[nft.address,accounts[3],user.address,2]).hex()
    execution={'target':SEADROP_V1_ADDRESS,'value':'20','data':mint_data}
    now=w3.eth.get_block('latest').timestamp
    def signed(expiry=now+300):
        typed=permission_typed_data(31337,user.address,accounts[1],execution,now-1,expiry)
        sig='0x'+Account.sign_message(encode_typed_data(full_message=typed),user.key).signature.hex()
        return typed,sig
    typed,sig=signed()
    changed={**execution,'value':'101'}
    with pytest.raises(Exception):
        w3.eth.estimate_gas({'from':accounts[1],'to':manager,'data':redeem_calldata(typed,sig,changed)})
    changed={**execution,'target':accounts[4]}
    with pytest.raises(Exception):
        w3.eth.estimate_gas({'from':accounts[1],'to':manager,'data':redeem_calldata(typed,sig,changed)})
    data=redeem_calldata(typed,sig,execution)
    before=w3.eth.get_balance(user.address)
    receipt=w3.eth.wait_for_transaction_receipt(w3.eth.send_transaction({'from':accounts[1],'to':manager,'data':data}))
    assert receipt.status==1
    assert before-w3.eth.get_balance(user.address)==20, 'Only mint value is debited; operator pays gas'
    assert nft.functions.ownerOf(1).call()==user.address
    assert nft.functions.ownerOf(2).call()==user.address
    with pytest.raises(Exception): w3.eth.estimate_gas({'from':accounts[1],'to':manager,'data':data})
    typed,sig=signed()
    revoke={'from':user.address,'to':manager,'data':revoke_calldata(typed,sig),'value':0,'chainId':31337,
            'nonce':w3.eth.get_transaction_count(user.address),'gasPrice':w3.eth.gas_price}
    revoke['gas']=w3.eth.estimate_gas(revoke)
    signed_tx=Account.sign_transaction(revoke,user.key)
    receipt=w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed_tx.raw_transaction))
    assert receipt.status==1
    with pytest.raises(Exception): w3.eth.estimate_gas({'from':accounts[1],'to':manager,'data':redeem_calldata(typed,sig,execution)})
    # Exact mint plus fee: neither reimbursement amount nor recipient can change.
    fee_execution=with_gas_reimbursement(execution,accounts[1],1000)
    chain_now=w3.eth.get_block('latest').timestamp
    typed=permission_typed_data(31337,user.address,accounts[1],fee_execution,chain_now-1,chain_now+300)
    sig='0x'+Account.sign_message(encode_typed_data(full_message=typed),user.key).signature.hex()
    for fee in [{'target':accounts[1],'value':'1001'},{'target':accounts[4],'value':'1000'}]:
        tampered={**fee_execution,'gas_reimbursement':fee}
        with pytest.raises(Exception): w3.eth.estimate_gas({'from':accounts[1],'to':manager,'data':redeem_calldata(typed,sig,tampered)})
    before=w3.eth.get_balance(user.address)
    batch_data=redeem_calldata(typed,sig,fee_execution)
    receipt=w3.eth.wait_for_transaction_receipt(w3.eth.send_transaction({'from':accounts[1],'to':manager,'data':batch_data}))
    assert receipt.status==1
    assert before-w3.eth.get_balance(user.address)==1020
    assert nft.functions.totalSupply().call()==4
    with pytest.raises(Exception): w3.eth.estimate_gas({'from':accounts[1],'to':manager,'data':batch_data})
    failed_execution=with_gas_reimbursement({**execution,'value':'21'},accounts[1],1000)
    typed=permission_typed_data(31337,user.address,accounts[1],failed_execution,chain_now-1,chain_now+300)
    sig='0x'+Account.sign_message(encode_typed_data(full_message=typed),user.key).signature.hex()
    before=w3.eth.get_balance(user.address)
    # Hardhat reports a reverted transaction as an RPC exception.
    with pytest.raises(Exception):
        w3.eth.send_transaction({'from':accounts[1],'to':manager,'data':redeem_calldata(typed,sig,failed_execution),'gas':1000000})
    assert w3.eth.get_balance(user.address)==before
    assert nft.functions.totalSupply().call()==4
    # Exercise the actual worker: operator key signs, durable bytes precede send,
    # receipt finalizes the permission, and a replay cannot mint again.
    operator=Account.create()
    w3.eth.wait_for_transaction_receipt(w3.eth.send_transaction({'from':accounts[0],'to':operator.address,'value':10**18}))
    owner=(await test_db.execute(select(User).where(User.username=='member'))).scalar_one()
    wallet=Wallet(user_id=owner.id,address=user.address,label='MetaMask',signing_capability='interactive',supported_chains=['Local test'],is_demo=False)
    test_db.add(wallet);await test_db.flush()
    plan=MintPlan(user_id=owner.id,wallet_id=wallet.id,collection_slug='local-test',quantity=2,collection_name='Local test',chain='Local test',chain_id=31337,contract_address=nft.address,opensea_url='https://opensea.io/collection/local-test',status='ready_for_approval',status_note='Test',stage_type='public_sale')
    test_db.add(plan);await test_db.flush()
    execution=with_gas_reimbursement(execution,operator.address,settings.MINT_RELAYER_MAX_FEE_WEI)
    now=datetime.now(timezone.utc)
    expiry=datetime.fromtimestamp(max(int(now.timestamp()),w3.eth.get_block('latest').timestamp)+1800,timezone.utc)
    typed=permission_typed_data(31337,user.address,operator.address,execution,int(now.timestamp())-1,int(expiry.timestamp()))
    signature='0x'+Account.sign_message(encode_typed_data(full_message=typed),user.key).signature.hex()
    p=MintPermission(user_id=owner.id,plan_id=plan.id,code_hash='0'*64,typed_data=typed,execution=execution,signature=signature,status='armed',expires_at=expiry,execute_after=now-timedelta(seconds=1),signature_deadline=now+timedelta(minutes=5),note='Local test')
    test_db.add(p);await test_db.commit()
    monkeypatch.setattr(settings,'ENABLE_MINT_PERMISSIONS',True)
    monkeypatch.setitem(CHAINS,'local-test',(31337,'Local test'))
    monkeypatch.setattr('app.services.mint_permission.chain_rpc',lambda chain:rpc)
    monkeypatch.setattr('app.services.permission_relayer.relayer_account',lambda:operator)
    await process_one_permission(test_db)
    assert p.status=='submitted',p.note
    assert Account.recover_transaction(p.raw_transaction)==operator.address
    await process_one_permission(test_db)
    assert p.status=='minted',p.note
    assert p.raw_transaction is None
    assert nft.functions.totalSupply().call()==6
    replay=MintPermission(user_id=owner.id,plan_id=plan.id,code_hash='1'*64,typed_data=typed,execution=execution,signature=signature,status='armed',expires_at=expiry,execute_after=now-timedelta(seconds=1),signature_deadline=now+timedelta(minutes=5),note='Replay test')
    test_db.add(replay);await test_db.commit()
    await process_one_permission(test_db)
    assert replay.status=='failed'
    assert nft.functions.totalSupply().call()==6
    chain_now=w3.eth.get_block('latest').timestamp
    typed=permission_typed_data(31337,user.address,accounts[1],execution,chain_now-1,chain_now+20)
    sig='0x'+Account.sign_message(encode_typed_data(full_message=typed),user.key).signature.hex()
    w3.provider.make_request('evm_increaseTime',[400]);w3.provider.make_request('evm_mine',[])
    with pytest.raises(Exception): w3.eth.estimate_gas({'from':accounts[1],'to':manager,'data':redeem_calldata(typed,sig,execution)})
