"""Resolve verified instructions; users never supply a proof or guessed stage index."""
from types import SimpleNamespace
from datetime import datetime,timezone
from fastapi import HTTPException
from app.models import Wallet,Drop,MintStage,CopyEvent,CopyWatch,MintPlan
from app.services import automatic
from app.services.mint_plans import aware
from app.services.opensea import OpenSeaClient,OpenSeaUnavailable,collection_slug,CHAINS
from app.services.seadrop_mint import decode_mint,verify_presale


async def own_presale(db,req,user_id,web3):
    wallet=await db.get(Wallet,req.wallet_id)
    drop=await db.get(Drop,req.drop_id)
    stage=await db.get(MintStage,req.stage_id)
    if not wallet or wallet.user_id!=user_id or wallet.archived_at or not drop or not stage or stage.drop_id!=drop.id:
        raise HTTPException(404,'Wallet or mint stage not found.')
    status,tx=await OpenSeaClient().build_mint(collection_slug(drop.mint_page_url),wallet.address,req.quantity)
    if status!=200 or not tx:
        raise HTTPException(409,'Wallet-specific whitelist instructions are not available yet. Try again when the project releases them.')
    if CHAINS.get(tx.get('chain'),(None,))[0]!=drop.chain_id:
        raise HTTPException(409,'Mint network could not be verified.')
    mint=decode_mint(tx,drop.contract_address,wallet.address,req.quantity)
    if mint['kind']=='public' or (getattr(req,'mint_kind',None) not in (None,'auto',mint['kind'])):
        raise HTTPException(409,'The selected whitelist stage is unavailable. Public fallback is disabled.')
    if not stage.end_time_utc or mint['params'][2:4]!=(int(aware(stage.start_time_utc).timestamp()),int(aware(stage.end_time_utc).timestamp())):
        raise HTTPException(409,'The project returned a different mint stage. Reopen the plan to review it.')
    await verify_presale(web3,mint,SimpleNamespace(starts_at=stage.start_time_utc,ends_at=stage.end_time_utc,
        price_wei=mint['params'][0],stage_type='presale'))
    return mint


async def prepare(db,body,user_id):
    grant=await automatic.grant_for(db,body.grant_id,user_id)
    wallet=await db.get(Wallet,body.wallet_id)
    drop=await db.get(Drop,body.drop_id)
    stage=await db.get(MintStage,body.stage_id)
    if not wallet or wallet.user_id!=user_id or wallet.archived_at or wallet.id!=grant.wallet_id or not drop or not stage or stage.drop_id!=drop.id:
        raise HTTPException(404,'Choose your wallet and a verified mint stage.')
    if not stage.end_time_utc:
        raise HTTPException(409,'This stage’s closing time is not verified yet.')
    source_kind=None
    force_presale=False
    deferred=False
    if body.plan_id:
        plan=await db.get(MintPlan,body.plan_id)
        if not plan or plan.user_id!=user_id or plan.archived_at or plan.wallet_id!=wallet.id:
            raise HTTPException(404,'Mint plan not found.')
        force_presale=plan.stage_type is not None and plan.stage_type!='public_sale'
        deferred=bool(force_presale and plan.selected_stage and aware(stage.start_time_utc)>datetime.now(timezone.utc))
    if body.copy_event_id:
        event=await db.get(CopyEvent,body.copy_event_id)
        watch=await db.get(CopyWatch,event.watch_id) if event else None
        if not event or not watch or watch.user_id!=user_id:
            raise HTTPException(404,'Copied mint not found.')
        source_kind=event.observation.get('mint_kind','public')
    web3=await automatic.provider_for(grant.chain_id)
    presale=None
    try:
        from app.services.copy_mints import public_stage
        try:
            public=None if deferred else await public_stage(web3,drop.contract_address)
            is_public=bool(public) and (public['start'],public['end'],public['price_wei'])==(
                int(aware(stage.start_time_utc).timestamp()),int(aware(stage.end_time_utc).timestamp()),stage.price_wei)
        except ValueError:
            is_public=False
        if deferred:
            kind={'signed_presale':'signed','signed_sale':'signed','signed':'signed',
                'allowlist':'allowlist','allowlist_sale':'allowlist'}.get(plan.stage_type)
            if kind is None or body.copy_event_id:
                raise HTTPException(409,'This phase cannot be approved in advance.')
            price,index=stage.price_wei,None
        elif is_public and not force_presale and source_kind in (None,'public'):
            kind,price,index='public',stage.price_wei,None
        else:
            candidate=SimpleNamespace(wallet_id=wallet.id,drop_id=drop.id,stage_id=stage.id,quantity=body.quantity,mint_kind=source_kind or 'auto')
            presale=await own_presale(db,candidate,user_id,web3)
            kind,price,index=presale['kind'],presale['params'][0],presale['params'][4]
        total=automatic.wei(body.maximum_total_eth)
        mint_value=price*body.quantity
        fee=automatic.wei(body.gas_limit_eth) if body.gas_limit_eth is not None else total-mint_value
        if not 0<fee<=total-mint_value:
            raise HTTPException(422,'Maximum total spend must include the NFT price and a positive gas allowance.')
        from app.schemas.task import DraftTaskRequest
        from app.services.parser import format_wei_to_eth
        req=DraftTaskRequest(guided=True,plan_id=body.plan_id,copy_event_id=body.copy_event_id,wallet_id=wallet.id,
            grant_id=grant.id,drop_id=drop.id,stage_id=stage.id,quantity=body.quantity,mint_kind=kind,
            price_cap_eth=format_wei_to_eth(price),fee_cap_eth=format_wei_to_eth(fee),total_cap_eth=format_wei_to_eth(total),
            scheduled_for_utc=body.scheduled_for_utc,onchain_stage_index=index,conditional_eligibility=deferred)
        grant,snapshot=await automatic.make_snapshot(db,req,user_id,presale_mint=presale)
        execution=None if deferred else presale['execution'] if presale else await automatic.prepare_mint(web3,snapshot)
        await automatic.signer_ready(grant.id)
        return {'snapshot':snapshot,'request':req.model_dump(mode='json'),'review_hash':automatic.digest(snapshot),
            'eligibility':'verified_waiting_for_instructions' if deferred else 'verified','execution_ready':execution is not None,'is_signer_ready':True,'policy':automatic.public_grant(grant),
            'breakdown':{'mint_value_wei':str(mint_value),'gas_limit_wei':str(fee),'maximum_total_wei':str(total)}}
    finally:
        await web3.provider.disconnect()
