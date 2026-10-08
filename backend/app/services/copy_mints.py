"""Observe verified public SeaDrop mints; never replay another wallet's calldata."""
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid
from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address
from fastapi import HTTPException
from sqlalchemy import select, func
from web3.exceptions import Web3RPCError
from app.config import settings
from app.models import CopyWatch, CopyRule, CopyEvent, MintTask, MintAuthorization, Drop, MintStage, ActivityEvent
from app.services import automatic
from app.services.mint_plans import aware
from app.services.seadrop_mint import decode_mint, verify_presale, ALLOW_SELECTOR, SIGNED_SELECTOR
from app.services.opensea import OpenSeaClient, OpenSeaUnavailable, CHAINS as OPENSEA_CHAINS
from app.services.signer.base import SEADROP_V1_ADDRESS, MINT_PUBLIC_SELECTOR
from app.services.parser import format_wei_to_eth
from app.services.automatic_fees import quote_gas, maximum_fee

CHAINS = {1: 'Ethereum', 8453: 'Base', 4663: 'Robinhood', 31337: 'Local test', 11155111: 'Sepolia'}
TRANSFER = '0x' + keccak(text='Transfer(address,address,uint256)').hex()
SEADROP_MINT = '0x' + keccak(text='SeaDropMint(address,address,address,address,uint256,uint256,uint256,uint256)').hex()
ZERO_TOPIC = '0x' + '0' * 64


def funding_note(chain, paid=False):
    return f'Not enough ETH on {CHAINS.get(chain, "this network")} for {"mint + gas" if paid else "gas"}.'


def is_funding_note(note, chain):
    return note in (funding_note(chain), funding_note(chain, True), 'Insufficient funds for mint value and gas')


def budget_group(snapshot):
    group = snapshot.get('budget_group')
    if group is None:
        return None
    if (set(group) != {'id', 'budget_wei', 'members'} or str(uuid.UUID(group['id'])) != group['id']
            or not 0 < group['budget_wei'] < 2**63 or not 1 <= len(group['members']) <= 3
            or len(set(group['members'])) != len(group['members'])
            or any(str(uuid.UUID(member)) != member for member in group['members'])):
        raise ValueError('Invalid shared copy budget')
    return group


async def group_remaining(db, rule):
    group = budget_group(rule.snapshot)
    if group is None:
        return rule.budget_wei - rule.spent_wei - rule.reserved_wei
    members = (await db.scalars(select(CopyRule).where(CopyRule.id.in_(group['members'])))).all()
    if len(members) != len(group['members']) or any(
            m.user_id != rule.user_id or m.watch_id != rule.watch_id
            or m.snapshot['wallet_id'] != rule.snapshot['wallet_id'] or budget_group(m.snapshot) != group for m in members):
        raise ValueError('Shared copy approval differs')
    return group['budget_wei'] - sum(m.spent_wei + m.reserved_wei for m in members)


async def funding_check(web3, execution, snapshot):
    value = int(execution['value'])
    balance = await web3.eth.get_balance(snapshot['account'], 'pending')
    if balance <= value:
        raise HTTPException(409, funding_note(snapshot['chain_id'], value > 0))
    tx = {'from': snapshot['account'], 'to': execution['target'], 'data': execution['data'], 'value': value}
    gas, price = await copy_gas_quote(web3, tx, snapshot['chain_id'], value > 0)
    fee = await maximum_fee(web3, tx, snapshot['chain_id'], gas, price)
    if balance < value + fee:
        raise HTTPException(409, funding_note(snapshot['chain_id'], value > 0))
    if fee > snapshot['fee_cap_wei'] or value + fee > snapshot['total_cap_wei']:
        raise HTTPException(409, f'Gas exceeds your spending limit on {CHAINS.get(snapshot["chain_id"], "this network")}.')


def balance_error(error):
    message = str(error).lower()
    return 'insufficient funds' in message or 'insufficient balance' in message


async def copy_gas_quote(web3, tx, chain, paid=False):
    try:
        return await quote_gas(web3, tx, chain)
    except Exception as error:
        if balance_error(error):
            raise HTTPException(409, funding_note(chain, paid)) from None
        raise


