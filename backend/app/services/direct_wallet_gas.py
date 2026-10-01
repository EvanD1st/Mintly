"""Owner-approved ERC-4337 v0.7 operations. No user key or operator gas wallet."""
import json
import secrets
from pathlib import Path

import aiohttp
from eth_abi import encode, decode
from eth_utils import keccak, to_checksum_address

from app.config import settings
from app.services.mint_permission import REGISTRY, redeem_calldata, exact_execution_bytes, validate_signature
from app.services.opensea import OpenSeaUnavailable

ENTRY_POINT = '0x0000000071727De22E5E9d8BAf0edAc6f37da032'
FIELDS = [('sender','address'), ('nonce','uint256'), ('initCode','bytes'),
          ('callData','bytes'), ('accountGasLimits','bytes32'),
          ('preVerificationGas','uint256'), ('gasFees','bytes32'),
          ('paymasterAndData','bytes'), ('entryPoint','address')]


class Bundler:
    def __init__(self, chain_id):
        self.chain_id = chain_id
        try:
            self.url = json.loads(Path(settings.MINT_BUNDLER_CONFIG_FILE).read_text())[str(chain_id)]
            if not self.url.startswith('https://'):
                raise ValueError()
        except (OSError, KeyError, ValueError, TypeError):
            raise OpenSeaUnavailable('Direct wallet gas needs a configured bundler for this network.', 409) from None

    async def call(self, method, params):
        try:
            # aiohttp does not emit HTTPX's INFO request log, which would include
            # the API key embedded in this URL under the worker's INFO logging.
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=False) as client:
                async with client.post(self.url,json={'jsonrpc':'2.0','id':1,'method':method,'params':params},allow_redirects=False) as response:
                    if response.status!=200:raise ValueError()
                    raw=await response.content.read(256*1024+1)
                    if len(raw)>256*1024:raise ValueError()
                    result=json.loads(raw)
                    if not isinstance(result,dict) or 'error' in result or 'result' not in result:
                        raise ValueError()
                    return result['result']
        except Exception:
            # URLs can contain API keys; upstream exceptions must never escape.
            raise OpenSeaUnavailable('Bundler request failed. No replacement operation was authorized.', 409) from None

    async def verify(self):
        chain = await self.call('eth_chainId', [])
        if int(chain,16) != self.chain_id:
            raise OpenSeaUnavailable('Bundler network does not match the mint network.',409)
        points = await self.call('eth_supportedEntryPoints', [])
        if not isinstance(points,list) or ENTRY_POINT.lower() not in [str(p).lower() for p in points]:
            raise OpenSeaUnavailable('Bundler does not support the wallet EntryPoint.',409)


def pair(high, low):
    return '0x' + (int(high).to_bytes(16,'big') + int(low).to_bytes(16,'big')).hex()


def packed(op):
    return (op['sender'],int(op['nonce'],16),b'',bytes.fromhex(op['callData'][2:]),
            bytes.fromhex(pair(int(op['verificationGasLimit'],16),int(op['callGasLimit'],16))[2:]),
            int(op['preVerificationGas'],16),bytes.fromhex(pair(int(op['maxPriorityFeePerGas'],16),int(op['maxFeePerGas'],16))[2:]),
            b'',bytes.fromhex(op['signature'][2:]))


def userop_typed_data(chain_id, op):
    p = packed(op)
    values = [p[0],str(p[1]),'0x','0x'+p[3].hex(),'0x'+p[4].hex(),str(p[5]),'0x'+p[6].hex(),'0x',ENTRY_POINT]
    return {'domain':{'name':'EIP7702StatelessDeleGator','version':'1','chainId':chain_id,'verifyingContract':op['sender']},
            'primaryType':'PackedUserOperation','types':{'PackedUserOperation':[{'name':n,'type':t} for n,t in FIELDS]},
            'message':dict(zip([n for n,t in FIELDS],values))}


def maximum_gas(op):
    return sum(int(op[k],16) for k in ['verificationGasLimit','callGasLimit','preVerificationGas']) * int(op['maxFeePerGas'],16)


