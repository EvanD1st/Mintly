"""Independently authenticated source mint intents; contains no receiving-wallet keys."""
from datetime import datetime, timezone
from eth_account import Account
from eth_account._utils.legacy_transactions import serializable_unsigned_transaction_from_dict, encode_transaction
from eth_abi import decode
from eth_utils import keccak, to_checksum_address
from hexbytes import HexBytes
from web3.exceptions import TransactionNotFound
from app.services.signer.base import SEADROP_V1_ADDRESS
from app.services.seadrop_mint import decode_mint, verify_presale


class PendingSourceChanged(ValueError):
    message = ('The followed wallet’s pending mint is no longer valid or could not be verified. '
               'This copy was stopped before signing. No transaction was sent.')


def number(value):
    return int.from_bytes(value,'big') if isinstance(value,bytes) else int(value,0) if isinstance(value,str) else int(value)


def signed_identity(tx, chain):
    """Rebuild the signed envelope: an RPC's claimed sender alone is insufficient."""
    kind = number(tx.get('type', 0))
    if kind not in (0, 1, 2, 4):
        raise ValueError('Unsupported pending source transaction type')
    fields = ('nonce', 'gas', 'value')
    envelope = {key: int(tx[key]) for key in fields}
    envelope.update(to=to_checksum_address(tx['to']), data=HexBytes(tx.get('input', tx.get('data', b''))))
    if kind == 0:
        v = int(tx['v'])
        if v < 35 or (v - 35) // 2 != chain:
            raise ValueError('Pending source lacks the approved replay-protected network')
        envelope.update(chainId=chain, gasPrice=int(tx['gasPrice']))
    else:
        if int(tx['chainId']) != chain:
            raise ValueError('Pending source network differs')
        envelope.update(type=kind, chainId=chain, accessList=tx.get('accessList', []))
        if kind == 1:
            envelope['gasPrice'] = int(tx['gasPrice'])
        else:
            envelope.update(maxFeePerGas=int(tx['maxFeePerGas']), maxPriorityFeePerGas=int(tx['maxPriorityFeePerGas']))
        if kind == 4:
            envelope['authorizationList'] = tx['authorizationList']
    v,r,s = (number(tx[k]) for k in ('v','r','s'))
    if not 0<r<2**256 or not 0<s<=0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0 or (kind and v not in (0,1)):
        raise ValueError('Pending source signature is not canonical')
    raw = encode_transaction(serializable_unsigned_transaction_from_dict(envelope),(v,r,s))
    if keccak(raw) != HexBytes(tx['hash']):
        raise ValueError('Pending source transaction hash differs from its signature')
    sender = Account.recover_transaction(raw)
    if sender.lower() != tx['from'].lower():
        raise ValueError('Pending source sender differs from its signature')
    return sender


def after_approval(source, after_block, approved_at, verified=None):
    if source.get('source_pending') is True:
        if verified is not None and verified.get('source_block_number') is not None:
            return verified['source_block_number'] > after_block
        return (type(source.get('seen_block')) is int and source['seen_block'] > after_block
            and type(source.get('seen_at')) is int and source['seen_at'] >= approved_at)
    return source['block_number'] > after_block


async def observe(web3, chain, tx_hash, source, contract):
    from app.services import copy_mints
    tx = await web3.eth.get_transaction(tx_hash)
    if tx.get('blockHash') is not None:
        raise ValueError('Source is already included; confirmed discovery will handle it')
    sender = signed_identity(tx, chain)
    if sender.lower() != source.lower():
        raise ValueError('Pending source is not the followed wallet')
    data = HexBytes(tx.get('input', tx.get('data', b'')))
    values = decode(['address', 'address', 'address', 'uint256'], data[4:132])
    mint = decode_mint({'to': tx['to'], 'data': data.hex() if data.hex().startswith('0x') else '0x'+data.hex(),
        'value': str(tx['value'])}, contract, sender, values[3])
    head = await web3.eth.get_block('latest')
    stage = await copy_mints.public_stage(web3, contract) if mint['kind'] == 'public' else dict(
        price_wei=mint['params'][0], start=mint['params'][2], end=mint['params'][3],
        limit=mint['params'][1], onchain_stage_index=mint['params'][4])
    result = dict(chain_id=chain, chain=copy_mints.CHAINS[chain], contract=to_checksum_address(contract),
        source_hash=tx_hash, source_address=sender, source_quantity=values[3], source_nonce=int(tx['nonce']),
        source_pending=True, seen_block=head.number, seen_at=int(datetime.now(timezone.utc).timestamp()),
        block_number=None, block_hash=None, timestamp=int(datetime.now(timezone.utc).timestamp()),
        mint_kind=mint['kind'], name='Collection '+contract[:8], **stage)
    await verify(web3, result)
    return result


