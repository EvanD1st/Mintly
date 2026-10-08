"""Custodial automatic execution: immutable intent, bounded budgets and real RPC.

Local chain and Sepolia; Robinhood requires a separate explicit opt-in.
"""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlparse
from pathlib import Path
import httpx

from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address
from fastapi import HTTPException
from sqlalchemy import select, update
from web3 import AsyncWeb3

from app.config import settings
from app.models import AutomaticGrant, AutomaticLock, Drop, MintStage, Wallet, MintTask, MintAuthorization, MintPlan
from app.services.mint_plans import aware
from app.services.opensea import OpenSeaClient, OpenSeaUnavailable, collection_slug, CHAINS
from app.services.seadrop_mint import decode_mint, verify_presale
from app.services.signer.base import SEADROP_V1_ADDRESS, MINT_PUBLIC_SELECTOR

MODE = 'custodial_v1'
TERMINAL = {'confirmed', 'reverted', 'failed', 'expired', 'disarmed'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def rpc_for(chain_id):
    if chain_id == settings.AUTOMATIC_CHAIN_ID:
        return settings.AUTOMATIC_RPC
    return {1: settings.RPC_ETHEREUM, 8453: settings.RPC_BASE, 4663: settings.RPC_ROBINHOOD,
            11155111: settings.RPC_SEPOLIA}.get(chain_id, '')


def enabled(chain_id=None):
    chain_id = settings.AUTOMATIC_CHAIN_ID if chain_id is None else chain_id
    if not settings.ENABLE_CUSTODIAL_AUTOMATIC:
        raise HTTPException(409, 'Automatic custody is not enabled. A linked MetaMask address alone cannot sign automatically.')
    permitted = {4663: settings.ENABLE_ROBINHOOD_AUTOMATIC, 1: settings.ENABLE_ETHEREUM_AUTOMATIC,
                 8453: settings.ENABLE_BASE_AUTOMATIC}
    if chain_id not in (31337, 11155111) and not permitted.get(chain_id, False):
        raise HTTPException(409, 'Automatic execution is disabled for this network.')
    parsed = urlparse(rpc_for(chain_id))
    if chain_id == 31337:
        if parsed.hostname not in ('127.0.0.1', 'localhost', 'evm') or parsed.scheme != 'http':
            raise HTTPException(409, 'Local automatic execution requires an isolated local RPC.')
    elif parsed.scheme != 'https':
        raise HTTPException(409, 'Remote automatic execution requires HTTPS RPC.')


async def provider(chain_id=None):
    chain_id = settings.AUTOMATIC_CHAIN_ID if chain_id is None else chain_id
    enabled(chain_id)
    web3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_for(chain_id), request_kwargs={'timeout': 8}))
    try:
        if await web3.eth.chain_id != chain_id:
            raise ValueError('RPC chain mismatch')
        return web3
    except Exception:
        await web3.provider.disconnect()
        raise


async def provider_for(chain_id):
    # Preserve the default provider boundary used by local integration fixtures.
    return await provider() if chain_id == settings.AUTOMATIC_CHAIN_ID else await provider(chain_id)


async def signer_ready(grant_id):
    try:
        token = Path(settings.AUTOMATIC_SIGNER_TOKEN_FILE).read_text().strip()
        if len(token) < 32:
            raise ValueError()
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            result = await client.get(settings.AUTOMATIC_SIGNER_URL + f'/policies/{grant_id}/ready',
                headers={'Authorization': 'Bearer ' + token})
            result.raise_for_status()
    except Exception:
        raise HTTPException(409, 'The isolated signer has not confirmed this policy and keystore are ready. No task was armed.') from None


