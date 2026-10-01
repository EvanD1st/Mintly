"""Test a real Robinhood SeaDrop mint on a localhost fork, never mainnet."""
import argparse,json
from urllib.parse import urlparse
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_abi import encode,decode
from eth_utils import keccak,to_checksum_address
from web3 import Web3
from app.services.mint_permission import REGISTRY,with_gas_reimbursement,permission_typed_data,redeem_calldata
from app.services.signer.base import SEADROP_V1_ADDRESS,MINT_PUBLIC_SELECTOR

def run(rpc,contract,quantity):
    parsed=urlparse(rpc)
    if parsed.scheme!='http' or parsed.hostname not in ['127.0.0.1','localhost']:
        raise ValueError('Only a localhost fork is permitted')
    w=Web3(Web3.HTTPProvider(rpc,request_kwargs={'timeout':30}))
    if w.eth.chain_id!=31337: raise ValueError('Only local chain 31337 is permitted')
    # Mine a local Prague block: the Orbit source header has no L1 blob fields.
    w.provider.make_request('evm_mine',[])
    env=REGISTRY['4663'];REGISTRY['31337']=env
    contract=to_checksum_address(contract)
    operator=w.eth.accounts[1];user=Account.create()
    for address in [SEADROP_V1_ADDRESS,env['manager'],env['implementation'],*env['enforcers'].values()]:
        assert w.eth.get_code(to_checksum_address(address)), 'Required real contracts missing in fork'
    def read(signature,types):
        raw=w.eth.call({'to':SEADROP_V1_ADDRESS,'data':'0x'+(keccak(text=signature)[:4]+encode(['address'],[contract])).hex()})
        return decode(types,raw)
    price,start,end,limit,fee_bps,restricted=read('getPublicDrop(address)',['uint80','uint48','uint48','uint16','uint16','bool'])
    now=w.eth.get_block('latest').timestamp
    assert start<=now<end, 'Public stage is not open at fork block'
    assert 1<=quantity<=limit
    recipients=read('getAllowedFeeRecipients(address)',['address[]'])[0]
    assert recipients, 'Cannot verify fee recipient'
    fee_recipient=recipients[0]
    assert w.provider.make_request('hardhat_setBalance',[user.address,hex(10**18)]).get('result') is True
    auth=Account.sign_authorization({'chainId':31337,'address':env['implementation'],'nonce':0},user.key)
    receipt=w.eth.wait_for_transaction_receipt(w.eth.send_transaction({'from':w.eth.accounts[0],'to':user.address,'authorizationList':[{'chainId':auth.chain_id,'address':auth.address,'nonce':auth.nonce,'yParity':auth.y_parity,'r':auth.r,'s':auth.s}],'type':4}))
    assert receipt.status==1
    assert bytes(w.eth.get_code(user.address))==bytes.fromhex('ef0100'+env['implementation'][2:])
    data='0x'+MINT_PUBLIC_SELECTOR+encode(['address','address','address','uint256'],[contract,fee_recipient,user.address,quantity]).hex()
    mint_value=price*quantity
    fee_quote=w.eth.gas_price*450000
    execution=with_gas_reimbursement({'target':SEADROP_V1_ADDRESS,'value':str(mint_value),'data':data},operator,fee_quote)
    now=w.eth.get_block('latest').timestamp
    typed=permission_typed_data(31337,user.address,operator,execution,now-1,min(now+900,end))
    sig='0x'+Account.sign_message(encode_typed_data(full_message=typed),user.key).signature.hex()
    tx={'from':operator,'to':to_checksum_address(env['manager']),'data':redeem_calldata(typed,sig,execution),'value':0,'gasPrice':w.eth.gas_price}
    gas=w.eth.estimate_gas(tx)*120//100
    assert gas*tx['gasPrice']<=fee_quote, '450,000 gas quote does not cover padded execution'
    tx['gas']=gas
    before=w.eth.get_balance(user.address)
    receipt=w.eth.wait_for_transaction_receipt(w.eth.send_transaction(tx))
    assert receipt.status==1
    assert before-w.eth.get_balance(user.address)==mint_value+fee_quote
    balance=decode(['uint256'],w.eth.call({'to':contract,'data':'0x'+(keccak(text='balanceOf(address)')[:4]+encode(['address'],[user.address])).hex()}))[0]
    assert balance==quantity
    try:
        w.eth.estimate_gas(tx)
        raise AssertionError('Replay unexpectedly succeeded')
    except AssertionError: raise
    except Exception: pass
    return {'local_only':True,'source_network':'robinhood','fork_chain_id':31337,'collection_contract':contract,'quantity_minted':quantity,'mint_value_wei':str(mint_value),'gas_reimbursement_wei':str(fee_quote),'total_user_debit_wei':str(mint_value+fee_quote),'estimated_gas_with_padding':gas,'confirmed_gas_used':receipt.gasUsed,'exact_user_debit_verified':True,'replay_rejected':True,'live_funds_spent':False}
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rpc',required=True)
    parser.add_argument('--contract',default='0xaa19274645cbfdc4de5c9c10586cbaca409b2c72')
    parser.add_argument('--quantity',type=int,default=2)
    args=parser.parse_args()
    print(json.dumps(run(args.rpc,args.contract,args.quantity),indent=2))
