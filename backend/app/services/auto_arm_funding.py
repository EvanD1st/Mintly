"""Small queued holds; buffered transaction liability is funded at execution."""
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.models import DailyDebit, MintTask, MintAuthorization, AutomaticGrant, User
from app.services.mint_plans import aware

QUEUED_WEI=10**13  # ETH queued hold, not a gas ceiling.
ETH_GAS_CEILING_WEI=2*10**13  # 0.00002 ETH per Auto-Arming transaction.


def fee_ceiling(chain_id, approved):
    from app.services.networks import symbol
    return min(approved,ETH_GAS_CEILING_WEI) if symbol(chain_id)=='ETH' else approved


def execution_ceiling(snapshot):
    approved=min(snapshot['fee_cap_wei'],snapshot['total_cap_wei'])
    return fee_ceiling(snapshot['chain_id'],approved) if snapshot.get('feed_approval_id') else approved


def execution_liability(snapshot,value,fee):
    if snapshot.get('feed_approval_id') and fee>execution_ceiling(snapshot):
        raise HTTPException(503,'Gas is above the Auto-Arming limit. Waiting for lower fees. No transaction sent.')
    if fee>snapshot['fee_cap_wei'] or value+fee>snapshot['total_cap_wei']:
        raise ValueError('Estimated gas or total debit exceeds task authorization')
    return value+fee if snapshot.get('feed_approval_id') else snapshot['total_cap_wei']


async def queued_amount(chain_id, maximum, *, strict=True):
    from app.services.networks import symbol
    currency=symbol(chain_id)
    if currency=='ETH':return min(QUEUED_WEI,maximum)
    from app.services.reservation_quote import dollar_native_wei
    amount=await dollar_native_wei(currency)
    if amount is None:
        if strict:raise HTTPException(503,f'{currency} price is unavailable. Auto-Arming will retry when its $1 reservation can be checked.')
        return maximum  # Preserve existing holds if a fresh quote is unavailable.
    return min(amount,maximum)

async def queued(auth, *, strict=False):
    if not auth.snapshot.get('feed_approval_id'):return auth.total_spend_cap_wei
    return await queued_amount(auth.snapshot['chain_id'],auth.total_spend_cap_wei,strict=strict)

async def held(db,task,auth):
    debit=await db.get(DailyDebit,task.id)
    return debit.maximum_wei if debit else auth.total_spend_cap_wei

async def resize(db,task,auth,grant,amount,*,restore=False):
    old=await held(db,task,auth)
    delta=amount-old
    if not restore and delta>0 and delta>grant.budget_wei-grant.spent_wei-grant.reserved_wei:
        raise HTTPException(503,'Waiting for earlier mints to release signing allowance. No transaction sent.')
    debit=await db.get(DailyDebit,task.id)
    if not debit:
        from app.services.daily_budget import day_key
        from app.services.networks import symbol
        debit=DailyDebit(task_id=task.id,user_id=grant.user_id,day=day_key(task.scheduled_for_utc),
            maximum_wei=amount,currency=symbol(grant.chain_id))
        db.add(debit)
    else:
        if debit.actual_wei is not None:raise ValueError('A settled reservation cannot be resized')
        debit.maximum_wei=amount
    grant.reserved_wei+=delta
    if grant.reserved_wei<0:raise ValueError('Reservation accounting invariant violated')
    await db.flush()