async def lock_execution(db):
    """Cross-process transaction lock. SQLite also takes a real write lock.

    Coarse serialization is intentional for the private deployment: both
    cancellation and the independent signer use this exact lock order.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert = pg_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
    await db.execute(insert(AutomaticLock).values(id=1, revision=0).on_conflict_do_nothing(index_elements=['id']))
    await db.execute(update(AutomaticLock).where(AutomaticLock.id == 1).values(revision=AutomaticLock.revision + 1))


def wei(value):
    amount = Decimal(value) * 10**18
    if amount != amount.to_integral_value() or not 0 <= amount < 2**63:
        raise HTTPException(422, 'Amounts must be exact nonnegative wei within the supported range.')
    return int(amount)


async def grant_for(db, grant_id, user_id):
    await require_running(db, user_id)
    grant = (await db.execute(select(AutomaticGrant).where(
        AutomaticGrant.id == grant_id, AutomaticGrant.user_id == user_id
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if grant is None:
        raise HTTPException(404, 'Automatic policy not found.')
    if grant.adapter != MODE:
        raise HTTPException(409, 'Unsupported automatic policy adapter or chain.')
    enabled(grant.chain_id)
    wallet = await db.get(Wallet, grant.wallet_id)
    if not wallet or wallet.archived_at:
        raise HTTPException(409, 'Wallet is unlinked. Add it again and approve a new policy.')
    if grant.status != 'enabled' or aware(grant.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(409, 'Automatic policy is disabled or expired. Renew it in the signer before arming.')
    return grant


async def require_running(db, user_id):
    from app.models import User
    user = await db.scalar(select(User).where(User.id == user_id).execution_options(populate_existing=True))
    if not user or not user.is_active or user.deleted_at or user.automation_paused:
        raise HTTPException(409, 'Automation is paused. Resume it in Settings before setting up a mint.')


async def make_snapshot(db, req, user_id, *, presale_mint=None):
    enabled()
    if not req.grant_id:
        raise HTTPException(409, 'MetaMask connection is not automatic signing authority. Configure a custodial signer policy first.')
    grant = await grant_for(db, req.grant_id, user_id)
    if req.plan_id:
        plan = await db.get(MintPlan, req.plan_id)
        if (not plan or plan.user_id != user_id or plan.archived_at
                or plan.wallet_id != req.wallet_id or plan.automatic_drop_id != req.drop_id
                or plan.automatic_stage_id != req.stage_id):
            raise HTTPException(409, 'Mint plan changed or was removed. Reopen its automatic review.')
    wallet = await db.get(Wallet, req.wallet_id)
    drop = await db.get(Drop, req.drop_id)
    stage = await db.get(MintStage, req.stage_id)
    if not wallet or wallet.archived_at or wallet.user_id != user_id or not drop or not stage or stage.drop_id != drop.id:
        raise HTTPException(404, 'Wallet, drop or selected stage not found.')
    if grant.wallet_id != wallet.id or grant.account.lower() != wallet.address.lower():
        raise HTTPException(409, 'Signer policy does not belong to this wallet.')
    if drop.chain_id != grant.chain_id or not drop.is_supported_integration or not drop.contract_address or drop.is_demo:
        raise HTTPException(409, 'Drop chain or contract integration is unsupported for this signer.')
    if not allows_collection(grant.scope, drop.contract_address) or req.mint_kind not in grant.scope['mint_kinds']:
        raise HTTPException(409, 'Contract or mint method is outside the signer policy.')
    if req.mint_kind != 'public' and req.conditional_eligibility and req.onchain_stage_index is None:
        raise HTTPException(409, 'A conditional presale needs the verified on-chain stage index before arming; an ambiguous stage label is insufficient.')
    stage_price, stage_limit = stage.price_wei, stage.limit_per_wallet
    if presale_mint is not None:
        p = presale_mint['params']
        if (req.mint_kind == 'public' or presale_mint['kind'] != req.mint_kind
                or presale_mint['wallet'].lower() != wallet.address.lower()
                or presale_mint['contract'].lower() != drop.contract_address.lower()
                or presale_mint['quantity'] != req.quantity or p[4] != req.onchain_stage_index
                or p[2:4] != (int(aware(stage.start_time_utc).timestamp()), int(aware(stage.end_time_utc).timestamp()))):
            raise HTTPException(409, 'Whitelist preparation differs from the receiving wallet or stage.')
        stage_price, stage_limit = p[0], p[1]
    if not stage.end_time_utc or not 1 <= req.quantity <= min(100, stage_limit):
        raise HTTPException(409, 'Stage needs an exact end time and sufficient quantity limit.')
    start, end = aware(stage.start_time_utc), aware(stage.end_time_utc)
    expiry = aware(req.expires_at) if req.expires_at else min(end, aware(grant.expires_at))
    price = wei(req.price_cap_eth) if req.price_cap_eth is not None else stage_price
    fee = wei(req.fee_cap_eth)
    total = wei(req.total_cap_eth) if req.total_cap_eth is not None else price * req.quantity + fee
    if not max(datetime.now(timezone.utc), start) < expiry <= min(end, aware(grant.expires_at)):
        raise HTTPException(409, 'Submission expiry must fall within the stage and policy validity.')
    scheduled = getattr(req, 'scheduled_for_utc', None)
    execute_at = None
    if scheduled is not None:
        if scheduled.tzinfo is None:
            raise HTTPException(422, 'Mint time must include its time zone; Mintly displays WAT.')
        scheduled = aware(scheduled)
        # Round up fractional seconds rather than execute before the requested instant.
        from math import ceil
        execute_at = ceil(scheduled.timestamp())
        if (scheduled < start or scheduled <= datetime.now(timezone.utc)
                or execute_at >= int(expiry.timestamp())):
            raise HTTPException(409, 'Choose a future mint time within the stage and before the approval expires.')
    if price < stage_price or fee <= 0 or total < stage_price * req.quantity + fee:
        raise HTTPException(409, 'Mint price, gas budget or total ceiling is insufficient.')
    if total > int(grant.scope['max_task_wei']) or total > grant.budget_wei - grant.spent_wei - grant.reserved_wei:
        raise HTTPException(409, 'Automatic policy budget is insufficient, including pending reservations.')
    snapshot = {
        'plan_id': req.plan_id, 'user_id': user_id, 'wallet_id': wallet.id, 'account': to_checksum_address(wallet.address),
        'chain_id': drop.chain_id, 'chain': drop.chain, 'contract': to_checksum_address(drop.contract_address),
        'drop_id': drop.id, 'drop_name': drop.name, 'stage_id': stage.id, 'stage_name': stage.stage_name,
        'mint_kind': req.mint_kind, 'start': int(start.timestamp()), 'end': int(end.timestamp()),
        'expiry': int(expiry.timestamp()), 'quantity': req.quantity, 'price_wei': stage_price,
        'price_cap_wei': price, 'fee_cap_wei': fee, 'total_cap_wei': total,
        'recipient': to_checksum_address(wallet.address), 'mint_page_url': drop.mint_page_url,
        'conditional_eligibility': req.conditional_eligibility,
        'onchain_stage_index': req.onchain_stage_index,
    }
    if execute_at is not None:
        snapshot['execute_at'] = execute_at
    if getattr(req, 'copy_event_id', None):
        from app.models import CopyEvent
        from app.services.copy_mints import enabled as copy_enabled
        copy_enabled()
        event = await db.get(CopyEvent, req.copy_event_id)
        if not event or event.user_id != user_id or event.task_id:
            raise HTTPException(409, 'Copy observation is unavailable or already has a task.')
        o = event.observation
        if (snapshot['mint_kind'] != 'public' or o['chain_id'] != snapshot['chain_id']
                or o['contract'].lower() != snapshot['contract'].lower()
                or any(o[k] != snapshot[k] for k in ('price_wei','start','end'))):
            raise HTTPException(409, 'Copy review differs from the observed public stage.')
        snapshot['copy_source'] = o
    return grant, snapshot


def allows_collection(scope, contract):
    """Explicit task-selected scope; old fixed policies retain their exact allowlist.

    This only selects an NFT collection. The signer still independently decodes
    the pinned SeaDrop call and checks the persisted recipient/quantity/budget.
    Unknown modes and implicit empty allowlists must fail closed.
    """
    if scope.get('collection_scope') == 'reviewed_mints':
        return scope.get('contracts') == []
    if scope.get('collection_scope') is not None:
        return False
    return contract.lower() in [x.lower() for x in scope.get('contracts', [])]


async def validate_mint(web3, snapshot, transaction):
    s = snapshot
    mint = decode_mint(transaction, s['contract'], s['account'], s['quantity'])
    if mint['kind'] != s['mint_kind'] or int(mint['execution']['value']) != s['price_wei'] * s['quantity']:
        raise ValueError('Upstream selected a different mint method, stage or price')
    if s['price_wei'] > s['price_cap_wei'] or s['recipient'].lower() != s['account'].lower():
        raise ValueError('Price or recipient differs from authorization')
    if mint['kind'] == 'public':
        arg = encode(['address'], [s['contract']])
        raw = await web3.eth.call({'to': SEADROP_V1_ADDRESS, 'data': keccak(text='getPublicDrop(address)')[:4] + arg})
        price, start, end, limit, bps, restricted = decode(['uint80','uint48','uint48','uint16','uint16','bool'], raw)
        if (price, start, end) != (s['price_wei'], s['start'], s['end']) or limit < s['quantity']:
            raise ValueError('Public stage changed on chain')
        if restricted or bps:
            allowed = decode(['bool'], await web3.eth.call({'to': SEADROP_V1_ADDRESS,
                'data': keccak(text='getFeeRecipientIsAllowed(address,address)')[:4] + encode(['address','address'], [s['contract'], mint['fee']])}))[0]
            if not allowed:
                raise ValueError('Public fee recipient is not allowed')
        minted, supply, maximum = decode(['uint256'] * 3, await web3.eth.call({
            'to': s['contract'], 'data': keccak(text='getMintStats(address)')[:4] + encode(['address'], [s['account']])}))
        if minted + s['quantity'] > limit or supply + s['quantity'] > maximum:
            raise ValueError('Public wallet limit or collection supply is insufficient')
    else:
        if s.get('onchain_stage_index') is not None and mint['params'][4] != s['onchain_stage_index']:
            raise ValueError('Upstream selected a different on-chain presale stage index')
        stage = SimpleNamespace(starts_at=datetime.fromtimestamp(s['start'], timezone.utc),
            ends_at=datetime.fromtimestamp(s['end'], timezone.utc), price_wei=s['price_wei'], stage_type='presale')
        await verify_presale(web3, mint, stage)
        # The preview displays this value, and Flutter returns it unchanged on arm.
        s['onchain_stage_index'] = mint['params'][4]
    return mint['execution']


async def prepare_mint(web3, snapshot):
    s = snapshot
    if s['mint_kind'] == 'public':
        arg = encode(['address'], [s['contract']])
        fees = decode(['address[]'], await web3.eth.call({'to': SEADROP_V1_ADDRESS,
            'data': keccak(text='getAllowedFeeRecipients(address)')[:4] + arg}))[0]
        fee = fees[0] if fees else '0x' + '0' * 40
        tx = {'to': SEADROP_V1_ADDRESS, 'value': str(s['price_wei'] * s['quantity']),
            'data': '0x' + MINT_PUBLIC_SELECTOR + encode(['address','address','address','uint256'],
                [s['contract'], fee, s['account'], s['quantity']]).hex()}
    else:
        status, tx = await OpenSeaClient().build_mint(collection_slug(s['mint_page_url']), s['account'], s['quantity'])
        if status != 200 or tx is None:
            raise OpenSeaUnavailable('Wallet-specific presale data is unavailable; provider access at opening is required.', 503)
        if CHAINS.get(tx.get('chain'), (None,))[0] != s['chain_id']:
            raise ValueError('Upstream mint chain mismatch')
    return await validate_mint(web3, s, tx)


async def release_reservation(db, task, actual=0):
    auth = await db.get(MintAuthorization, task.authorization_id)
    grant = await db.get(AutomaticGrant, auth.grant_id)
    grant.reserved_wei -= auth.total_spend_cap_wei
    grant.spent_wei += actual
    if task.copy_rule_id:
        from app.models import CopyRule
        rule = await db.get(CopyRule, task.copy_rule_id)
        rule.reserved_wei -= auth.total_spend_cap_wei
        rule.spent_wei += actual
        if rule.reserved_wei < 0:
            raise ValueError('Copy budget reservation invariant violated')
        if rule.spent_wei > rule.budget_wei or actual > auth.total_spend_cap_wei:
            rule.status = 'paused'
    if grant.chain_id == 8453 and (grant.spent_wei > grant.budget_wei or actual > auth.total_spend_cap_wei):
        # Inclusion-time parent fees can change after a bounded submission.
        # Preserve the real charge and stop future signing rather than lose a receipt.
        grant.status = 'disabled'
        from app.models import CopyRule
        await db.execute(update(CopyRule).where(CopyRule.grant_id == grant.id,
            CopyRule.status.in_(['active','registering'])).values(status='paused'))
    elif grant.spent_wei > grant.budget_wei:
        raise ValueError('Budget accounting invariant violated')
    if grant.reserved_wei < 0:
        raise ValueError('Budget accounting invariant violated')


def public_grant(grant):
    expired = aware(grant.expires_at) <= datetime.now(timezone.utc)
    return {'id': grant.id, 'wallet_id': grant.wallet_id, 'account': grant.account,
        'chain_id': grant.chain_id, 'mode': grant.adapter,
        'status': 'expired' if expired else grant.status, 'expires_at': grant.expires_at,
        'budget_wei': str(grant.budget_wei), 'reserved_wei': str(grant.reserved_wei),
        'spent_wei': str(grant.spent_wei), 'remaining_wei': str(max(0, grant.budget_wei - grant.reserved_wei - grant.spent_wei)),
        'scope': grant.scope, 'enforcement': 'Custodial signer policy; not an on-chain wallet permission.'}