def quantity_mode(rule):
    mode = rule.get('quantity_mode', 'fixed')
    if mode not in ('fixed', 'max_free') or (mode == 'max_free' and (
            not rule['free_only'] or rule['price_cap_wei'] != 0 or rule['quantity'] != 100)):
        raise ValueError('Unsupported or unapproved copy quantity mode')
    return mode


async def maximum_free_quantity(web3, observation, rule):
    """Remaining supported quantity, submitted only when its fee quote fits.

    Reads only the receiving wallet's stats. RPC/eligibility failures propagate;
    a successfully quoted fee above the limit skips the maximum mint.
    """
    if quantity_mode(rule) != 'max_free' or observation['price_wei'] != 0:
        raise ValueError('Maximum copying requires a verified zero-price mint')
    current = await public_stage(web3, observation['contract'])
    if any(current[k] != observation[k] for k in ('price_wei', 'start', 'end')):
        raise ValueError('Free public stage changed')
    account = to_checksum_address(rule['account'])
    minted, supply, maximum = decode(['uint256'] * 3, await web3.eth.call({
        'to': observation['contract'], 'data': keccak(text='getMintStats(address)')[:4]
        + encode(['address'], [account])}))
    ceiling = min(rule['quantity'], max(0, current['limit'] - minted), max(0, maximum - supply))
    balance = await web3.eth.get_balance(account, 'pending')
    if ceiling < 1:
        raise HTTPException(409, 'No remaining free mint allowance or supply.')
    if balance <= 0:
        raise HTTPException(409, funding_note(observation['chain_id']))
    base = dict(mint_kind='public', contract=observation['contract'], account=account,
        recipient=account, chain_id=observation['chain_id'], price_wei=0, price_cap_wei=0,
        start=current['start'], end=current['end'])

    async def fits(count):
        execution = await automatic.prepare_mint(web3, {**base, 'quantity': count})
        tx = {'from': account, 'to': execution['target'], 'data': execution['data'], 'value': 0}
        gas, price = await copy_gas_quote(web3, tx, observation['chain_id'])
        fee = await maximum_fee(web3, tx, observation['chain_id'], gas, price)
        if fee > balance:
            raise HTTPException(409, funding_note(observation['chain_id']))
        return fee <= rule['fee_cap_wei']

    if await fits(ceiling):
        return ceiling
    raise HTTPException(409, 'Maximum free mint exceeds your network-fee limit or available gas balance.')


def enabled():
    if not settings.ENABLE_COPY_MINTS:
        raise HTTPException(409, 'Copy mints is not enabled on this server yet.')


def networks():
    result = []
    for chain, name in CHAINS.items():
        if chain in (31337,11155111) and chain != settings.AUTOMATIC_CHAIN_ID:
            continue
        try:
            automatic.enabled(chain)
            result.append({'chain_id': chain, 'name': name})
        except HTTPException:
            pass
    return result


def hex_value(value):
    return '0x' + bytes(value).hex()


async def public_stage(web3, contract, block='latest'):
    raw = await web3.eth.call({'to': SEADROP_V1_ADDRESS,
        'data': keccak(text='getPublicDrop(address)')[:4] + encode(['address'], [contract])}, block)
    price, start, end, limit, bps, restricted = decode(['uint80','uint48','uint48','uint16','uint16','bool'], raw)
    if not 0 < start < end or not 0 < limit or price >= 2**63:
        raise ValueError('No bounded public stage')
    return {'price_wei': price, 'start': start, 'end': end, 'limit': limit}


