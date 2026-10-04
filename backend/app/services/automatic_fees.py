"""Bounded gas quotes. Nitro's total gas already includes parent data fees."""
from eth_abi import encode, decode
from eth_utils import keccak, to_checksum_address


async def quote_gas(web3, tx, chain_id):
    price = await web3.eth.gas_price
    standard = await web3.eth.estimate_gas(tx)
    total = standard
    if chain_id == 4663:
        data = tx['data']
        data = bytes.fromhex(data.removeprefix('0x')) if isinstance(data, str) else bytes(data)
        raw = await web3.eth.call({
            'from': tx['from'], 'to': to_checksum_address('0x00000000000000000000000000000000000000c8'),
            'value': tx['value'], 'data': keccak(text='gasEstimateComponents(address,bool,bytes)')[:4]
            + encode(['address', 'bool', 'bytes'], [tx['to'], False, data])})
        nitro_total, l1_gas, base_fee, _ = decode(['uint64', 'uint64', 'uint256', 'uint256'], raw)
        if not 0 <= l1_gas <= nitro_total or nitro_total <= 0 or base_fee <= 0:
            raise ValueError('Invalid Nitro fee quote')
        total, price = max(standard, nitro_total), max(price, base_fee)
        # Base fees can move between RPC responses and sequencer acceptance.
        # Reserve modest price headroom before signing, inside the reviewed fee cap.
        price = (price * 120 + 99) // 100
    if standard <= 0 or price <= 0:
        raise ValueError('Invalid gas quote')
    return (total * 120 + 99) // 100, price
