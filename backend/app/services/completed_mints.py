"""Reconcile an unsigned task against canonical wallet mints, without signing.

Collection ownership alone cannot establish the phase or consumed allowance.
Only finalized mint receipts with matching SeaDrop calldata can complete a task.
"""
from datetime import datetime, timezone

from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address

from app.services.networks import NETWORKS
from app.services.seadrop_mint import decode_mint
from app.services.signer.base import SEADROP_V1_ADDRESS

TRANSFER = keccak(text='Transfer(address,address,uint256)')
ZERO = bytes(32)


def hex_value(value):
    return value if isinstance(value, str) else '0x' + bytes(value).hex()


async def find_completed_mint(web3, scope):
    """Return public receipt evidence only when the approved allowance is used.

    Run after an explicit preparation rejection, never on the successful hot path.
    Search at most twelve RPC-sized log pages; an incomplete/failed search cannot
    establish completion. No keys, nonce allocation, budgets or provider mint POSTs.
    """
    account = to_checksum_address(scope['account'])
    contract = to_checksum_address(scope['contract'])
    minted, _, _ = decode(['uint256'] * 3, await web3.eth.call({
        'to': contract, 'data': keccak(text='getMintStats(address)')[:4] + encode(['address'], [account])}))
    limit = (scope.get('selected_phase') or {}).get('wallet_total_limit')
    if scope['mint_kind'] == 'public':
        price, start, end, limit, _, _ = decode(['uint80','uint48','uint48','uint16','uint16','bool'],
            await web3.eth.call({'to': SEADROP_V1_ADDRESS,
                'data': keccak(text='getPublicDrop(address)')[:4] + encode(['address'], [contract])}))
        if (price, start, end) != (scope['price_wei'], scope['start'], scope['end']):
            return None
    elif limit is None and scope.get('execution'):
        execution = scope['execution']
        approved = decode_mint({'to': execution['target'], 'data': execution['data'], 'value': execution['value']},
            contract, account, scope['quantity'])
        limit = approved['params'][1] if approved['params'] else None
    if type(limit) is not int or limit <= 0 or minted < limit:
        return None
    latest = await web3.eth.get_block('latest')
    span = NETWORKS[scope['chain_id']].log_span
    end_block = latest['number']
    seen = set()
    for _ in range(12):
        begin = max(0, end_block - span + 1)
        logs = await web3.eth.get_logs({'fromBlock': begin, 'toBlock': end_block, 'address': contract,
            'topics': [hex_value(TRANSFER), hex_value(ZERO), '0x' + account[2:].lower().rjust(64, '0')]})
        # Receipt order is deterministic; repeated ERC721 transfers use one lookup.
        for log in sorted(logs, key=lambda item: (item['blockNumber'], item['logIndex']), reverse=True):
            tx_hash = hex_value(log['transactionHash'])
            if tx_hash in seen or log.get('removed'):
                continue
            seen.add(tx_hash)
            from app.services.automatic_signer import final_receipt
            receipt = await final_receipt(web3, tx_hash, scope['chain_id'])
            if receipt is None or receipt['status'] != 1:
                continue
            if receipt['blockHash'] != log['blockHash'] or receipt['blockNumber'] != log['blockNumber']:
                continue
            block = await web3.eth.get_block(receipt['blockNumber'])
            if not scope['start'] <= block['timestamp'] <= scope['end']:
                continue
            count = sum(1 for item in receipt['logs'] if item['address'].lower() == contract.lower()
                and len(item['topics']) == 4 and bytes(item['topics'][0]) == TRANSFER
                and bytes(item['topics'][1]) == ZERO
                and bytes(item['topics'][2]) == bytes.fromhex(account[2:].rjust(64, '0')))
            if not 1 <= count <= 100:
                continue
            tx = await web3.eth.get_transaction(tx_hash)
            # A zero minter argument means the sender; require that sender too.
            try:
                mint = decode_mint({'to': tx['to'], 'data': hex_value(tx['input']), 'value': str(tx['value'])},
                    contract, account, count)
                recipient = decode(['address'] * 3 + ['uint256'], bytes.fromhex(hex_value(tx['input'])[10:])[:128])[2]
            except Exception:
                continue
            if int(recipient, 16) == 0 and tx['from'].lower() != account.lower():
                continue
            if mint['kind'] != scope['mint_kind']:
                continue
            params = mint['params']
            if params and ((params[0], params[1], params[2], params[3]) !=
                    (scope['price_wei'], limit, scope['start'], scope['end']) or
                    (scope.get('onchain_stage_index') is not None and params[4] != scope['onchain_stage_index'])):
                continue
            if params and scope.get('onchain_stage_index') is None:
                # Matching clock times alone are insufficient when phases overlap.
                from app.services.opensea import OpenSeaClient, collection_slug, stage_schedule, CHAINS
                from app.services.seadrop_mint import match_stage
                from app.services.phase_identity import schedule_matches
                from app.services.mint_stage_choice import pinned
                if not scope.get('selected_phase'):
                    continue
                detail = await OpenSeaClient().get_drop(collection_slug(scope['mint_page_url']))
                if (CHAINS.get(detail.get('chain'), (None,))[0] != scope['chain_id'] or
                        detail['contract_address'].lower() != contract.lower()):
                    continue
                selected = match_stage(mint, stage_schedule(detail))
                if not schedule_matches(selected, scope['selected_phase'], pinned):
                    continue
            if not params and tx['value'] != scope['price_wei'] * count:
                continue
            from app.services.networks import NETWORKS as networks
            return {'transaction_hash': tx_hash, 'block_number': receipt['blockNumber'],
                'block_hash': hex_value(receipt['blockHash']), 'chain_id': scope['chain_id'],
                'contract': contract, 'account': account, 'stage_name': scope['stage_name'],
                'stage_index': params[4] if params else 0, 'quantity': count,
                'minted_at': datetime.fromtimestamp(block['timestamp'], timezone.utc).isoformat(),
                'explorer_url': networks[scope['chain_id']].explorer + tx_hash,
                'wallet_minted': minted, 'wallet_total_limit': limit}
        if begin == 0:
            break
        # Stop when the oldest scanned block precedes the approved phase.
        boundary = await web3.eth.get_block(begin)
        if boundary['timestamp'] < scope['start']:
            break
        end_block = begin - 1
    return None


async def reconcile_rejection(scope, events, reason=None):
    """A provider rejection proves this preparation stopped before signing."""
    rejected = {'wallet_limit', 'allowance_or_supply_exhausted', 'wallet_not_allowlisted', 'supply_exhausted'}
    if reason not in rejected and not any(event.get('mint_reason') in rejected for event in events):
        return None
    import asyncio
    from app.services.network_reads import provider_for
    try:
        async with asyncio.timeout(8):
            web3 = await provider_for(scope['chain_id'])
            try:
                return await find_completed_mint(web3, scope)
            finally:
                await web3.provider.disconnect()
    except Exception:
        # Unavailable RPC/history leaves the ordinary bounded retry path intact.
        return None
