"""One-use MetaMask delegation. User keys never reach the relayer.

ABI, EIP-712 structure and caveat terms matched against Smart Accounts Kit 2.0.0.
Only an existing EIP-7702 MetaMask account and an exact public mint are accepted.
"""
import json
import secrets
from pathlib import Path
from eth_abi import decode, encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address
from web3 import AsyncWeb3
from app.config import settings
from app.services.opensea import CHAINS, OpenSeaUnavailable, chain_rpc, transaction_value_wei
from app.services.signer.base import SEADROP_V1_ADDRESS, MINT_PUBLIC_SELECTOR
from app.services.mint_plans import aware

REGISTRY = json.loads(Path(__file__).with_name('delegation_registry.json').read_text())['chains']
DELEGATION_TYPE = '(address,address,bytes32,(address,bytes,bytes)[],uint256,bytes)[]'
TYPES = {
    'Caveat': [{'name': 'enforcer', 'type': 'address'}, {'name': 'terms', 'type': 'bytes'}],
    'Delegation': [{'name': 'delegate', 'type': 'address'}, {'name': 'delegator', 'type': 'address'},
                   {'name': 'authority', 'type': 'bytes32'}, {'name': 'caveats', 'type': 'Caveat[]'},
                   {'name': 'salt', 'type': 'uint256'}],
}

def relayer_account():
    """Operator's gas wallet only. Never accept a user's private key."""
    try:
        return Account.from_key(Path(settings.MINT_RELAYER_KEY_FILE).read_text().strip())
    except (OSError, ValueError):
        raise OpenSeaUnavailable('Automatic minting is not configured: operator relayer unavailable.', 409)

def public_mint_execution(tx, contract, wallet, quantity):
    data = tx.get('data', '')
    if tx.get('to', '').lower() != SEADROP_V1_ADDRESS.lower() or data[:10].lower() != '0x' + MINT_PUBLIC_SELECTOR:
        raise OpenSeaUnavailable('Automatic permission currently supports SeaDrop public mint calls only.', 409)
    try:
        raw = bytes.fromhex(data[10:])
        # OpenSea's SIP-6 domain attribution follows the four static ABI words.
        # Keep the known suffix in the exact signed execution; reject other tails.
        if len(raw) != 128 and not (len(raw) == 132 and raw[128:] == bytes.fromhex('3d958fe2')):
            raise ValueError()
        nft, fee, recipient, count = decode(['address','address','address','uint256'], raw[:128])
        if nft.lower() != contract.lower() or count != quantity or recipient.lower() not in (wallet.lower(), '0x' + '0'*40):
            raise ValueError()
    except Exception as error:
        raise OpenSeaUnavailable('Mint calldata does not match the collection, recipient and quantity.', 409) from error
    return {'target': to_checksum_address(tx['to']), 'value': str(transaction_value_wei(tx['value'])), 'data': data}

def exact_execution_bytes(execution):
    return bytes.fromhex(execution['target'][2:]) + int(execution['value']).to_bytes(32,'big') + bytes.fromhex(execution['data'][2:])

def batch_execution_bytes(execution):
    fee = execution['gas_reimbursement']
    return encode(['(address,uint256,bytes)[]'], [[
        (execution['target'], int(execution['value']), bytes.fromhex(execution['data'][2:])),
        (fee['target'], int(fee['value']), b'')]])


def with_gas_reimbursement(execution, operator, fee):
    if fee <= 0 or fee > settings.MINT_RELAYER_MAX_FEE_WEI:
        raise OpenSeaUnavailable('Gas quote exceeds the automatic mint fee cap. Try again later.',409)
    return {**execution, 'gas_reimbursement': {'target':to_checksum_address(operator),'value':str(fee)}}


def total_user_debit(execution):
    return int(execution['value']) + int(execution.get('gas_reimbursement',{}).get('value',0))


async def scheduled_public_execution(web3,plan,wallet):
    """Cross-check future OpenSea public-stage metadata against SeaDrop on-chain."""
    address_arg=encode(['address'],[plan.contract_address])
    raw=await web3.eth.call({'to':to_checksum_address(SEADROP_V1_ADDRESS),'data':'0x'+(keccak(text='getPublicDrop(address)')[:4]+address_arg).hex()})
    price,start,end,limit,fee_bps,restricted=decode(['uint80','uint48','uint48','uint16','uint16','bool'],raw)
    if price!=plan.price_wei or start!=int(aware(plan.starts_at).timestamp()) or end!=int(aware(plan.ends_at).timestamp()) or plan.quantity>limit:
        raise OpenSeaUnavailable('OpenSea public stage does not match the on-chain mint schedule, price or quantity limit.',409)
    raw=await web3.eth.call({'to':to_checksum_address(SEADROP_V1_ADDRESS),'data':'0x'+(keccak(text='getAllowedFeeRecipients(address)')[:4]+address_arg).hex()})
    recipients=decode(['address[]'],raw)[0]
    recipients=[address for address in recipients if address.lower()!='0x'+'0'*40]
    if not recipients and (restricted or fee_bps):
        raise OpenSeaUnavailable('A future mint fee recipient could not be verified. Check the mint again when the stage opens.',409)
    recipient=recipients[0] if recipients else '0x'+'0'*40
    data='0x'+MINT_PUBLIC_SELECTOR+encode(['address','address','address','uint256'],[plan.contract_address,recipient,wallet.address,plan.quantity]).hex()
    value=price*plan.quantity
    transaction_value_wei(str(value))
    if await web3.eth.get_balance(to_checksum_address(wallet.address))<value:
        raise OpenSeaUnavailable('Your linked wallet needs the mint value on this network before authorizing.',409)
    return {'chain':next(chain for chain,info in CHAINS.items() if info[0]==plan.chain_id),'to':SEADROP_V1_ADDRESS,'data':data,'value':str(value)}