async def verify(web3, source):
    """Both observer and isolated signer independently verify the same signed intent."""
    from app.services import copy_mints
    chain = source['chain_id']
    try:
        tx = await web3.eth.get_transaction(source['source_hash'])
    except TransactionNotFound:
        if int(datetime.now(timezone.utc).timestamp())-source['seen_at']>300:
            raise ValueError('Pending source disappeared') from None
        raise
    sender = signed_identity(tx, chain)
    if (sender.lower() != source['source_address'].lower() or int(tx['nonce']) != source['source_nonce']
            or HexBytes(tx['hash']) != HexBytes(source['source_hash'])):
        raise ValueError('Pending source identity changed')
    mint = decode_mint({'to': tx['to'], 'data': '0x'+HexBytes(tx.get('input', tx.get('data', b''))).hex().removeprefix('0x'),
        'value': str(tx['value'])}, source['contract'], sender, source['source_quantity'])
    if mint['kind'] != source.get('mint_kind', 'public'):
        raise ValueError('Pending source method changed')
    if tx.get('blockHash') is not None:
        receipt = await web3.eth.get_transaction_receipt(source['source_hash'])
        block = await web3.eth.get_block(receipt.blockNumber)
        verified = await copy_mints.verify_source(web3, {**source, 'source_pending': False,
            'block_number': receipt.blockNumber, 'block_hash': copy_mints.hex_value(receipt.blockHash),
            'timestamp': block.timestamp}, minimum_confirmations=1)
        return {**verified, 'source_block_number':receipt.blockNumber}
    try:
        receipt = await web3.eth.get_transaction_receipt(source['source_hash'])
    except TransactionNotFound:
        receipt = None
    if receipt is not None:
        raise ValueError('Pending source inclusion changed during validation')
    wall = int(datetime.now(timezone.utc).timestamp())
    head = await web3.eth.get_block('latest')
    now = max(wall, head.timestamp)
    if not 0 <= wall-source['seen_at'] <= 300:
        raise ValueError('Pending mint activity is stale')
    if not 0 <= source['seen_block'] <= head.number:
        raise ValueError('Pending source observation head differs from the network')
    if await web3.eth.get_transaction_count(sender, 'latest') != int(tx['nonce']):
        raise ValueError('Pending source nonce is no longer executable')
    stage = await copy_mints.public_stage(web3, source['contract']) if mint['kind'] == 'public' else dict(
        price_wei=mint['params'][0], start=mint['params'][2], end=mint['params'][3])
    if (any(stage[k] != source[k] for k in ('price_wei', 'start', 'end'))
            or int(tx['value']) != stage['price_wei'] * source['source_quantity']
            or not stage['start'] <= now < stage['end']
            or (mint['kind'] != 'public' and mint['params'][4] != source['onchain_stage_index'])):
        raise ValueError('Pending source stage or price changed')
    await verify_presale(web3, mint)
    # A successful simulation does not guarantee eventual inclusion; it rejects
    # already-invalid source attempts before any receiving-wallet signature.
    await web3.eth.call({'from': sender, 'to': SEADROP_V1_ADDRESS, 'data': tx.get('input', tx.get('data')),
        'value': int(tx['value']), 'gas': int(tx['gas'])}, 'latest')
    return mint
