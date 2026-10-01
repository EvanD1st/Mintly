"""Real SeaDrop presales through real MetaMask + EntryPoint on localhost."""
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak
from web3 import Web3,AsyncWeb3
from web3.logs import DISCARD

from app.services.seadrop_mint import decode_mint,verify_presale,signed_mint_typed_data,PARAM_TYPE,ALLOW_SELECTOR,SIGNED_SELECTOR
from app.services.direct_wallet_gas import ENTRY_POINT,mint_call,packed,userop_typed_data
from app.services.mint_permission import REGISTRY,permission_typed_data
from app.services.signer.base import SEADROP_V1_ADDRESS
from app.services.opensea import OpenSeaUnavailable


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['allowlist','signed'])
async def test_presale_original_wallet_mints_and_invalid_eligibility_cannot_arm(kind,monkeypatch):
    rpc=os.environ.get('MINTLY_TEST_RPC')
    if not rpc:pytest.skip('Isolated EVM required')
    assert urlparse(rpc).hostname in ('localhost','127.0.0.1')
    w=Web3(Web3.HTTPProvider(rpc));assert w.eth.chain_id==31337
    aw=AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc))
    funding,bundler,fee=w.eth.accounts[:3]
    directory=Path(__file__).parent/'fixtures'
    contracts=json.loads((directory/'metamask-delegation-contracts.json').read_text())['contracts']
    presales=json.loads((directory/'seadrop-presale.json').read_text())['contracts']
    def deploy(spec,*args):
        factory=w.eth.contract(abi=spec['abi'],bytecode=spec['bytecode'])
        r=w.eth.wait_for_transaction_receipt(factory.constructor(*args).transact({'from':funding}))
        assert r.status==1
        return w.eth.contract(address=r.contractAddress,abi=spec['abi'])
    try:
        real=deploy(presales['SeaDrop'])
        code=w.eth.get_code(real.address).hex()
        # Relocate only the immutable EIP-712 domain separator to the canonical
        # test address; production code and signature-validation logic are intact.
        def domain(address):return keccak(encode(['bytes32','bytes32','bytes32','uint256','address'],[keccak(text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)'),keccak(text='SeaDrop'),keccak(text='1.0'),31337,address])).hex()
        assert domain(real.address) in code
        code=code.replace(domain(real.address),domain(SEADROP_V1_ADDRESS))
        w.provider.make_request('hardhat_setCode',[SEADROP_V1_ADDRESS,'0x'+code])
        # Constructor initializes Solmate's reentrancy lock in slot zero.
        w.provider.make_request('hardhat_setStorageAt',[SEADROP_V1_ADDRESS,'0x0','0x'+(1).to_bytes(32,'big').hex()])
        seadrop=w.eth.contract(address=SEADROP_V1_ADDRESS,abi=presales['SeaDrop']['abi'])
        nft=deploy(presales['PresaleTestNFT'],SEADROP_V1_ADDRESS)
        manager=deploy(contracts['DelegationManager'],funding)
        entry_spec=json.loads((directory/'entrypoint-v07.json').read_text())
        deployed_entry=deploy(entry_spec)
        w.provider.make_request('hardhat_setCode',[ENTRY_POINT,'0x'+w.eth.get_code(deployed_entry.address).hex()])
        entry=w.eth.contract(address=ENTRY_POINT,abi=entry_spec['abi'])
        implementation=deploy(contracts['EIP7702StatelessDeleGator'],manager.address,ENTRY_POINT)
        enforcers={name:deploy(contracts[name]).address for name in ['ExactExecutionEnforcer','TimestampEnforcer','LimitedCallsEnforcer']}
        monkeypatch.setitem(REGISTRY,'31337',{'manager':manager.address,'implementation':implementation.address,'enforcers':enforcers})
        owner,signer,outsider=Account.create(),Account.create(),Account.create()
        auth=Account.sign_authorization({'chainId':31337,'address':implementation.address,'nonce':0},owner.key)
        authorization={'chainId':auth.chain_id,'address':auth.address,'nonce':auth.nonce,'yParity':auth.y_parity,'r':auth.r,'s':auth.s}
        w.eth.wait_for_transaction_receipt(w.eth.send_transaction({'from':funding,'to':owner.address,'value':10**18,'authorizationList':[authorization],'type':4}))
        now=w.eth.get_block('latest').timestamp
        params=(10,4,now-1,now+600,1,100,500,True)
        sibling=keccak(b'other wallet')
        leaf=keccak(encode(['address',PARAM_TYPE],[owner.address,params]))
        root=keccak(min(leaf,sibling)+max(leaf,sibling))
        bounds=(10,4,params[2],params[3],100,500,500)
        w.eth.wait_for_transaction_receipt(nft.functions.configure(root,fee,signer.address,bounds).transact({'from':funding}))
        types=['address','address','address','uint256',PARAM_TYPE]
        values=[nft.address,fee,owner.address,2,params]
        if kind=='allowlist':types+=['bytes32[]'];values+=[[sibling]];selector=ALLOW_SELECTOR
        else:
            types+=['uint256','bytes'];selector=SIGNED_SELECTOR
            mint={'contract':nft.address,'wallet':owner.address,'fee':fee,'params':params,'salt':42}
            signature=Account.sign_message(encode_typed_data(full_message=signed_mint_typed_data(mint,31337)),signer.key).signature
            values+=[42,signature]
        def tx(vals=values):return {'to':SEADROP_V1_ADDRESS,'value':str(vals[4][0]*vals[3]),'data':'0x'+selector+encode(types,vals).hex()+'3d958fe2'}
        decoded=decode_mint(tx(),nft.address,owner.address,2)
        stage=SimpleNamespace(starts_at=datetime.fromtimestamp(params[2],timezone.utc),ends_at=datetime.fromtimestamp(params[3],timezone.utc),price_wei=10,stage_type='presale')
        await verify_presale(aw,decoded,stage)
        # Wallet-specific cryptographic eligibility rejects another recipient,
        # tampered stage/price, corrupt proof/signature and unauthorized fee.
        variations=[]
        changed=list(values);changed[2]=outsider.address;variations.append((changed,outsider.address))
        for index,number in [(0,11),(2,params[2]+1),(6,501)]:
            changed=list(values);p=list(params);p[index]=number;changed[4]=tuple(p);variations.append((changed,owner.address))
        changed=list(values);changed[1]=outsider.address;variations.append((changed,owner.address))
        changed=list(values);changed[-1]=[keccak(b'bad proof')] if kind=='allowlist' else bytes(signature[:-1])+bytes([signature[-1]^1]);variations.append((changed,owner.address))
        for changed,wallet in variations:
            candidate=decode_mint(tx(changed),nft.address,wallet,2)
            with pytest.raises(OpenSeaUnavailable):await verify_presale(aw,candidate,stage)
            with pytest.raises(Exception):w.eth.estimate_gas({'from':wallet,'to':SEADROP_V1_ADDRESS,'value':int(tx(changed)['value']),'data':tx(changed)['data']})
        execution=decoded['execution']
        typed=permission_typed_data(31337,owner.address,owner.address,execution,params[2],params[3])
        delegation='0x'+Account.sign_message(encode_typed_data(full_message=typed),owner.key).signature.hex()
        nonce=entry.functions.getNonce(owner.address,0).call()
        op={'sender':owner.address,'nonce':hex(nonce),'callData':mint_call(typed,delegation,execution),'callGasLimit':hex(600000),'verificationGasLimit':hex(150000),'preVerificationGas':hex(100000),'maxFeePerGas':hex(w.eth.gas_price*2),'maxPriorityFeePerGas':hex(w.eth.gas_price),'signature':'0x'}
        op['signature']='0x'+Account.sign_message(encode_typed_data(full_message=userop_typed_data(31337,op)),owner.key).signature.hex()
        before=w.eth.get_balance(owner.address)+entry.functions.balanceOf(owner.address).call()
        receipt=w.eth.wait_for_transaction_receipt(entry.functions.handleOps([packed(op)],bundler).transact({'from':bundler,'gas':2000000}))
        event=entry.events.UserOperationEvent().process_receipt(receipt,errors=DISCARD)[0]['args']
        assert event['success'] is True
        after=w.eth.get_balance(owner.address)+entry.functions.balanceOf(owner.address).call()
        assert before-after==20+event['actualGasCost']
        assert nft.functions.ownerOf(1).call()==owner.address and nft.functions.ownerOf(2).call()==owner.address
        with pytest.raises(Exception):entry.functions.handleOps([packed(op)],bundler).estimate_gas({'from':bundler})
        if kind=='signed':
            with pytest.raises(OpenSeaUnavailable):await verify_presale(aw,decoded,stage)
            with pytest.raises(Exception):w.eth.estimate_gas({'from':owner.address,'to':SEADROP_V1_ADDRESS,'data':tx()['data'],'value':20})
        else:
            w.eth.wait_for_transaction_receipt(nft.functions.replaceRoot(bytes(32)).transact({'from':funding}))
            with pytest.raises(OpenSeaUnavailable):await verify_presale(aw,decoded,stage)
    finally:await aw.provider.disconnect()