async def verify_source(web3, observation):
    """Signer and observer independently check sender, calldata and ERC721 receipt."""
    tx = await web3.eth.get_transaction(observation['source_hash'])
    receipt = await web3.eth.get_transaction_receipt(observation['source_hash'])
    block = await web3.eth.get_block(receipt.blockNumber)
    source = observation['source_address'].lower()
    if (receipt.status != 1 or tx['from'].lower() != source
            or hex_value(receipt.blockHash) != observation['block_hash'] or block.hash != receipt.blockHash
            or receipt.blockNumber != observation['block_number']
            or block.timestamp != observation['timestamp']
            or await web3.eth.block_number - receipt.blockNumber + 1 < 2):
        raise ValueError('Source mint is not canonical or does not belong to the followed wallet')
    data = tx.get('input', tx.get('data'))
    data = data if isinstance(data, str) else hex_value(data)
    mint = decode_mint({'to': tx['to'], 'data': data, 'value': str(tx.value)},
        observation['contract'], source, observation['source_quantity'])
    if mint['kind'] != observation.get('mint_kind', 'public'):
        raise ValueError('Source mint method differs from the observed stage')
    topic = bytes.fromhex(source[2:].rjust(64, '0'))
    count = sum(1 for log in receipt.logs if log.address.lower() == observation['contract'].lower()
        and len(log.topics) == 4 and bytes(log.topics[0]) == bytes.fromhex(TRANSFER[2:])
        and bytes(log.topics[1]) == bytes(32) and bytes(log.topics[2]) == topic)
    if count != mint['quantity'] or tx.value != observation['price_wei'] * count:
        raise ValueError('Source receipt does not prove the specified NFT mint')
    historical = await public_stage(web3, observation['contract'], receipt.blockNumber) if mint['kind'] == 'public' else {
        'price_wei':mint['params'][0], 'start':mint['params'][2], 'end':mint['params'][3]}
    if any(historical[k] != observation[k] for k in ('price_wei', 'start', 'end')):
        raise ValueError('Source stage differs from the observed public stage')
    if mint['kind'] != 'public' and mint['params'][4] != observation.get('onchain_stage_index'):
        raise ValueError('Source whitelist stage index differs')
    return mint


async def observe(web3, chain, tx_hash, source, contract):
    tx = await web3.eth.get_transaction(tx_hash)
    data = tx.get('input', tx.get('data'))
    raw = bytes.fromhex(data.removeprefix('0x')) if isinstance(data, str) else bytes(data)
    if raw[:4].hex() not in (MINT_PUBLIC_SELECTOR, ALLOW_SELECTOR, SIGNED_SELECTOR):
        raise ValueError('Not a supported direct SeaDrop mint')
    values = decode(['address','address','address','uint256'], raw[4:132])
    if values[0].lower() != contract.lower():
        raise ValueError('NFT differs from mint calldata')
    if tx['from'].lower() != source.lower():
        raise ValueError('Transaction was not sent by the followed wallet')
    mint = decode_mint({'to': tx['to'], 'value': str(tx.value), 'data': '0x' + raw.hex()}, contract, source, values[3])
    receipt = await web3.eth.get_transaction_receipt(tx_hash)
    stage = await public_stage(web3, contract, receipt.blockNumber) if mint['kind'] == 'public' else {
        'price_wei':mint['params'][0], 'start':mint['params'][2], 'end':mint['params'][3],
        'limit':mint['params'][1], 'onchain_stage_index':mint['params'][4], 'mint_kind':mint['kind']}
    block = await web3.eth.get_block(receipt.blockNumber)
    observation = dict(chain_id=chain, chain=CHAINS[chain], contract=to_checksum_address(contract),
        source_hash=tx_hash, source_address=source, source_quantity=values[3],
        block_number=receipt.blockNumber, block_hash=hex_value(receipt.blockHash),
        timestamp=block.timestamp, **stage)
    await verify_source(web3, observation)
    try:
        raw_name = await web3.eth.call({'to': to_checksum_address(contract), 'data': keccak(text='name()')[:4], 'gas': 50000})
        name = decode(['string'], raw_name)[0] if len(raw_name) <= 2048 else ''
        name = ''.join(c for c in name if c.isprintable()).strip()[:150]
    except Exception:
        name = ''
    observation['name'] = name or 'Collection ' + contract[:8]
    return observation


