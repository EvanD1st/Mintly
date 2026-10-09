"""Read-only mint evaluation: no tasks, nonce allocation, reservations or signer."""
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.models import CopyCheck, CopyCheckResult, CopyEvent, Wallet, User
from app.services import automatic, copy_mints
from app.services.mint_plans import aware
from app.services.automatic_fees import quote_gas, maximum_fee


async def evaluate(web3,observation,snapshot,*,now=None):
    o,r = observation,snapshot
    now = now or datetime.now(timezone.utc)
    kind=o.get('mint_kind','public')
    if o['block_number'] <= r['after_blocks'].get(str(o['chain_id']),0):
        return {'status':'would_skip','note':'Earlier mint. New copy approvals do not spend on past activity.'}
    latest=await web3.eth.get_block('latest')
    if not o['start'] <= max(int(now.timestamp()),latest.timestamp) < o['end']:
        return {'status':'would_skip','note':'This mint stage is not open.'}
    if kind not in r['mint_kinds']:
        return {'status':'would_skip','note':'Whitelist copying is off in these settings.'}
    await copy_mints.verify_source(web3,o)
    if kind == 'public':
        count=(await copy_mints.maximum_free_quantity(web3,o,r) if r['quantity_mode']=='max_free' else
            await copy_mints.maximum_available_quantity(web3,o,r) if r['quantity_mode']=='max_available' else r['quantity'])
        price=o['price_wei']
        s={**o,'mint_kind':kind,'account':r['account'],'recipient':r['account'],'quantity':count,
            'price_cap_wei':r['price_cap_wei']}
        execution=await automatic.prepare_mint(web3,s)
    else:
        mint,_=await copy_mints.prepare_presale_copy(web3,o,r)
        count,price,execution=mint['quantity'],mint['params'][0],mint['execution']
    if price > r['price_cap_wei'] or (r['free_only'] and price != 0):
        return {'status':'would_skip','note':'Mint price exceeds these limits.'}
    tx={'from':r['account'],'to':execution['target'],'data':execution['data'],'value':int(execution['value'])}
    gas,gas_price=await quote_gas(web3,tx,o['chain_id'])
    fee=await maximum_fee(web3,tx,o['chain_id'],gas,gas_price)
    if fee > r['fee_cap_wei']:
        return {'status':'would_skip','note':'Gas exceeds the spending limit.'}
    if tx['value']+fee > r['budget_wei']:
        return {'status':'would_skip','note':'This mint exceeds the check-only budget.'}
    if await web3.eth.get_balance(r['account'],'pending') < tx['value']+fee:
        return {'status':'would_skip','note':copy_mints.funding_note(o['chain_id'],price>0)}
    await web3.eth.call({**tx,'gas':gas,'gasPrice':gas_price},'pending')
    return {'status':'would_copy','note':'Checks passed now. No transaction was signed or sent.',
        'quantity':count,'estimated_fee_wei':fee,'maximum_wei':tx['value']+fee}


async def process(db,watch,chain):
    check=await db.get(CopyCheck,watch.id)
    if not check or not check.active or aware(check.expires_at)<=datetime.now(timezone.utc):
        return
    wallet=await db.get(Wallet,check.wallet_id)
    if not wallet or wallet.archived_at or wallet.user_id!=watch.user_id:
        check.active=False
        return
    version=check.version
    snapshot=dict(check.snapshot)
    events=(await db.scalars(select(CopyEvent).where(CopyEvent.watch_id==watch.id).order_by(CopyEvent.created_at.desc()).limit(25))).all()
    candidates=[]
    for event in events:
        key=automatic.digest(['check',version,event.id])
        if event.observation['chain_id']==chain and not await db.get(CopyCheckResult,key):
            candidates.append((key,event.id,dict(event.observation)))
    await db.commit()  # RPC evaluation never holds the execution lock.
    web3=await automatic.provider_for(chain)
    results=[]
    try:
        for key,event_id,observation in candidates:
            try:
                result=await evaluate(web3,observation,snapshot)
                if result['status']=='would_copy':
                    from app.services.daily_budget import usage
                    user=await db.get(User,watch.user_id,populate_existing=True)
                    used=await usage(db,user.id)
                    if user.daily_limit_wei is not None and sum(used.values())+result['maximum_wei']>user.daily_limit_wei:
                        result={'status':'would_skip','note':'Daily spending limit has no room for this mint.'}
            except HTTPException as error:
                result={'status':'would_skip','note':str(error.detail)}
            except ValueError:
                result={'status':'would_skip','note':'The stage or receiving-wallet eligibility changed.'}
            except Exception as error:
                if copy_mints.balance_error(error):
                    result={'status':'would_skip','note':copy_mints.funding_note(chain)}
                else:
                    result={'status':'unavailable','note':'Checks could not complete. No transaction was sent.'}
            results.append((key,event_id,result))
    finally:
        await web3.provider.disconnect()
    await automatic.lock_execution(db)
    await db.refresh(check)
    await db.refresh(watch)
    await db.refresh(wallet)
    if not check.active or check.version!=version or watch.archived_at or wallet.archived_at:
        return
    for key,event_id,result in results:
        if not await db.get(CopyCheckResult,key):
            db.add(CopyCheckResult(id=key,user_id=watch.user_id,watch_id=watch.id,wallet_id=check.wallet_id,
                event_id=event_id,version=version,status=result['status'],note=result['note'],
                quantity=result.get('quantity'),estimated_fee_wei=result.get('estimated_fee_wei')))
    await db.flush()