async def fund(db,task,auth,grant,*,restore=False,journal=None,now=None,amount=None):
    if not auth.snapshot.get('feed_approval_id'):return
    if restore:
        # The private journal survives a lost DB commit. Never re-quote or shrink
        # an already signed transaction's unresolved liability.
        entry=journal.execute('SELECT liability FROM signed WHERE task=?',(task.id,)).fetchone() if journal is not None else None
        amount=entry['liability'] if entry else auth.total_spend_cap_wei
    elif amount is None:
        amount=auth.total_spend_cap_wei
    if not isinstance(amount,int) or not 0<amount<=auth.total_spend_cap_wei:
        raise ValueError('Execution liability exceeds task authorization')
    if not restore:
        now=now or datetime.now(timezone.utc)
        if aware(task.scheduled_for_utc)>now:raise HTTPException(503,'Waiting for this mint to open.')
        earlier=(await db.scalars(select(MintTask).where(MintTask.wallet_id==task.wallet_id,
            MintTask.id!=task.id,MintTask.status.in_(('armed','preparing')),
            MintTask.scheduled_for_utc<=now).order_by(MintTask.scheduled_for_utc,MintTask.created_at,MintTask.id))).all()
        for other in earlier:
            a=await db.get(MintAuthorization,other.authorization_id)
            if not a or not a.snapshot.get('feed_approval_id') or a.snapshot['chain_id']!=auth.snapshot['chain_id']:continue
            if (aware(other.scheduled_for_utc),aware(other.created_at),other.id)<(aware(task.scheduled_for_utc),aware(task.created_at),task.id):
                raise HTTPException(503,'An earlier-opening Auto-Arming mint has priority. Waiting to retry.')
        # Only signer-verified unsigned future holds may yield to this opening.
        if journal is not None:
            from app.services import daily_budget
            from app.services.networks import symbol
            currency=symbol(grant.chain_id)
            owner=await daily_budget.limit_owner(db,await db.get(User,grant.user_id),currency)
            later=(await db.execute(select(MintTask,MintAuthorization).join(MintAuthorization,
                MintTask.authorization_id==MintAuthorization.id).join(AutomaticGrant,MintAuthorization.grant_id==AutomaticGrant.id)
                .where(AutomaticGrant.user_id==grant.user_id,
                MintTask.id!=task.id,MintTask.status.in_(('armed','preparing')),
                MintTask.signed_tx_raw.is_(None),MintTask.transaction_hash.is_(None)))).all()
            for other,a in later:
                if not a.snapshot.get('feed_approval_id') or journal.execute('SELECT 1 FROM signed WHERE task=?',(other.id,)).fetchone():continue
                if (aware(other.scheduled_for_utc),aware(other.created_at),other.id)<(aware(task.scheduled_for_utc),aware(task.created_at),task.id):continue
                other_grant=await db.get(AutomaticGrant,a.grant_id)
                if a.grant_id!=grant.id and symbol(other_grant.chain_id)!=currency:continue
                old=await held(db,other,a)
                target=await queued(a)
                if old>target:await resize(db,other,a,other_grant,target)
                policy_shortage=(a.grant_id==grant.id and
                    amount-await held(db,task,auth)>grant.budget_wei-grant.spent_wei-grant.reserved_wei)
                daily_shortage=False
                if owner.daily_limit_wei is not None:
                    used=await daily_budget.usage(db,grant.user_id,daily_budget.day_key(now),excluding=task.id,currency=currency)
                    daily_shortage=used['spent_wei']+used['reserved_wei']+amount>owner.daily_limit_wei
                if policy_shortage or daily_shortage:await resize(db,other,a,other_grant,0)
    await resize(db,task,auth,grant,amount,restore=restore)

def quantity(task,authorized):
    try:
        value=json.loads(task.prepared_calldata or '{}').get('quantity')
        if task.signed_tx_raw and isinstance(value,int) and 1<=value<=authorized:return value
    except (ValueError,TypeError,AttributeError):pass
    return authorized

def signed_quantity(raw,maximum):
    from eth_account._utils.legacy_transactions import Transaction
    data=Transaction.from_bytes(bytes.fromhex(raw.removeprefix('0x'))).data
    count=int.from_bytes(data[100:132],'big') if len(data)>=132 else 0
    if not 1<=count<=maximum:raise ValueError('Signed quantity exceeds approval')
    return count

async def adapt_quantity(db,journal,task,s,grant,web3):
    if not s.get('feed_approval_id'):return s
    pin=journal.execute('SELECT snapshot FROM feed_approvals WHERE id=?',(s['feed_approval_id'],)).fetchone()
    if not pin or json.loads(pin['snapshot']).get('quantity_mode')!='wallet_max':return s
    from eth_abi import encode,decode
    from eth_utils import keccak,to_checksum_address
    from app.services.opensea import OpenSeaUnavailable
    minted,supply,maximum=decode(['uint256']*3,await web3.eth.call({'to':to_checksum_address(s['contract']),
        'data':keccak(text='getMintStats(address)')[:4]+encode(['address'],[to_checksum_address(s['account'])])}))
    if supply>=maximum:raise OpenSeaUnavailable('This collection is sold out. No transaction was sent.',409,mint_reason='supply_exhausted')
    if s['mint_kind']=='public':
        remaining=max(0,s['phase_identity']['max_per_wallet']-minted)
    else:
        from app.models import Wallet
        from app.services.mint_stage_choice import wallet_stages
        from app.services.opensea import collection_slug
        from app.services.phase_identity import stage_key
        wallet=await db.get(Wallet,grant.wallet_id)
        result,_=await wallet_stages(db,wallet,collection_slug(s['mint_page_url']),grant.chain_id,s['contract'])
        phase=next((p for p in result['stages'] if stage_key(p['id'])==stage_key(s['phase_identity']['uuid'])),None)
        if not phase or phase['eligibility']!='eligible' or phase.get('remaining') is None:
            raise OpenSeaUnavailable('Wallet eligibility is not verified for this phase. Waiting to retry.',503)
        remaining=phase['remaining']
    count=min(s['quantity'],remaining,maximum-supply)
    if count<=0:raise OpenSeaUnavailable('This wallet has no remaining mint allowance.',409,mint_reason='wallet_limit')
    if count!=s['quantity']:
        s={**s,'quantity':count};s.pop('execution',None)
    return s
