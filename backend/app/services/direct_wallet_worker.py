"""Submit only the immutable operation approved when arming."""
from datetime import datetime, timezone
from sqlalchemy import select, text

from app.services.seadrop_mint import decode_mint, verify_presale
from app.config import settings
from app.models import MintPermission
from app.services.direct_wallet_gas import Bundler, ENTRY_POINT, validate_operation, operation_hash, verify_account
from app.services.mint_permission import checked_provider
from app.services.mint_plans import aware


async def process_direct_permission(db,p,plan,wallet,chain):
    if settings.APP_ENV == 'production' or not settings.ENABLE_DIRECT_WALLET_GAS:
        return
    now=datetime.now(timezone.utc)
    web3=None
    try:
        bundler=Bundler(plan.chain_id)
        if p.status in ['prepared','submitted']:
            result=await bundler.call('eth_getUserOperationReceipt',[p.tx_hash])
            if result:
                p.status='minted' if result.get('success') is True else 'reverted'
                p.note='Mint confirmed. Main wallet paid network gas.' if p.status=='minted' else 'Mint reverted. Network gas may have been charged; no automatic second mint.'
                await db.commit();return
            if p.status=='submitted':return
            if aware(p.expires_at)<=now:
                p.status='submitted';p.note='Expired; no resend. Tracking operation because submission outcome is uncertain.'
                await db.commit();return
        web3=await checked_provider(chain,wallet.address)
        await verify_account(web3,wallet.address)
        op=validate_operation(p,plan.chain_id,wallet.address)
        await verify_presale(web3,decode_mint({'to':p.execution['target'],'data':p.execution['data'],'value':p.execution['value']},plan.contract_address,wallet.address,plan.quantity))
        if p.status=='armed':
            if aware(p.expires_at)<=now:
                p.status='expired';p.note='Operation expired before submission.';await db.commit();return
            if now<aware(p.execute_after): return
            await bundler.verify()
            estimate=await bundler.call('eth_estimateUserOperationGas',[op,ENTRY_POINT])
            for key in ['callGasLimit','verificationGasLimit','preVerificationGas']:
                if int(estimate[key],16)>int(op[key],16):
                    raise ValueError('Signed gas limit insufficient')
            if int(await web3.eth.gas_price)>int(op['maxFeePerGas'],16):
                raise ValueError('Signed fee ceiling insufficient')
            if not settings.ENABLE_DIRECT_WALLET_BROADCAST:
                p.note='Bundler simulation passed. Live submission is disabled pending verification; no operation sent.'
                await db.commit();return
            p.tx_hash=operation_hash(op,plan.chain_id)
            p.raw_transaction=None
            p.status='prepared';p.note='Approved operation stored; awaiting bundler submission.'
            await db.commit()
            if db.bind.dialect.name=='postgresql':
                await db.execute(text('SELECT pg_advisory_xact_lock(731654202)'))
            p=(await db.execute(select(MintPermission).where(MintPermission.id==p.id).with_for_update())).scalar_one()
        result=await bundler.call('eth_getUserOperationReceipt',[p.tx_hash])
        if result:
            # This is a UserOperation hash; receipt includes its enclosing tx hash.
            p.status='minted' if result.get('success') is True else 'reverted'
            p.note='Mint confirmed. Main wallet paid network gas.' if p.status=='minted' else 'Mint reverted. Network gas may have been charged; no automatic second mint.'
        elif p.status=='prepared':
            if aware(p.expires_at)<=now:
                p.status='submitted';p.note='Expired; no resend. Tracking operation because submission outcome is uncertain.'
            else:
                if not settings.ENABLE_DIRECT_WALLET_BROADCAST:return
                returned=await bundler.call('eth_sendUserOperation',[op,ENTRY_POINT])
                if not isinstance(returned,str) or returned.lower()!=p.tx_hash.lower():
                    raise ValueError('Unexpected operation hash')
                p.status='submitted';p.submitted_at=now;p.note='Submitted to bundler; main wallet pays gas.'
        await db.commit()
    except Exception:
        if p.status=='armed':
            p.status='failed';p.note='Direct wallet gas checks failed. No operation sent. Refresh and approve a new quote.'
            await db.commit()
        # A prepared operation retains its hash after an ambiguous upstream error.
        # Never create a fresh nonce, alter fees, or resubmit after expiry.
    finally:
        if web3: await web3.provider.disconnect()
