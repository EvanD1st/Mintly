"""Collection-triggered free copying under a separately pinned user opt-in."""
from datetime import datetime, timezone, timedelta
from eth_abi import decode, encode
from eth_utils import keccak
from fastapi import HTTPException
from app.services.opensea import OpenSeaClient, stage_schedule, CHAINS
from app.services.phase_identity import stage_kind
from app.services.seadrop_mint import decode_mint, verify_presale


def enabled(rule):
    value = rule.get('any_eligible_free_phase', False)
    if type(value) is not bool or value and (
            not rule['free_only'] or rule['price_cap_wei'] != 0 or rule.get('paid_only', False)
            or rule.get('mint_kinds') != ['public', 'allowlist', 'signed']):
        raise ValueError('Any-phase copying requires explicit free-only and presale consent')
    return value


class PhaseWait(Exception):
    def __init__(self, note, next_attempt, plan):
        self.note, self.next_attempt, self.plan = note, next_attempt, plan


async def require_unminted(web3, contract, account):
    minted, supply, maximum = decode(['uint256'] * 3, await web3.eth.call({
        'to': contract, 'data': keccak(text='getMintStats(address)')[:4] + encode(['address'], [account])}))
    if minted:
        raise HTTPException(409, f'Already minted {minted} from this collection. Copy skipped to prevent another mint.')
    if supply >= maximum:
        raise HTTPException(409, 'This collection is sold out. No transaction sent.')


def deadline(event, rule):
    return rule.expires_at if enabled(rule.snapshot) else datetime.fromtimestamp(event.observation['end'], timezone.utc)


async def select_phase(web3, source, rule):
    """Only wallet-specific, independently verified zero-price instructions can arm."""
    from app.services import copy_mints
    await require_unminted(web3, source['contract'], rule.snapshot['account'])
    client = OpenSeaClient()
    slug = await client.collection_for_contract(source['chain_id'], source['contract'])
    drop = await client.get_drop(slug)
    now = max(int(datetime.now(timezone.utc).timestamp()), (await web3.eth.get_block('latest')).timestamp)
    expiry = int(rule.expires_at.replace(tzinfo=timezone.utc).timestamp())
    # Whitelist prices can be wallet-specific; only verified zero-value calldata
    # can authorize execution, even when a schedule has a nonzero/unknown price.
    phases = [p for p in stage_schedule(drop) if (p['price_wei'] in (0, None) or stage_kind(p['type']) in ('allowlist', 'signed'))
        and stage_kind(p['type']) in ('public', 'allowlist', 'signed')
        and int(p['ends_at'].timestamp()) > now and int(p['starts_at'].timestamp()) < expiry]
    if not phases:
        raise HTTPException(409, 'No free phase remains within your copy approval. No transaction sent.')
    future = [p for p in phases if int(p['starts_at'].timestamp()) > now]
    current = [p for p in phases if int(p['starts_at'].timestamp()) <= now]
    reason = None
    if current:
        count = rule.snapshot['quantity'] if copy_mints.quantity_mode(rule.snapshot) == 'fixed' else 1
        status, tx = await client.build_mint(slug, rule.snapshot['account'], count)
        if status == 200 and tx:
            if CHAINS.get(tx.get('chain'), (None,))[0] != source['chain_id']:
                raise HTTPException(409, 'Mint network differs from the followed collection.')
            mint = decode_mint(tx, source['contract'], rule.snapshot['account'], count)
            if mint['kind'] == 'public':
                terms = await copy_mints.public_stage(web3, source['contract'])
                start, end, price = terms['start'], terms['end'], terms['price_wei']
            else:
                price, _, start, end = mint['params'][:4]
            matching = [p for p in current if stage_kind(p['type']) == mint['kind']
                and (int(p['starts_at'].timestamp()), int(p['ends_at'].timestamp())) == (start, end)]
            if price != 0 or int(tx['value']) != 0:
                reason = 'Your wallet received paid mint instructions. Paid fallback is disabled.'
            elif not matching:
                reason = 'Wallet instructions do not match an active free phase. No transaction sent.'
            else:
                selected = {**source, 'mint_kind': mint['kind'], 'price_wei': 0, 'start': start, 'end': end,
                    'phase_name': matching[0]['name']}
                if mint['kind'] == 'public':
                    selected['limit'] = terms['limit']
                    selected.pop('onchain_stage_index', None)
                    return selected, None, slug
                selected['limit'], selected['onchain_stage_index'] = mint['params'][1], mint['params'][4]
                await verify_presale(web3, mint)
                mint = await copy_mints.resize_presale(web3, selected, rule.snapshot, mint)
                return selected, mint, slug
        else:
            from app.services.mint_diagnostics import MINT_REASONS
            category = getattr(client, 'last_mint_reason', None) or 'instructions_unavailable'
            reason = MINT_REASONS.get(category, 'Wallet eligibility could not yet be verified.')
            if category == 'insufficient_funds':
                raise HTTPException(409, copy_mints.funding_note(source['chain_id']))
            if category not in ('wallet_not_allowlisted', 'wallet_limit', 'supply_exhausted', 'allowance_or_supply_exhausted'):
                boundary = min([int(p['ends_at'].timestamp()) for p in current] +
                    [int(p['starts_at'].timestamp()) for p in future] + [expiry])
                raise PhaseWait(reason + ' Waiting to recheck this free phase.',
                    datetime.fromtimestamp(min(now + 60, boundary), timezone.utc), {'rule_id': rule.id, 'slug': slug})
    if future:
        upcoming = min(future, key=lambda p: p['starts_at'])
        opening, label = upcoming['starts_at'], upcoming['name']
        time = (opening + timedelta(hours=1)).strftime('%d %b %H:%M WAT')
        raise PhaseWait(((reason + ' ') if reason else '') +
            f'Waiting for {label} at {time}. Eligibility will be checked when it opens; the mint price must be zero.',
            opening, {'rule_id': rule.id, 'slug': slug, 'phase': label, 'starts_at': opening.isoformat()})
    raise HTTPException(409, reason or 'No eligible free phase remains. No transaction sent.')