async def prepare_presale_copy(web3, observation, rule):
    """Acquire the receiving wallet's proof/signature, never the followed wallet's."""
    if await web3.eth.get_balance(rule['account'], 'pending') <= 0:
        raise HTTPException(409, funding_note(observation['chain_id']))
    client = OpenSeaClient()
    try:
        slug = await client.collection_for_contract(observation['chain_id'], observation['contract'])
        async def build(quantity):
            status, transaction = await client.build_mint(slug, rule['account'], quantity)
            if status != 200 or transaction is None:
                raise HTTPException(409, 'Your wallet cannot mint this whitelist stage.')
            if OPENSEA_CHAINS.get(transaction.get('chain'), (None,))[0] != observation['chain_id']:
                raise HTTPException(409, 'Whitelist mint network could not be verified.')
            mint = decode_mint(transaction, observation['contract'], rule['account'], quantity)
            if (mint['kind'] != observation['mint_kind'] or mint['params'] is None
                    or mint['params'][2:5] != (observation['start'], observation['end'], observation['onchain_stage_index'])):
                raise HTTPException(409, 'Whitelist mint unavailable. Public mint fallback is disabled.')
            await verify_presale(web3, mint)
            return mint
        mode = quantity_mode(rule)
        mint = await build(1 if mode == 'max_free' else rule['quantity'])
        if mode == 'max_free' and mint['params'][0] == 0:
            minted, supply, maximum = decode(['uint256'] * 3, await web3.eth.call({
                'to': observation['contract'], 'data': keccak(text='getMintStats(address)')[:4]
                    + encode(['address'], [rule['account']])}))
            count = min(rule['quantity'], mint['params'][1] - minted, mint['params'][5] - supply, maximum - supply)
            if count < 1:
                raise HTTPException(409, 'No whitelist mint allowance or supply remains.')
            if count != 1:
                mint = await build(count)
        return mint, slug
    except OpenSeaUnavailable as error:
        if error.status in (400,404,409,422):
            raise HTTPException(409, 'Whitelist eligibility or mint data could not be verified for your wallet.') from None
        raise


async def drop_for(db, web3, observation, *, presale=None, slug=None):
    kind = observation.get('mint_kind', 'public')
    if kind != 'public' and presale is None:
        raise HTTPException(409, 'Enable eligible whitelist copying in Copy settings first.')
    current = await public_stage(web3, observation['contract']) if kind == 'public' else {
        'price_wei':observation['price_wei'], 'start':observation['start'], 'end':observation['end'], 'limit':observation['limit']}
    if any(current[k] != observation[k] for k in ('price_wei', 'start', 'end')):
        raise HTTPException(409, 'The observed public stage has changed. This mint cannot be copied.')
    block = await web3.eth.get_block('latest')
    if not current['start'] <= max(block.timestamp, int(datetime.now(timezone.utc).timestamp())) < current['end']:
        raise HTTPException(409, 'This public stage is no longer open.')
    parts = [observation['chain_id'], observation['contract'].lower(), current['start'], current['end']]
    if kind != 'public':
        parts += [kind, observation['onchain_stage_index']]
    key = automatic.digest(parts)
    drop = await db.get(Drop, key)
    if not drop:
        chain_slug = {1:'ethereum',8453:'base',4663:'robinhood',11155111:'sepolia',31337:'local'}[observation['chain_id']]
        drop = Drop(id=key, name=observation['name'], chain=observation['chain'], chain_id=observation['chain_id'],
            contract_address=observation['contract'], mint_page_url=f'https://opensea.io/collection/{slug}' if slug else f'https://opensea.io/assets/{chain_slug}/{observation["contract"]}',
            site_label='Public SeaDrop', icon_name='gem', status_label='Public stage verified', status_kind='unknown',
            is_supported_integration=True, is_demo=False)
        db.add(drop)
        await db.flush()
        stage = MintStage(id=key, drop_id=key, stage_name='Public' if kind == 'public' else 'Whitelist',
            start_time_utc=datetime.fromtimestamp(current['start'], timezone.utc),
            end_time_utc=datetime.fromtimestamp(current['end'], timezone.utc), price_wei=current['price_wei'],
            price_eth_str=format_wei_to_eth(current['price_wei']), limit_per_wallet=current['limit'], eligibility_status='unknown')
        db.add(stage)
        await db.flush()
    else:
        stage = await db.get(MintStage, key)
        stage.limit_per_wallet = current['limit']
    return drop, stage


