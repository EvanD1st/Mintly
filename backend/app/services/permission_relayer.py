"""Operator-gas EOA redeems an exact, single-use user delegation.

Persist signed bytes before submission; retry only the same bytes/hash.
No replacement, mint-price increase, second attempt with a fresh nonce, or user key.
"""
from datetime import datetime, timezone
from sqlalchemy import select, text, or_, and_
from eth_utils import to_checksum_address
from web3.exceptions import TransactionNotFound
from app.services.seadrop_mint import decode_mint, verify_presale
from app.config import settings
from app.models import MintPermission, MintPlan, Wallet, User
from app.services.mint_plans import aware
from app.services.mint_permission import REGISTRY, checked_provider, relayer_account, redeem_calldata, validate_signature
from app.services.opensea import CHAINS

async def process_one_permission(db):
    if not settings.ENABLE_MINT_PERMISSIONS: return
    # Serialize the operator nonce across workers; held through durable preparation.
    if db.bind.dialect.name == 'postgresql':
        await db.execute(text('SELECT pg_advisory_xact_lock(731654202)'))
    now=datetime.now(timezone.utc)
    p=(await db.execute(select(MintPermission).where(or_(MintPermission.status.in_(['prepared','submitted']),and_(MintPermission.status=='armed',MintPermission.execute_after<=now))).order_by(MintPermission.created_at).limit(1).with_for_update(skip_locked=True))).scalar_one_or_none()
    if p is None: return
    plan=await db.get(MintPlan,p.plan_id)
    user=await db.get(User,p.user_id)
    wallet=await db.get(Wallet,plan.wallet_id) if plan else None
    if not plan or not wallet or wallet.user_id!=p.user_id or not user or not user.is_active or user.deleted_at:
        if p.status=='armed':
            p.status='cancelled'; p.note='Account or linked plan unavailable.'; await db.commit()
        return
    chain=next(k for k,v in CHAINS.items() if v[0]==plan.chain_id)
    web3=None
    try:
        if 'direct_gas' in p.execution:
            from app.services.direct_wallet_worker import process_direct_permission
            await process_direct_permission(db,p,plan,wallet,chain)
            return
        account=relayer_account()
        web3=await checked_provider(chain,wallet.address)
        if p.status=='armed':
            if aware(p.expires_at)<=now:
                p.status='expired'; p.note='Permission expired before submission.'; await db.commit(); return
            typed=p.typed_data
            msg=typed['message']
            if msg['delegate'].lower()!=account.address.lower() or msg['delegator'].lower()!=wallet.address.lower() or typed['domain']['chainId']!=plan.chain_id or typed['domain']['verifyingContract'].lower()!=REGISTRY[str(plan.chain_id)]['manager'].lower():
                raise ValueError('Permission account mismatch')
            validate_signature(typed,p.signature,wallet.address)
            await verify_presale(web3,decode_mint({'to':p.execution['target'],'data':p.execution['data'],'value':p.execution['value']},plan.contract_address,wallet.address,plan.quantity))
            fee_payment=p.execution.get('gas_reimbursement')
            if not fee_payment: raise ValueError('A user-paid gas permission is required')
            if fee_payment and (fee_payment['target'].lower()!=account.address.lower() or not 0<int(fee_payment['value'])<=settings.MINT_RELAYER_MAX_FEE_WEI):
                raise ValueError('Fee reimbursement mismatch')
            calldata=redeem_calldata(typed,p.signature,p.execution)
            gas_price=await web3.eth.gas_price
            tx={'from':account.address,'to':to_checksum_address(typed['domain']['verifyingContract']),
                'data':calldata,'value':0,'chainId':plan.chain_id,
                'nonce':await web3.eth.get_transaction_count(account.address,'pending'),'gasPrice':gas_price}
            # This simulation checks revocation, expiry, single-use and exact call on-chain.
            gas=(await web3.eth.estimate_gas(tx))*120//100
            fee=gas*gas_price
            if fee_payment and fee>int(fee_payment['value']):
                raise ValueError('Gas exceeds the signed reimbursement; a fresh quote is required')
            if fee>settings.MINT_RELAYER_MAX_FEE_WEI or await web3.eth.get_balance(account.address)<fee:
                raise ValueError('Relayer fee cap or balance unavailable')
            tx['gas']=gas
            signed=account.sign_transaction(tx)
            p.raw_transaction='0x'+bytes(signed.raw_transaction).hex()
            p.tx_hash='0x'+bytes(signed.hash).hex()
            p.status='prepared'; p.note='Exact mint signed by operator relayer; awaiting submission.'
            await db.commit()
            # Reacquire lock after committing signed bytes, before external mutation.
            if db.bind.dialect.name == 'postgresql':
                await db.execute(text('SELECT pg_advisory_xact_lock(731654202)'))
            p=(await db.execute(select(MintPermission).where(MintPermission.id==p.id).with_for_update())).scalar_one()
        try:
            receipt=await web3.eth.get_transaction_receipt(p.tx_hash)
        except TransactionNotFound:
            receipt=None
        if receipt is not None:
            p.status='minted' if receipt.status==1 else 'reverted'
            p.note='Mint transaction confirmed.' if receipt.status==1 else 'Mint reverted. No automatic second mint will be attempted.'
            p.raw_transaction=None
        elif p.status=='prepared':
            if aware(p.expires_at)<=now:
                p.status='submitted'; p.note='Expiry passed; no resend. Tracking the signed hash because submission outcome is uncertain.'
            else:
                await web3.eth.send_raw_transaction(bytes.fromhex(p.raw_transaction[2:]))
                p.status='submitted'; p.submitted_at=now; p.note='Mint submitted; waiting for chain receipt.'
        await db.commit()
    except Exception:
        # Never expose raw signatures, keys or upstream RPC exception contents.
        if p.status=='armed':
            p.status='failed'; p.note='Permission simulation or relayer checks failed. No mint was sent. Review the plan and create a fresh permission.'
            await db.commit()
        # Prepared/sent transactions retain the durable hash for reconciliation.
    finally:
        if web3: await web3.provider.disconnect()