def mint_call(typed, signature, execution):
    # The account calls the manager as itself. A self-delegation enforces time,
    # exact mint and single use without granting another key spending authority.
    call = {'target':typed['domain']['verifyingContract'],'value':'0','data':redeem_calldata(typed,signature,execution)}
    return '0x' + (keccak(text='execute(bytes32,bytes)')[:4] + encode(['bytes32','bytes'],[bytes(32),exact_execution_bytes(call)])).hex()


async def verify_account(web3, wallet):
    raw = await web3.eth.call({'to':to_checksum_address(wallet),'data':'0x'+keccak(text='entryPoint()')[:4].hex()})
    if decode(['address'],raw)[0].lower() != ENTRY_POINT.lower() or not await web3.eth.get_code(ENTRY_POINT):
        raise OpenSeaUnavailable('Wallet EntryPoint is incompatible with direct gas payment.',409)


async def quote_operation(web3, chain_id, wallet):
    await verify_account(web3,wallet)
    bundler = Bundler(chain_id)
    await bundler.verify()
    key = secrets.randbits(192)
    data = keccak(text='getNonce(address,uint192)')[:4] + encode(['address','uint192'],[wallet,key])
    nonce = decode(['uint256'],await web3.eth.call({'to':ENTRY_POINT,'data':'0x'+data.hex()}))[0]
    # Conservative, bounded limits; signed operation is estimated at execution.
    # Future stage calldata cannot be simulated before that stage opens.
    price = int(await web3.eth.gas_price)
    try:
        tip = int(await bundler.call('rundler_maxPriorityFeePerGas',[]),16)
    except (OpenSeaUnavailable,ValueError,TypeError):
        raise OpenSeaUnavailable('Bundler priority-fee quote unavailable. Try again later.',409) from None
    op = {'sender':to_checksum_address(wallet),'nonce':hex(nonce),'callData':'0x',
          'callGasLimit':hex(600000),'verificationGasLimit':hex(150000),
          'preVerificationGas':hex(100000),'maxFeePerGas':hex(max(price*2,tip*2)),
          'maxPriorityFeePerGas':hex(max(price,tip)),'signature':'0x'}
    if price <= 0 or maximum_gas(op) > settings.MINT_RELAYER_MAX_FEE_WEI:
        raise OpenSeaUnavailable('Direct wallet gas ceiling exceeds the configured cap. Try a fresh quote later.',409)
    return op


def operation_hash(op, chain_id):
    p = packed(op)
    inner = keccak(encode(['address','uint256','bytes32','bytes32','bytes32','uint256','bytes32','bytes32'],
                         [p[0],p[1],keccak(p[2]),keccak(p[3]),p[4],p[5],p[6],keccak(p[7])]))
    return '0x'+keccak(encode(['bytes32','address','uint256'],[inner,ENTRY_POINT,chain_id])).hex()


def validate_operation(p, chain_id, wallet):
    stored = p.execution['direct_gas']
    op = stored['operation']
    if op['sender'].lower()!=wallet.lower() or p.typed_data['message']['delegate'].lower()!=wallet.lower():
        raise ValueError('Wallet mismatch')
    if p.typed_data['domain']['chainId']!=chain_id or p.typed_data['domain']['verifyingContract'].lower()!=REGISTRY[str(chain_id)]['manager'].lower():
        raise ValueError('Domain mismatch')
    if set(op)!= {'sender','nonce','callData','callGasLimit','verificationGasLimit','preVerificationGas','maxFeePerGas','maxPriorityFeePerGas','signature'}:
        raise ValueError('Unexpected operation fields')
    if maximum_gas(op)!=int(stored['max_gas_wei']) or maximum_gas(op)>settings.MINT_RELAYER_MAX_FEE_WEI:
        raise ValueError('Gas cap mismatch')
    if op['callData']!=mint_call(p.typed_data,p.signature,p.execution):
        raise ValueError('Execution mismatch')
    validate_signature(p.typed_data,p.signature,wallet)
    validate_signature(userop_typed_data(chain_id,op),op['signature'],wallet)
    return op
