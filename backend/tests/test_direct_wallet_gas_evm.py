"""Real EntryPoint v0.7 + MetaMask contracts, isolated EVM only."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

from app.services.direct_wallet_gas import ENTRY_POINT, mint_call, packed, userop_typed_data, operation_hash
from app.services.mint_permission import REGISTRY, permission_typed_data, revoke_calldata
from app.services.signer.base import SEADROP_V1_ADDRESS, MINT_PUBLIC_SELECTOR


def test_entrypoint_mints_with_owner_funds_rejects_tampering_and_replay(monkeypatch):
    rpc=os.environ.get('MINTLY_TEST_RPC')
    if not rpc: pytest.skip('Isolated EVM required')
    assert urlparse(rpc).hostname in ('localhost','127.0.0.1')
    w=Web3(Web3.HTTPProvider(rpc));assert w.eth.chain_id==31337
    funding,bundler=w.eth.accounts[:2]
    fixtures=Path(__file__).parent/'fixtures'
    contracts=json.loads((fixtures/'metamask-delegation-contracts.json').read_text())['contracts']
    def deploy(spec,*args):
        c=w.eth.contract(abi=spec['abi'],bytecode=spec['bytecode'])
        r=w.eth.wait_for_transaction_receipt(c.constructor(*args).transact({'from':funding}))
        assert r.status==1
        return w.eth.contract(address=r.contractAddress,abi=spec['abi'])
    entry_spec=json.loads((fixtures/'entrypoint-v07.json').read_text())
    deployed=deploy(entry_spec)
    w.provider.make_request('hardhat_setCode',[ENTRY_POINT,'0x'+w.eth.get_code(deployed.address).hex()])
    entry=w.eth.contract(address=ENTRY_POINT,abi=entry_spec['abi'])
    manager=deploy(contracts['DelegationManager'],funding)
    implementation=deploy(contracts['EIP7702StatelessDeleGator'],manager.address,ENTRY_POINT)
    enforcers={n:deploy(contracts[n]).address for n in ['ExactExecutionEnforcer','TimestampEnforcer','LimitedCallsEnforcer']}
    monkeypatch.setitem(REGISTRY,'31337',{'manager':manager.address,'implementation':implementation.address,'enforcers':enforcers})
    owner=Account.create()
    auth=Account.sign_authorization({'chainId':31337,'address':implementation.address,'nonce':0},owner.key)
    authorization={'chainId':auth.chain_id,'address':auth.address,'nonce':auth.nonce,'yParity':auth.y_parity,'r':auth.r,'s':auth.s}
    w.eth.wait_for_transaction_receipt(w.eth.send_transaction({'from':funding,'to':owner.address,'value':10**18,'authorizationList':[authorization],'type':4}))
    mocks=json.loads((fixtures/'mock-seadrop.json').read_text())
    w.provider.make_request('hardhat_setCode',[SEADROP_V1_ADDRESS,'0x'+mocks['MockSeaDrop']['evm']['deployedBytecode']['object']])
    nft=deploy({'abi':mocks['MockNFT']['abi'],'bytecode':'0x'+mocks['MockNFT']['evm']['bytecode']['object']})
    execution={'target':SEADROP_V1_ADDRESS,'value':'20','data':'0x'+MINT_PUBLIC_SELECTOR+encode(['address','address','address','uint256'],[nft.address,funding,owner.address,2]).hex()}
    def approve(execution,after=None,expiry=None):
        now=w.eth.get_block('latest').timestamp
        typed=permission_typed_data(31337,owner.address,owner.address,execution,after or now-1,expiry or now+300)
        signature='0x'+Account.sign_message(encode_typed_data(full_message=typed),owner.key).signature.hex()
        nonce=entry.functions.getNonce(owner.address,0).call()
        op={'sender':owner.address,'nonce':hex(nonce),'callData':mint_call(typed,signature,execution),'callGasLimit':hex(600000),'verificationGasLimit':hex(150000),'preVerificationGas':hex(100000),'maxFeePerGas':hex(w.eth.gas_price*2),'maxPriorityFeePerGas':hex(w.eth.gas_price),'signature':'0x'}
        op['signature']='0x'+Account.sign_message(encode_typed_data(full_message=userop_typed_data(31337,op)),owner.key).signature.hex()
        account=w.eth.contract(address=owner.address,abi=contracts['EIP7702StatelessDeleGator']['abi'])
        # Python EIP-712 construction must exactly match the actual wallet.
        digest=account.functions.getPackedUserOperationTypedDataHash(packed(op)).call()
        assert Account._recover_hash(digest,signature=op['signature'])==owner.address
        assert '0x'+entry.functions.getUserOpHash(packed(op)).call().hex()==operation_hash(op,31337)
        return typed,signature,op
    typed,signature,op=approve(execution)
    for key,value in [('maxFeePerGas',hex(int(op['maxFeePerGas'],16)+1)),('callGasLimit',hex(600001)),('nonce',hex(1)),('callData','0x')]:
        changed={**op,key:value}
        with pytest.raises(Exception): entry.functions.handleOps([packed(changed)],bundler).estimate_gas({'from':bundler})
    before=w.eth.get_balance(owner.address)+entry.functions.balanceOf(owner.address).call()
    receipt=w.eth.wait_for_transaction_receipt(entry.functions.handleOps([packed(op)],bundler).transact({'from':bundler,'gas':2000000}))
    events=entry.events.UserOperationEvent().process_receipt(receipt,errors=__import__('web3').logs.DISCARD)
    assert len(events)==1 and events[0]['args']['success']
    gas_cost=events[0]['args']['actualGasCost']
    after=w.eth.get_balance(owner.address)+entry.functions.balanceOf(owner.address).call()
    assert before-after==20+gas_cost
    assert gas_cost>0
    assert nft.functions.ownerOf(1).call()==owner.address
    assert nft.functions.ownerOf(2).call()==owner.address
    with pytest.raises(Exception): entry.functions.handleOps([packed(op)],bundler).estimate_gas({'from':bundler})
    # Execution-time caveats reject early, expired and revoked operations.
    # EntryPoint still charges gas on failure and consumes the nonce.
    now=w.eth.get_block('latest').timestamp
    for kind in ['early','expired','revoked','bad_mint']:
        candidate={**execution,'value':'21'} if kind=='bad_mint' else execution
        typed,sig,failed=approve(candidate,after=now+100 if kind=='early' else None,expiry=now-1 if kind=='expired' else None)
        if kind=='revoked':
            tx={'to':manager.address,'data':revoke_calldata(typed,sig),'value':0,'chainId':31337,'nonce':w.eth.get_transaction_count(owner.address),'gas':300000,'gasPrice':w.eth.gas_price}
            raw=Account.sign_transaction(tx,owner.key)
            w.eth.wait_for_transaction_receipt(w.eth.send_raw_transaction(raw.raw_transaction))
        before=w.eth.get_balance(owner.address)+entry.functions.balanceOf(owner.address).call()
        r=w.eth.wait_for_transaction_receipt(entry.functions.handleOps([packed(failed)],bundler).transact({'from':bundler,'gas':2000000}))
        e=entry.events.UserOperationEvent().process_receipt(r,errors=__import__('web3').logs.DISCARD)[0]['args']
        assert e['success'] is False
        after=w.eth.get_balance(owner.address)+entry.functions.balanceOf(owner.address).call()
        assert before-after==e['actualGasCost']>0
        assert nft.functions.totalSupply().call()==2
        with pytest.raises(Exception): entry.functions.handleOps([packed(failed)],bundler).estimate_gas({'from':bundler})
