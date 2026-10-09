"""Bounded gas quotes. Nitro's total gas already includes parent data fees."""
from eth_abi import encode, decode
from eth_utils import keccak, to_checksum_address

BASE_ORACLE = to_checksum_address('0x420000000000000000000000000000000000000F')


async def additional_fee(web3, chain_id, gas, transaction_size, block='pending'):
    """Base's parent data and operator fees are outside the L2 gas limit.

    Query the versioned oracle rather than hard-code a fork's fee formula.
    The upper bound includes signature bytes and pessimistic compression.
    """
    if chain_id != 8453:
        return 0
    total = 0
    for method, value in [('getL1FeeUpperBound(uint256)', transaction_size),
                          ('getOperatorFee(uint256)', gas)]:
        raw = await web3.eth.call({'to': BASE_ORACLE, 'data': keccak(text=method)[:4]
                                  + encode(['uint256'], [value])}, block)
        total += decode(['uint256'], raw)[0]
    return (total * 150 + 99) // 100


async def maximum_fee(web3, tx, chain_id, gas, price):
    data = tx['data']
    size = len(bytes.fromhex(data.removeprefix('0x')) if isinstance(data, str) else data) + 256
    return gas * price + await additional_fee(web3, chain_id, gas, size)


def number(value):
    return int(value, 16) if isinstance(value, str) and value.startswith('0x') else int(value)


async def receipt_cost(web3, receipt, chain_id, value=0):
    cost = receipt.gasUsed * receipt.effectiveGasPrice + (value if receipt.status == 1 else 0)
    if chain_id == 8453:
        if 'l1Fee' not in receipt:
            raise ValueError('Base receipt lacks parent fee accounting')
        cost += number(receipt['l1Fee'])
        if 'operatorFee' in receipt:
            cost += number(receipt['operatorFee'])
        else:
            raw = await web3.eth.call({'to': BASE_ORACLE, 'data': keccak(text='getOperatorFee(uint256)')[:4]
                + encode(['uint256'], [receipt.gasUsed])}, receipt.blockNumber)
            cost += decode(['uint256'], raw)[0]
    return cost


async def quote_gas(web3, tx, chain_id):
    import asyncio
    price, standard = await asyncio.gather(web3.eth.gas_price, web3.eth.estimate_gas(tx))
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
