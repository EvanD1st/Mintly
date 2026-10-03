"""Read-only Robinhood SeaDrop quote. Never imports keys, signs, arms or broadcasts.

Supply a fresh ETH/USD reference price. A USD estimate is not an on-chain USD cap.
"""
import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
import json
from pathlib import Path

from eth_abi import encode, decode
from eth_utils import keccak, to_checksum_address
from web3 import AsyncWeb3

from app.services.automatic import prepare_mint
from app.services.opensea import collection_slug
from app.services.signer.base import SEADROP_V1_ADDRESS

RPC = 'https://rpc.mainnet.chain.robinhood.com'
NODE_INTERFACE = '0x00000000000000000000000000000000000000C8'
# Address returned by the OpenSea Drops API for this exact slug on 2026-10-02.
PINNED_COLLECTIONS = {'robinhood-ape-club-449348279': '0xaa19274645cbfdc4de5c9c10586cbaca409b2c72'}


def usd_cap_wei(max_usd, eth_usd):
    maximum, price = Decimal(max_usd), Decimal(eth_usd)
    if not maximum.is_finite() or not price.is_finite() or maximum <= 0 or price <= 0:
        raise ValueError('A positive finite USD cap and ETH/USD price are required.')
    result = int((maximum / price * 10**18).to_integral_value(rounding=ROUND_FLOOR))
    if not 0 < result < 2**63:
        raise ValueError('USD cap is outside the supported exact-wei range.')
    return result


def padded_gas(standard, total, l1):
    if not 0 <= l1 <= total or total <= 0 or standard <= 0:
        raise ValueError('Invalid Nitro gas components.')
    # Both estimates already include parent-chain data gas. Do not add it twice.
    return (max(standard, total) * 120 + 99) // 100


async def check(url, wallet, max_usd, eth_usd):
    slug, wallet = collection_slug(url), to_checksum_address(wallet)
    cap = usd_cap_wei(max_usd, eth_usd)
    if slug not in PINNED_COLLECTIONS:
        raise ValueError('This read-only probe requires a verified collection address binding.')
    contract = to_checksum_address(PINNED_COLLECTIONS[slug])
    web3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(RPC, request_kwargs={'timeout': 12}))
    try:
        if await web3.eth.chain_id != 4663:
            raise ValueError('RPC chain mismatch.')
        block = await web3.eth.get_block('latest')
        raw = await web3.eth.call({'to': SEADROP_V1_ADDRESS,
            'data': keccak(text='getPublicDrop(address)')[:4] + encode(['address'], [contract])})
        mint_price, start, end, limit, bps, restricted = decode(
            ['uint80','uint48','uint48','uint16','uint16','bool'], raw)
        snapshot = {'contract': contract, 'account': wallet, 'recipient': wallet,
            'chain_id': 4663, 'quantity': 1, 'mint_kind': 'public',
            'price_wei': mint_price, 'price_cap_wei': mint_price, 'start': start, 'end': end}
        if not snapshot['start'] <= block.timestamp < snapshot['end']:
            raise ValueError('The matched mint stage is not open.')
        execution = await prepare_mint(web3, snapshot)
        code = bytes(await web3.eth.get_code(wallet))
        balance = await web3.eth.get_balance(wallet, 'pending')
        call = {'from': wallet, 'to': execution['target'], 'data': execution['data'],
                'value': int(execution['value'])}
        await web3.eth.call(call, 'pending')
        standard = await web3.eth.estimate_gas(call)
        components = await web3.eth.call({
            'from': wallet, 'to': to_checksum_address(NODE_INTERFACE), 'value': call['value'],
            'data': keccak(text='gasEstimateComponents(address,bool,bytes)')[:4] +
                encode(['address','bool','bytes'], [call['to'], False, bytes.fromhex(call['data'][2:])]),
        })
        total, l1, base_fee, l1_base_fee = decode(['uint64','uint64','uint256','uint256'], components)
        price = max(await web3.eth.gas_price, base_fee)
        if price <= 0:
            raise ValueError('Invalid gas price.')
        gas_limit = padded_gas(standard, total, l1)
        max_fee, max_total = gas_limit * price, call['value'] + gas_limit * price
        eth_price = Decimal(eth_usd)
        in_usd = lambda value: str(Decimal(value) * eth_price / Decimal(10**18))
        return {
            'checked_at': datetime.now(timezone.utc).isoformat(), 'mode': 'read_only_preflight',
            'collection_url': url, 'collection_contract': contract,
            'wallet': wallet, 'chain_id': 4663, 'reference_block': block.number,
            'quantity': 1, 'stage': 'Public stage', 'mint_kind': 'public',
            'mint_value_wei': str(call['value']), 'mint_usd_estimate': in_usd(call['value']),
            'eth_usd_reference': str(eth_price), 'requested_max_usd': str(max_usd),
            'reference_price_cap_wei': str(cap), 'gas_limit_with_padding': gas_limit,
            'gas_price_wei': str(price), 'l1_data_gas_included': l1,
            'l1_base_fee_estimate': str(l1_base_fee), 'max_gas_fee_wei': str(max_fee),
            'max_total_wei': str(max_total), 'max_total_usd_at_reference_price': in_usd(max_total),
            'fits_reference_price_cap': max_total <= cap, 'has_funds': balance >= max_total,
            'simulation_succeeded': True, 'account_code': '0x' + code.hex(),
            'account_type': 'eip7702_delegated' if code.startswith(bytes.fromhex('ef0100')) else 'contract' if code else 'eoa',
            'automatic_ready': False,
            'automatic_blockers': ['Read-only probe does not verify a provisioned custody policy or running services.'] +
                (['Delegated account requires an independently pinned eip7702-direct policy.'] if code else []),
            'signed': False, 'broadcast': False,
            'quote_notice': 'Snapshot only. Refresh price, eligibility and gas before any user submission. ETH/USD changes can change dollar cost.',
        }
    finally:
        await web3.provider.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--wallet', required=True)
    parser.add_argument('--max-usd', required=True)
    parser.add_argument('--eth-usd', required=True)
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        result = asyncio.run(check(args.url, args.wallet, args.max_usd, args.eth_usd))
    except Exception as error:
        # Do not expose provider payloads or API credentials in exceptions.
        raise SystemExit(f'Preflight incomplete ({type(error).__name__}); no signature or broadcast occurred.') from None
    output = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(output + '\n', encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
