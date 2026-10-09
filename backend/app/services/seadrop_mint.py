"""Exact SeaDrop public, Merkle allowlist and signed-presale validation.

Never infer eligibility from a stage label or a successful upstream response.
"""
from datetime import timezone
from eth_abi import decode, encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address

from app.services.opensea import OpenSeaUnavailable, transaction_value_wei
from app.services.signer.base import SEADROP_V1_ADDRESS, MINT_PUBLIC_SELECTOR

PARAM_NAMES = ['mintPrice','maxTotalMintableByWallet','startTime','endTime',
               'dropStageIndex','maxTokenSupplyForStage','feeBps','restrictFeeRecipients']
PARAM_TYPE = '(' + ','.join(['uint256']*7+['bool']) + ')'
ALLOW_SIGNATURE = f'mintAllowList(address,address,address,uint256,{PARAM_TYPE},bytes32[])'
SIGNED_SIGNATURE = f'mintSigned(address,address,address,uint256,{PARAM_TYPE},uint256,bytes)'
ALLOW_SELECTOR = keccak(text=ALLOW_SIGNATURE)[:4].hex()
SIGNED_SELECTOR = keccak(text=SIGNED_SIGNATURE)[:4].hex()
BASE_TYPES = ['address','address','address','uint256']
SIGNED_TYPES = {'MintParams':[{'name':n,'type':'bool' if n=='restrictFeeRecipients' else 'uint256'} for n in PARAM_NAMES],
                'SignedMint':[{'name':'nftContract','type':'address'},{'name':'minter','type':'address'},
                              {'name':'feeRecipient','type':'address'},{'name':'mintParams','type':'MintParams'},
                              {'name':'salt','type':'uint256'}]}


def decode_mint(tx,contract,wallet,quantity):
    try:
        if tx['to'].lower()!=SEADROP_V1_ADDRESS.lower() or not 1<=quantity<=100:
            raise ValueError()
        data=bytes.fromhex(tx['data'][2:])
        selector=data[:4].hex()
        kind,types = {
            MINT_PUBLIC_SELECTOR:('public',BASE_TYPES),
            ALLOW_SELECTOR:('allowlist',BASE_TYPES+[PARAM_TYPE,'bytes32[]']),
            SIGNED_SELECTOR:('signed',BASE_TYPES+[PARAM_TYPE,'uint256','bytes']),
        }[selector]
        values=decode(types,data[4:])
        canonical=encode(types,values)
        if data[4:] not in (canonical,canonical+bytes.fromhex('3d958fe2')):
            raise ValueError()
        nft,fee,recipient,count=values[:4]
        if nft.lower()!=contract.lower() or count!=quantity or recipient.lower() not in (wallet.lower(),'0x'+'0'*40):
            raise ValueError()
        value=transaction_value_wei(tx['value'])
        params=values[4] if kind!='public' else None
        if params:
            price,limit,start,end,index,supply,bps,restricted=params
            if (value!=price*quantity or limit<quantity or not 0<start<end or index==0 or supply<quantity or bps>10000):
                raise ValueError()
        return {'kind':kind,'contract':to_checksum_address(nft),'wallet':to_checksum_address(wallet),
                'fee':to_checksum_address(fee),'quantity':quantity,'params':params,
                'proof':values[5] if kind=='allowlist' else None,
                'salt':values[5] if kind=='signed' else None,
                'signature':values[6] if kind=='signed' else None,
                'execution':{'target':to_checksum_address(tx['to']),'value':str(value),'data':tx['data']}}
    except Exception as error:
        # Decode errors have multiple exception classes; no calldata/proof leaks.
        raise OpenSeaUnavailable('Mint calldata does not match a supported SeaDrop mint, wallet, quantity or price.',409) from error


def match_stage(mint,stages):
    if mint['kind']=='public':
        candidates=[s for s in stages if s['type']=='public_sale']
    else:
        p=mint['params']
        candidates=[s for s in stages if s['type']!='public_sale'
                    and int(s['starts_at'].timestamp())==p[2] and int(s['ends_at'].timestamp())==p[3]
                    and s['price_wei']==p[0]]
    if len(candidates)!=1:
        raise OpenSeaUnavailable('The exact eligible mint stage could not be identified. Refresh the drop.',409)
    return candidates[0]