def stage_key(snapshot):
    parts = [snapshot['chain_id'], snapshot['account'].lower(), snapshot['contract'].lower(), snapshot['start'], snapshot['end']]
    if snapshot.get('mint_kind', 'public') != 'public':
        parts += [snapshot['mint_kind'], snapshot['onchain_stage_index']]
    return automatic.digest(parts)


async def no_mixed_stage_copy(db, snapshot, *, task_id=None):
    """Block queued/finished presale-public duplicates by address, network and collection."""
    rows = (await db.execute(select(MintTask, MintAuthorization).join(MintAuthorization,
        MintTask.authorization_id == MintAuthorization.id).where(MintTask.copy_stage_key.is_not(None),
            MintAuthorization.snapshot['chain_id'].as_integer() == snapshot['chain_id'],
            func.lower(MintAuthorization.snapshot['account'].as_string()) == snapshot['account'].lower(),
            func.lower(MintAuthorization.snapshot['contract'].as_string()) == snapshot['contract'].lower()))).all()
    for task, auth in rows:
        other = auth.snapshot
        if task.id == task_id or not other:
            continue
        if task.status in ('failed','expired','disarmed') and not task.signed_tx_raw:
            continue
        if (other['chain_id'] == snapshot['chain_id'] and other['account'].lower() == snapshot['account'].lower()
                and other['contract'].lower() == snapshot['contract'].lower()
                and (other['mint_kind'] == 'public') != (snapshot['mint_kind'] == 'public')):
            raise HTTPException(409, 'Whitelist copy already exists. Public mint skipped.' if snapshot['mint_kind'] == 'public'
                else 'Public copy already exists. Whitelist mint skipped.')


async def no_duplicate(db, snapshot):
    await no_mixed_stage_copy(db, snapshot)
    key = stage_key(snapshot)
    if await db.scalar(select(MintTask.id).where(MintTask.copy_stage_key == key).limit(1)):
        raise HTTPException(409, 'This receiving wallet already has a copy for this collection’s public stage.')
    # Prevent a followed signal from duplicating a separately armed mint plan.
    existing = (await db.execute(select(MintAuthorization).join(MintTask, MintTask.authorization_id == MintAuthorization.id)
        .where(MintAuthorization.wallet_id == snapshot['wallet_id'], MintTask.execution_mode == automatic.MODE,
               MintTask.status.not_in(['failed','expired','disarmed'])))).scalars().all()
    if any(a.snapshot and a.snapshot.get('mint_kind') == 'public' and stage_key(a.snapshot) == key for a in existing):
        raise HTTPException(409, 'This wallet already has an active or completed mint for this public stage.')
    return key


async def pause_rule(db, rule):
    rule.status = 'paused'
    tasks = (await db.execute(select(MintTask).where(MintTask.copy_rule_id == rule.id,
        MintTask.status.in_(['armed','preparing']), MintTask.signed_tx_raw.is_(None)))).scalars().all()
    for task in tasks:
        task.status = 'disarmed'
        await automatic.release_reservation(db, task)


