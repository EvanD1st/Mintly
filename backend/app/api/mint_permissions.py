"""Explicit one-use signing permissions; no wallet keys accepted."""
import secrets
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_db
from app.config import settings
from app.models import MintPermission, MintPlan, Wallet, User
from app.services.seadrop_mint import verified_mint_execution
from app.services.direct_wallet_gas import quote_operation, maximum_gas, mint_call, userop_typed_data
from app.services.auth import token_digest
from app.services.mint_plans import aware, refresh_mint_plan
from app.services.opensea import CHAINS, OpenSeaClient, OpenSeaUnavailable
from app.services.mint_permission import checked_provider, relayer_account, permission_typed_data, validate_signature, revoke_calldata, scheduled_public_execution, with_gas_reimbursement, total_user_debit

def user_cost(plan,execution):
    value=total_user_debit(execution)
    gas=int(execution.get('direct_gas',{}).get('max_gas_wei',execution.get('gas_reimbursement',{}).get('value',0)))
    if 'direct_gas' in execution: value=int(execution['value'])+gas
    eth=format(Decimal(value)/Decimal(10**18),'f')
    fresh=plan.rate_checked_at and aware(plan.rate_checked_at)>datetime.now(timezone.utc)-timedelta(minutes=5)
    usdt=format(Decimal(eth)*Decimal(plan.eth_usdt_rate),'.4f') if plan.eth_usdt_rate and fresh else None
    return {'user_debit_eth':eth,'user_debit_usdt':usdt,'gas_payer':'user','gas_mode':'direct_wallet' if 'direct_gas' in execution else 'relayer_reimbursement','gas_fee_wei':str(gas),'gas_fee_eth':format(Decimal(gas)/Decimal(10**18),'f'),'total_value_wei':str(value),'rate_source':'Coinbase ETH-USDT'}

router=APIRouter(prefix='/mint-permissions',tags=['mint-permissions'])
public_router=APIRouter(prefix='/mint-permission-link',tags=['mint-permission-link'])

class CreatePermission(BaseModel):
    plan_id: str
    max_mint_value_wei: str = Field(pattern=r'^[0-9]{1,19}$')
    expiry_minutes: int = Field(default=15,ge=1,le=30,strict=True)

class PermissionCode(BaseModel):
    code: str = Field(pattern=r'^[0-9a-f]{32}$')

class SignPermission(PermissionCode):
    signature: str = Field(pattern=r'^0x[0-9a-fA-F]{130}$')
    userop_signature: str | None = Field(default=None,pattern=r'^0x[0-9a-fA-F]{130}$')

def public_status(p):
    return {'id':p.id,'plan_id':p.plan_id,'status':p.status,'note':p.note,'expires_at':p.expires_at,'execute_after':p.execute_after,'tx_hash':p.tx_hash}

def enabled():
    if not settings.ENABLE_MINT_PERMISSIONS:
        raise HTTPException(409,'Mint-only permissions are not enabled for live execution yet.')