def signed_mint_typed_data(mint,chain_id):
    return {'domain':{'name':'SeaDrop','version':'1.0','chainId':chain_id,'verifyingContract':SEADROP_V1_ADDRESS},
            'primaryType':'SignedMint','types':SIGNED_TYPES,
            'message':{'nftContract':mint['contract'],'minter':mint['wallet'],'feeRecipient':mint['fee'],
                       'mintParams':dict(zip(PARAM_NAMES,mint['params'])),'salt':mint['salt']}}


async def verify_presale(web3,mint,stage=None):
    if mint['kind']=='public':return
    p=mint['params'];contract=mint['contract'];wallet=mint['wallet']
    unix=lambda value:int((value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).timestamp())
    if stage and (unix(stage.starts_at)!=p[2] or unix(stage.ends_at)!=p[3] or stage.price_wei!=p[0] or stage.stage_type=='public_sale'):
        raise OpenSeaUnavailable('Allowlist mint does not match the approved stage.',409)
    async def read(signature,types,args,outputs,to=SEADROP_V1_ADDRESS):
        data=keccak(text=signature)[:4]+encode(types,args)
        return decode(outputs,await web3.eth.call({'to':to_checksum_address(to),'data':'0x'+data.hex()}))
    try:
        if mint['kind']=='allowlist':
            proof=mint['proof']
            if len(proof)>64:raise ValueError()
            root=(await read('getAllowListMerkleRoot(address)',['address'],[contract],['bytes32']))[0]
            leaf=keccak(encode(['address',PARAM_TYPE],[wallet,p]))
            for sibling in proof:leaf=keccak(min(leaf,sibling)+max(leaf,sibling))
            if root==bytes(32) or leaf!=root:raise ValueError()
        else:
            sig=mint['signature']
            if len(sig)!=65 or sig[64] not in (27,28) or not 0<int.from_bytes(sig[32:64],'big')<=0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0:
                raise ValueError()
            signer=Account.recover_message(encode_typed_data(full_message=signed_mint_typed_data(mint,await web3.eth.chain_id)),signature=sig)
            bounds=await read('getSignedMintValidationParams(address,address)',['address','address'],[contract,signer],['uint80','uint24','uint40','uint40','uint40','uint16','uint16'])
            if not (bounds[1]>0 and p[0]>=bounds[0] and p[1]<=bounds[1] and p[2]>=bounds[2] and p[3]<=bounds[3]
                    and p[5]<=bounds[4] and bounds[5]<=p[6]<=bounds[6] and p[7]):raise ValueError()
        if int(mint['fee'],16)==0:raise ValueError()
        if p[7] and not (await read('getFeeRecipientIsAllowed(address,address)',['address','address'],[contract,mint['fee']],['bool']))[0]:raise ValueError()
        minted,total,max_supply=await read('getMintStats(address)',['address'],[wallet],['uint256']*3,to=contract)
        if minted+mint['quantity']>p[1] or total+mint['quantity']>min(max_supply,p[5]):raise ValueError()
        if int(mint['execution']['value']) and int((await read('getCreatorPayoutAddress(address)',['address'],[contract],['address']))[0],16)==0:raise ValueError()
        block=await web3.eth.get_block('latest')
        if p[2]<=block['timestamp']<=p[3]:
            # Also detects consumed signed-mint digests and live NFT/payout
            # restrictions without broadcasting or changing chain state.
            from app.services.automatic_fees import quote_gas
            tx={'from':wallet,'to':SEADROP_V1_ADDRESS,
                'data':mint['execution']['data'],'value':int(mint['execution']['value'])}
            gas,_=await quote_gas(web3,tx,await web3.eth.chain_id)
            await web3.eth.call({**tx,'gas':gas},'pending')
    except Exception as error:
        raise OpenSeaUnavailable('Wallet allowlist proof or presale signature, limits, supply or fee rules could not be verified on-chain.',409) from error


async def verified_mint_execution(web3,tx,plan,wallet):
    mint=decode_mint(tx,plan.contract_address,wallet.address,plan.quantity)
    await verify_presale(web3,mint,plan)
    return mint['execution']