async def arm_event(db, event, rule, web3):
    await automatic.require_running(db, rule.user_id)
    o, r = event.observation, rule.snapshot
    if rule.status != 'active' or aware(rule.expires_at) <= datetime.now(timezone.utc):
        return
    if o['block_number'] <= rule.resume_after_block:
        return  # Recent history and paused intervals are never spent automatically.
    kind = o.get('mint_kind', 'public')
    if kind not in r.get('mint_kinds', ['public']):
        event.status, event.note = 'skipped', 'Whitelist copying is off. Enable it in Copy settings.'
        return
    await no_mixed_stage_copy(db, {'chain_id':o['chain_id'], 'account':r['account'], 'contract':o['contract'], 'mint_kind':kind})
    if kind == 'public' and (o['price_wei'] > r['price_cap_wei'] or (r['free_only'] and o['price_wei'] != 0)):
        event.status, event.note = 'skipped', 'Mint price is outside your copy limits.'
        return
    if rule.budget_wei - rule.spent_wei - rule.reserved_wei < r['total_cap_wei']:
        event.status, event.note = 'skipped', 'Copy budget is exhausted or reserved by pending mints.'
        return
    if await group_remaining(db, rule) < r['total_cap_wei']:
        event.status, event.note = 'skipped', 'Total copy budget is used or reserved by pending mints.'
        return
    await verify_source(web3, o)
    mode = quantity_mode(r)
    presale, slug = None, None
    if kind == 'public':
        drop, stage = await drop_for(db, web3, o)
        quantity = await maximum_free_quantity(web3, o, r) if mode == 'max_free' else r['quantity']
        price = o['price_wei']
    else:
        presale, slug = await prepare_presale_copy(web3, o, r)
        quantity, price = presale['quantity'], presale['params'][0]
        drop, stage = await drop_for(db, web3, o, presale=presale, slug=slug)
        if price > r['price_cap_wei'] or (r['free_only'] and price != 0):
            event.status, event.note = 'skipped', 'Your whitelist price is outside your copy limits.'
            return
    if await web3.eth.get_balance(r['account'], 'pending') <= price * quantity:
        raise HTTPException(409, funding_note(o['chain_id'], price > 0))
    req = SimpleNamespace(plan_id=None, grant_id=rule.grant_id, wallet_id=r['wallet_id'], drop_id=drop.id,
        stage_id=stage.id, quantity=quantity, price_cap_eth=format_wei_to_eth(r['price_cap_wei']),
        fee_cap_eth=format_wei_to_eth(r['fee_cap_wei']), total_cap_eth=format_wei_to_eth(r['total_cap_wei']),
        expires_at=min(aware(rule.expires_at), aware(stage.end_time_utc)), mint_kind=kind,
        conditional_eligibility=False, onchain_stage_index=o.get('onchain_stage_index'))
    grant, s = await automatic.make_snapshot(db, req, rule.user_id, presale_mint=presale)
    s['copy_rule_id'], s['copy_source'] = rule.id, o
    if mode == 'max_free':
        s['copy_quantity_mode'] = mode
    key = await no_duplicate(db, s)
    s['execution'] = presale['execution'] if presale else await automatic.prepare_mint(web3, s)
    await funding_check(web3, s['execution'], s)
    auth = MintAuthorization(id=str(uuid.uuid4()), wallet_id=r['wallet_id'], drop_id=drop.id, stage_id=stage.id,
        quantity=s['quantity'], max_price_per_token_wei=s['price_cap_wei'], max_fee_wei=s['fee_cap_wei'],
        total_spend_cap_wei=s['total_cap_wei'], recipient_address=s['account'],
        user_consent_text='Copy this followed wallet’s verified public mints within the approved immutable rule.',
        authorized_at=datetime.fromtimestamp(r['approved_at'], timezone.utc), grant_id=grant.id, snapshot=s)
    db.add(auth)
    await db.flush()
    task = MintTask(id=str(uuid.uuid4()), authorization_id=auth.id, wallet_id=r['wallet_id'], drop_id=drop.id,
        stage_id=stage.id, copy_rule_id=rule.id, copy_stage_key=key, status='armed', is_demo=False,
        idempotency_key=automatic.digest(['copy', event.id, rule.id]), request_hash=automatic.digest(s),
        execution_mode=automatic.MODE, scheduled_for_utc=datetime.now(timezone.utc),
        expires_at_utc=datetime.fromtimestamp(s['expiry'], timezone.utc))
    db.add(task)
    await db.flush()
    rule.reserved_wei += s['total_cap_wei']
    grant.reserved_wei += s['total_cap_wei']
    event.task_id, event.status, event.note = task.id, 'armed', None
    db.add(ActivityEvent(user_id=rule.user_id, event_type='copy_armed', label='Copied mint armed',
        detail=f'{rule.id}: {task.id}', icon_name='gem', is_demo=False))