@router.get('')
async def list_permissions(user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    items=(await db.execute(select(MintPermission).where(MintPermission.user_id==user.id).order_by(MintPermission.created_at.desc()))).scalars().all()
    return [public_status(p) for p in items]

@router.post('')
async def create_permission(req:CreatePermission,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    enabled()
    plan=(await db.execute(select(MintPlan).where(MintPlan.id==req.plan_id,MintPlan.user_id==user.id).with_for_update())).scalar_one_or_none()
    if plan is None: raise HTTPException(404,'Mint plan not found.')
    wallet=(await db.execute(select(Wallet).where(Wallet.id==plan.wallet_id,Wallet.user_id==user.id,Wallet.is_demo.is_(False)))).scalar_one_or_none()
    if wallet is None: raise HTTPException(409,'Linked wallet unavailable.')
    existing=(await db.execute(select(MintPermission.id).where(MintPermission.plan_id==plan.id,MintPermission.status.in_(['awaiting_signature','armed','prepared','submitted'])))).first()
    if existing: raise HTTPException(409,'This plan already has a pending permission. Cancel it before creating another.')
    try:
        direct=settings.ENABLE_DIRECT_WALLET_GAS
        account=None if direct else relayer_account()
        if account and account.address.lower()==wallet.address.lower():
            raise OpenSeaUnavailable('The operator relayer must be separate from the user wallet.',409)
        client=OpenSeaClient()
        tx={}
        await refresh_mint_plan(plan,wallet,client,transaction_out=tx)
        if plan.status not in ['ready_for_approval','scheduled']:
            raise OpenSeaUnavailable('The wallet has no verified mint transaction to authorize. Refresh its eligibility.',409)
        now=datetime.now(timezone.utc)
        execute_after=max(now,aware(plan.starts_at))
        if execute_after>now+timedelta(hours=24):
            raise OpenSeaUnavailable('Automatic mints can be authorized at most 24 hours before the stage opens.',409)
        web3=await checked_provider(next(k for k,v in CHAINS.items() if v[0]==plan.chain_id),wallet.address)
        try:
            operator_balance = await web3.eth.get_balance(account.address) if account else 0
            operation = await quote_operation(web3,plan.chain_id,wallet.address) if direct else None
            if plan.status=='scheduled':
                if plan.stage_type!='public_sale':
                    raise OpenSeaUnavailable('OpenSea has not supplied this wallet’s allowlist proof before the stage opens. Check again at its start; no permission was armed.',409)
                tx=await scheduled_public_execution(web3,plan,wallet)
            # A fixed fee budget is quoted before signing; never silently increased.
            gas_quote = int(await web3.eth.gas_price) * 450000
            user_balance = await web3.eth.get_balance(wallet.address)
            execution=await verified_mint_execution(web3,tx,plan,wallet)
        finally: await web3.provider.disconnect()
        if tx.get('chain') not in CHAINS or CHAINS[tx['chain']][0]!=plan.chain_id:
            raise OpenSeaUnavailable('OpenSea could not verify the exact mint for permission.',409)
        if int(execution['value'])>int(req.max_mint_value_wei) or (plan.mint_value_wei is not None and int(execution['value'])!=plan.mint_value_wei):
            raise OpenSeaUnavailable('Mint price changed or exceeds your cap. Refresh the cost preview.',409)
        if direct:
            execution={**execution,'direct_gas':{'operation':operation,'max_gas_wei':str(maximum_gas(operation))}}
        else:
            execution=with_gas_reimbursement(execution,account.address,gas_quote)
        if not direct and operator_balance < gas_quote:
            quoted_eth=format(Decimal(gas_quote)/Decimal(10**18),'f')
            raise OpenSeaUnavailable(f'Operator gas relayer needs funding of at least {quoted_eth} ETH on this network for this quote. Users reimburse successful execution.',409)
        if user_balance < int(execution['value']) + (maximum_gas(operation) if direct else gas_quote):
            raise OpenSeaUnavailable('Your wallet needs the mint price plus the quoted gas fee before authorizing.',409)
        expiry=min(execute_after+timedelta(minutes=req.expiry_minutes),aware(plan.ends_at))
        code=secrets.token_hex(16)
        typed=permission_typed_data(plan.chain_id,wallet.address,wallet.address if direct else account.address,execution,int(execute_after.timestamp())-1,int(expiry.timestamp()))
        p=MintPermission(user_id=user.id,plan_id=plan.id,code_hash=token_digest(code),typed_data=typed,execution=execution,execute_after=execute_after,expires_at=expiry,signature_deadline=min(expiry,now+timedelta(minutes=5)),status='awaiting_signature',note='Approve the exact mint permission and then its gas-capped operation in MetaMask. Your main wallet pays gas; failed execution can consume gas.' if direct else 'Approve one exact mint and a fixed gas reimbursement in MetaMask. Both execute atomically.')
        db.add(p); await db.commit()
        return {**public_status(p),**user_cost(plan,execution),'code':code,'approve_url':settings.PUBLIC_URL.rstrip('/')+'/authorize-mint'}
    except OpenSeaUnavailable as error:
        await db.rollback(); raise HTTPException(error.status,str(error)) from error

async def code_permission(code,db):
    p=(await db.execute(select(MintPermission).where(MintPermission.code_hash==token_digest(code)).with_for_update())).scalar_one_or_none()
    now=datetime.now(timezone.utc)
    if not p or p.status not in ['awaiting_signature','cancelled'] or aware(p.signature_deadline)<=now:
        raise HTTPException(404,'Permission code expired or unavailable.')
    user=await db.get(User,p.user_id)
    if not user or not user.is_active or user.deleted_at: raise HTTPException(404,'Permission unavailable.')
    return p

@public_router.post('/challenge')
async def challenge(req:PermissionCode,db:AsyncSession=Depends(get_db)):
    enabled(); p=await code_permission(req.code,db)
    plan=await db.get(MintPlan,p.plan_id)
    if p.status=='cancelled':
        if not p.signature: raise HTTPException(409,'No spending signature was granted; nothing needs on-chain revocation.')
        return {'mode':'revoke','wallet_address':p.typed_data['message']['delegator'],'chain_id':plan.chain_id,
                'transaction':{'to':p.typed_data['domain']['verifyingContract'],'data':revoke_calldata(p.typed_data,p.signature),'value':'0x0'},
                'collection':plan.collection_name}
    return {**user_cost(plan,p.execution),'typed_data':p.typed_data,'wallet_address':p.typed_data['message']['delegator'],'chain_id':plan.chain_id,
            'stage_name':plan.stage_name,'stage_type':plan.stage_type,'collection':plan.collection_name,'nft_contract':plan.contract_address,'quantity':plan.quantity,'mint_value_wei':p.execution['value'],
            'execute_after':p.execute_after,'expires_at':p.expires_at,'note':p.note}

@public_router.post('/prepare-userop')
async def prepare_userop(req:SignPermission,db:AsyncSession=Depends(get_db)):
    enabled(); p=await code_permission(req.code,db)
    if p.status!='awaiting_signature' or 'direct_gas' not in p.execution:
        raise HTTPException(409,'Direct wallet gas permission unavailable.')
    wallet=p.typed_data['message']['delegator']
    try: validate_signature(p.typed_data,req.signature,wallet)
    except OpenSeaUnavailable as error: raise HTTPException(error.status,str(error)) from error
    stored=p.execution['direct_gas']
    if p.signature and p.signature!=req.signature:
        raise HTTPException(409,'Permission already bound to a signature. Start a new permission.')
    op={**stored['operation'],'callData':mint_call(p.typed_data,req.signature,p.execution)}
    p.signature=req.signature
    p.execution={**p.execution,'direct_gas':{**stored,'operation':op}}
    await db.commit()
    return {'typed_data':userop_typed_data(p.typed_data['domain']['chainId'],op),'max_gas_wei':stored['max_gas_wei']}

@public_router.post('/complete')
async def complete(req:SignPermission,db:AsyncSession=Depends(get_db)):
    enabled(); p=await code_permission(req.code,db)
    if p.status!='awaiting_signature': raise HTTPException(409,'This code is for revocation, not mint approval.')
    try:
        validate_signature(p.typed_data,req.signature,p.typed_data['message']['delegator'])
    except OpenSeaUnavailable as error: raise HTTPException(error.status,str(error)) from error
    if 'direct_gas' in p.execution:
        if p.signature!=req.signature or not req.userop_signature:
            raise HTTPException(409,'Approve the prepared gas-paying operation before arming.')
        op={**p.execution['direct_gas']['operation'],'signature':req.userop_signature}
        try: validate_signature(userop_typed_data(p.typed_data['domain']['chainId'],op),req.userop_signature,p.typed_data['message']['delegator'])
        except OpenSeaUnavailable as error: raise HTTPException(error.status,str(error)) from error
        p.execution={**p.execution,'direct_gas':{**p.execution['direct_gas'],'operation':op}}
    p.signature=req.signature; p.status='armed'; p.note='Exact mint and capped gas-paying operation approved; awaiting scheduled bundler submission.' if 'direct_gas' in p.execution else 'One exact mint authorized; awaiting the relayer.'
    await db.commit(); return public_status(p)

@router.post('/{permission_id}/revocation')
async def request_revocation(permission_id:str,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    p=(await db.execute(select(MintPermission).where(MintPermission.id==permission_id,MintPermission.user_id==user.id).with_for_update())).scalar_one_or_none()
    if not p: raise HTTPException(404,'Permission not found.')
    if p.status!='cancelled' or not p.signature: raise HTTPException(409,'Cancel a signed permission before requesting on-chain revocation.')
    code=secrets.token_hex(16); p.code_hash=token_digest(code)
    p.signature_deadline=datetime.now(timezone.utc)+timedelta(minutes=5)
    await db.commit()
    return {'code':code,'approve_url':settings.PUBLIC_URL.rstrip('/')+'/authorize-mint'}

@router.post('/{permission_id}/cancel')
async def cancel(permission_id:str,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    p=(await db.execute(select(MintPermission).where(MintPermission.id==permission_id,MintPermission.user_id==user.id).with_for_update())).scalar_one_or_none()
    if p is None: raise HTTPException(404,'Permission not found.')
    if p.status not in ['awaiting_signature','armed']:
        raise HTTPException(409,'This mint is already signed for broadcast or finished. A submitted transaction cannot be cancelled here.')
    p.status='cancelled'; p.note='Cancelled in Mintly. Any signed delegation remains valid on-chain until expiry; revoke it in your wallet for on-chain revocation.'
    await db.commit(); return public_status(p)