def permission_typed_data(chain_id, wallet, delegate, execution, after, expiry, salt=None):
    env = REGISTRY[str(chain_id)]
    enforcers = env['enforcers']
    batch = 'gas_reimbursement' in execution
    terms = [batch_execution_bytes(execution) if batch else exact_execution_bytes(execution), int(after).to_bytes(16,'big') + int(expiry).to_bytes(16,'big'), (1).to_bytes(32,'big')]
    caveats = [{'enforcer': enforcers[name], 'terms': '0x'+term.hex()} for name,term in zip(
        ['ExactExecutionBatchEnforcer' if batch else 'ExactExecutionEnforcer','TimestampEnforcer','LimitedCallsEnforcer'], terms)]
    return {
        'domain': {'name':'DelegationManager','version':'1','chainId':chain_id,'verifyingContract':env['manager']},
        'primaryType': 'Delegation', 'types': TYPES,
        'message': {'delegate':delegate, 'delegator':wallet, 'authority':'0x'+'ff'*32,
                    'caveats':caveats, 'salt':str(salt if salt is not None else secrets.randbits(256))},
    }

def validate_signature(typed, signature, wallet):
    try:
        recovered = Account.recover_message(encode_typed_data(full_message=typed), signature=signature)
        if recovered.lower() != wallet.lower():
            raise ValueError()
    except Exception as error:
        raise OpenSeaUnavailable('Permission signature does not match the linked wallet.',400) from error

def redeem_calldata(typed, signature, execution):
    msg = typed['message']
    caveats = [(c['enforcer'], bytes.fromhex(c['terms'][2:]), b'\x00') for c in msg['caveats']]
    signed = (msg['delegate'],msg['delegator'],bytes.fromhex(msg['authority'][2:]),caveats,int(msg['salt']),bytes.fromhex(signature[2:]))
    context = encode([DELEGATION_TYPE], [[signed]])
    selector = keccak(text='redeemDelegations(bytes[],bytes32[],bytes[])')[:4]
    batch = 'gas_reimbursement' in execution
    mode = bytes.fromhex('01'+'00'*31) if batch else bytes(32)
    calls = batch_execution_bytes(execution) if batch else exact_execution_bytes(execution)
    return '0x'+(selector+encode(['bytes[]','bytes32[]','bytes[]'],[[context],[mode],[calls]])).hex()

def revoke_calldata(typed, signature):
    msg=typed['message']
    caveats=[(c['enforcer'],bytes.fromhex(c['terms'][2:]),b'\x00') for c in msg['caveats']]
    signed=(msg['delegate'],msg['delegator'],bytes.fromhex(msg['authority'][2:]),caveats,int(msg['salt']),bytes.fromhex(signature[2:]))
    tuple_type=DELEGATION_TYPE[:-2]
    selector=keccak(text='disableDelegation((address,address,bytes32,(address,bytes,bytes)[],uint256,bytes))')[:4]
    return '0x'+(selector+encode([tuple_type],[signed])).hex()

async def checked_provider(chain, wallet):
    provider = AsyncWeb3.AsyncHTTPProvider(chain_rpc(chain), request_kwargs={'timeout':10})
    web3 = AsyncWeb3(provider)
    try:
        env = REGISTRY[str(CHAINS[chain][0])]
        if await web3.eth.chain_id != CHAINS[chain][0]:
            raise OpenSeaUnavailable('RPC network could not be verified.',409)
        code = bytes(await web3.eth.get_code(to_checksum_address(wallet)))
        expected = bytes.fromhex('ef0100' + env['implementation'][2:])
        if code != expected:
            raise OpenSeaUnavailable('This address is not an enabled compatible MetaMask Smart Account on this network. Mintly will not upgrade your account automatically.',409)
        for address in [SEADROP_V1_ADDRESS,env['manager'],env['implementation'],*env['enforcers'].values()]:
            if not await web3.eth.get_code(to_checksum_address(address)):
                raise OpenSeaUnavailable('Required permission contracts are unavailable on this network.',409)
        return web3
    except Exception:
        await provider.disconnect()
        raise