async def discover_watch(watch, chain):
    """Only RPC reads: independent wallets/networks may run concurrently."""
    previous = dict(watch.cursors.get(str(chain), {}))
    web3 = await automatic.provider_for(chain)
    observations = []
    try:
        head = max(0, await web3.eth.block_number - 12)
        last = previous.get('block', max(0, head - 2000))
        if previous.get('hash') and hex_value((await web3.eth.get_block(last)).hash) != previous['hash']:
            last = max(0, last - 24)
        end = min(head, last + 300)
        if end > last:
            logs = await web3.eth.get_logs({'address': SEADROP_V1_ADDRESS, 'fromBlock': last + 1, 'toBlock': end,
                'topics': [SEADROP_MINT, None, '0x' + watch.address[2:].rjust(64, '0')]})
            if len(logs) > 1000:
                raise ValueError('Mint observation range too dense')
            seen = set()
            for log in logs:
                if len(log.topics) != 4:
                    continue
                tx_hash = hex_value(log.transactionHash)
                contract = to_checksum_address(bytes(log.topics[1])[-20:])
                if (tx_hash, contract.lower()) in seen:
                    continue
                seen.add((tx_hash, contract.lower()))
                try:
                    observations.append(await observe(web3, chain, tx_hash, watch.address, contract))
                except (ValueError, KeyError):
                    continue
                except Exception as error:
                    message = str(error).lower()
                    if isinstance(error, Web3RPCError) and (('historical state' in message and 'not available' in message)
                            or 'missing trie node' in message):
                        previous['history_note'] = 'Older source stages are outside this RPC’s retained state. Only verified source mints are counted or copied.'
                        continue
                    from app.services.opensea import OpenSeaUnavailable
                    if isinstance(error, OpenSeaUnavailable):
                        continue
                    raise
            previous = {'block': end, 'hash': hex_value((await web3.eth.get_block(end)).hash),
                'since_block': previous.get('since_block', last + 1),
                'since': previous.get('since', datetime.now(timezone.utc).isoformat()),
                'history_note': previous.get('history_note'),
                'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'catching_up' if end < head else 'monitoring'}
        else:
            previous.update(checked_at=datetime.now(timezone.utc).isoformat(), status='monitoring')
        return previous, observations
    finally:
        await web3.provider.disconnect()


async def scan_watch(db, watch, chain):
    # No shared AsyncSession and no database mutation during parallel discovery.
    original = dict(watch.cursors.get(str(chain), {}))
    watch_id = watch.id
    await db.commit()
    try:
        import asyncio
        previous, observations = await asyncio.wait_for(discover_watch(watch, chain), timeout=45)
    except Exception:
        previous, observations = dict(original), []
        previous.update(checked_at=datetime.now(timezone.utc).isoformat(), status='unavailable')
    await automatic.lock_execution(db)
    await db.refresh(watch)
    if watch.archived_at or chain not in watch.chains:
        return
    if dict(watch.cursors.get(str(chain), {})) != original:
        return  # Another process advanced this pair; never overwrite a newer cursor.
    for observation in observations:
        key = automatic.digest([watch_id, chain, observation['source_hash'], observation['contract'].lower()])
        if not await db.get(CopyEvent, key):
            db.add(CopyEvent(id=key, user_id=watch.user_id, watch_id=watch_id, observation=observation, status='detected'))
            await db.flush()
    watch.cursors = {**watch.cursors, str(chain): previous}
    watch.updated_at = datetime.now(timezone.utc)
    await db.flush()
    # Observation and reservations are committed independently for crash replay.
    await db.commit()
    if previous['status'] == 'unavailable':
        return
    await automatic.lock_execution(db)
    await db.refresh(watch)
    if watch.archived_at or chain not in watch.chains:
        return
    rules = (await db.scalars(select(CopyRule).where(CopyRule.watch_id == watch_id,
        CopyRule.chain_id == chain, CopyRule.status == 'active'))).all()
    if not rules:
        return
    web3 = await automatic.provider_for(chain)
    try:
        events = (await db.scalars(select(CopyEvent).where(CopyEvent.watch_id == watch_id,
            CopyEvent.status == 'detected', CopyEvent.task_id.is_(None)).order_by(CopyEvent.created_at).limit(50))).all()
        for event in events:
            if event.observation['chain_id'] != chain:
                continue
            for rule in rules:
                try:
                    async with db.begin_nested():
                        await arm_event(db, event, rule, web3)
                except HTTPException as error:
                    event.status, event.note = 'skipped', str(error.detail)
                except ValueError:
                    event.status, event.note = 'skipped', 'Stage, source receipt or receiving-wallet eligibility changed.'
                if event.task_id or event.status == 'skipped':
                    break
    finally:
        await web3.provider.disconnect()
