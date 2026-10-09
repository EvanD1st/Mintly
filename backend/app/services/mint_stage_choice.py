"""Explicit stage discovery/selection does not authorize a mint."""
from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy import select,or_
from app.models import Wallet,OpenSeaAccess,MintTask,MintPermission
from app.services import automatic
from app.services.mint_plans import aware
from app.services.opensea import OpenSeaClient,stage_schedule


def pinned(stage):
    return {key:(int(stage[key].timestamp()) if key in ('starts_at','ends_at') else stage[key])
        for key in ('uuid','type','starts_at','ends_at','price_wei','max_per_wallet')}


async def stages(db,plan,user_id):
    wallet=await db.get(Wallet,plan.wallet_id)
    if plan.user_id!=user_id or plan.archived_at or not wallet or wallet.archived_at or wallet.user_id!=user_id:
        raise HTTPException(404,'Mint plan not found.')
    client=OpenSeaClient();detail=await client.get_drop(plan.collection_slug)
    from app.services.opensea import CHAINS
    if CHAINS[detail['chain']][0]!=plan.chain_id or detail['contract_address'].lower()!=plan.contract_address.lower():
        raise HTTPException(409,'The collection network or contract changed.')
    schedule=stage_schedule(detail)
    consent=await db.get(OpenSeaAccess,wallet.id)
    access=bool(consent and consent.user_id==user_id and consent.enabled and aware(consent.expires_at)>datetime.now(timezone.utc))
    lookup={};note=None
    if access:
        try:
            from app.api.opensea_access import broker
            response=await broker(wallet.id,'stages',slug=plan.collection_slug,key=await client._key())
            if response.get('address','').lower()!=wallet.address.lower():raise ValueError('Wallet result differs')
            lookup={row['stage_uuid']:row for row in response['stages']}
        except Exception:
            note='Eligibility could not be verified now. Public stage details are still available.'
    else:note='Enable read-only OpenSea access to check your whitelist stages.'
    minted=supply=maximum=None;public=None
    try:
        from eth_abi import encode,decode
        from eth_utils import keccak,to_checksum_address
        web3=await automatic.provider_for(plan.chain_id)
        try:
            minted,supply,maximum=decode(['uint256']*3,await web3.eth.call({'to':plan.contract_address,
                'data':keccak(text='getMintStats(address)')[:4]+encode(['address'],[to_checksum_address(wallet.address)])}))
            from app.services.copy_mints import public_stage
            public=await public_stage(web3,plan.contract_address)
        finally:await web3.provider.disconnect()
    except Exception:
        if note is None:note='Eligibility found; remaining allowance could not be checked on-chain. It will be checked before signing.'
    result=[]
    now=datetime.now(timezone.utc)
    for stage in schedule:
        own=lookup.get(stage['uuid'],{})
        eligible=own.get('eligible') if own.get('eligible') is not None else True if stage['type']=='public_sale' else None
        remaining=own.get('remaining')
        total=own.get('max_total_mintable_by_wallet')
        if stage['type']=='public_sale' and public and (public['start'],public['end'],public['price_wei'])==(
            int(stage['starts_at'].timestamp()),int(stage['ends_at'].timestamp()),stage['price_wei']):
            total=min(total,public['limit']) if total is not None else public['limit']
        if total is not None and minted is not None:
            remaining=max(0,total-minted)
            if supply is not None:remaining=min(remaining,max(0,maximum-supply))
        # A published stage default is not the wallet's accumulated remaining allowance.
        result.append({'id':stage['uuid'],'name':stage['name'],'type':stage['type'],
            'eligibility':'eligible' if eligible is True else 'not_eligible' if eligible is False else 'unverified',
            'remaining':remaining,'wallet_total_limit':total,'default_limit':stage['max_per_wallet'],
            'price_wei':str(own.get('price_wei') if own.get('price_wei') is not None else stage['price_wei']) if stage['price_wei'] is not None else None,
            'starts_at':stage['starts_at'].isoformat(),'ends_at':stage['ends_at'].isoformat(),
            'timing':'ended' if stage['ends_at']<=now else 'upcoming' if stage['starts_at']>now else 'open',
            'selected':bool(plan.selected_stage and plan.selected_stage['uuid']==stage['uuid'])})
    return {'wallet_id':wallet.id,'address':wallet.address,'stages':result,'access_enabled':access,'note':note},schedule


async def select_stage(db,plan,body,user_id):
    await automatic.lock_execution(db)
    pending=await db.scalar(select(MintTask.id).where(MintTask.plan_id==plan.id,or_(
        MintTask.status.not_in(automatic.TERMINAL),
        MintTask.signed_tx_raw.is_not(None)&MintTask.status.not_in(('confirmed','reverted')))).limit(1))
    legacy=await db.scalar(select(MintPermission.id).where(MintPermission.plan_id==plan.id,
        MintPermission.status.in_(('awaiting_signature','armed','prepared','submitted','uncertain'))).limit(1))
    if pending or legacy:raise HTTPException(409,'This plan already has a mint in progress. Manage that mint before changing its phase.')
    await db.commit()  # Discovery does not hold the execution lock through HTTP.
    result,schedule=await stages(db,plan,user_id)
    stage=next((stage for stage in schedule if stage['uuid']==body.stage_uuid),None)
    item=next((stage for stage in result['stages'] if stage['id']==body.stage_uuid),None)
    if not stage or item['timing']=='ended':raise HTTPException(409,'This phase has ended or is no longer available.')
    if item['eligibility']=='not_eligible':raise HTTPException(409,'This wallet is not eligible for that phase.')
    if item['remaining'] is not None and body.quantity>item['remaining']:
        raise HTTPException(409,'Quantity exceeds this wallet’s verified remaining allowance.')
    await automatic.lock_execution(db);await db.refresh(plan)
    wallet=await db.get(Wallet,plan.wallet_id,populate_existing=True)
    if plan.user_id!=user_id or plan.archived_at or wallet.archived_at:raise HTTPException(409,'The plan or wallet changed.')
    pending=await db.scalar(select(MintTask.id).where(MintTask.plan_id==plan.id,MintTask.status.not_in(automatic.TERMINAL)).limit(1))
    if pending:raise HTTPException(409,'The plan was armed while checking its phases.')
    plan.selected_stage=pinned(stage);plan.quantity=body.quantity
    plan.stage_uuid=stage['uuid'];plan.stage_name=stage['name'];plan.stage_type=stage['type']
    plan.starts_at=stage['starts_at'];plan.ends_at=stage['ends_at'];plan.price_wei=stage['price_wei']
    plan.automatic_drop_id=plan.automatic_stage_id=None
    plan.status='scheduled';plan.status_note='Selected phase saved. Exact eligibility and mint limits are verified before arming.'
    from app.api.mint_plans import record_plan
    record_plan(db,plan,wallet,'phase_selected');await db.commit()
    return plan,wallet
