"""Account-scoped, bounded public RPC reads. No vault or signing access."""
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from eth_utils import to_checksum_address
from app.models import Wallet, AutomaticGrant, MintTask, MintAuthorization
from app.services import automatic
from app.services.mint_plans import aware

NETWORKS = {1:'Ethereum', 4663:'Robinhood', 8453:'Base'}


async def readiness(db, user):
    wallets = (await db.scalars(select(Wallet).where(Wallet.user_id == user.id,
        Wallet.archived_at.is_(None)).order_by(Wallet.created_at))).all()
    grants = (await db.scalars(select(AutomaticGrant).where(AutomaticGrant.user_id == user.id))).all()
    tasks = (await db.execute(select(MintTask, MintAuthorization).join(MintAuthorization,
        MintAuthorization.id == MintTask.authorization_id).join(Wallet, Wallet.id == MintTask.wallet_id)
        .where(Wallet.user_id == user.id, MintTask.execution_mode == automatic.MODE,
            MintTask.status.not_in(automatic.TERMINAL)))).all()
    now = datetime.now(timezone.utc)
    result = []
    checks = []
    for wallet in wallets:
        networks = []
        for chain, name in NETWORKS.items():
            own = [g for g in grants if g.wallet_id == wallet.id and g.chain_id == chain]
            active = [g for g in own if g.status == 'enabled' and aware(g.expires_at) > now]
            required = sum(auth.total_spend_cap_wei for task, auth in tasks
                if task.wallet_id == wallet.id and auth.snapshot['chain_id'] == chain)
            upcoming = [task for task, auth in tasks if task.wallet_id == wallet.id and auth.snapshot['chain_id'] == chain]
            next_task = min(upcoming, key=lambda task: aware(task.scheduled_for_utc)) if upcoming else None
            card = {'chain_id':chain, 'network':name, 'balance_wei':None,
                'balance_status':'unavailable', 'approval_status':'active' if active else ('expired' if own else 'needed'),
                'approved_remaining_wei':str(sum(max(0,g.budget_wei-g.spent_wei-g.reserved_wei) for g in active)),
                'approval_expires_at':min((aware(g.expires_at) for g in active), default=None),
                'pending_maximum_wei':str(required), 'gas_status':'Network check unavailable',
                'advance_check':next_task.preflight_note if next_task else None,
                'advance_checked_at':next_task.preflight_checked_at if next_task else None}
            networks.append(card)
            checks.append((wallet.address, card, required))
        result.append({'wallet_id':wallet.id, 'networks':networks})
    slots = asyncio.Semaphore(6)
    async def balance(address, card, required):
        web3 = None
        try:
            async with slots:
                web3 = await asyncio.wait_for(automatic.provider_for(card['chain_id']), 3)
                amount = await asyncio.wait_for(web3.eth.get_balance(to_checksum_address(address), 'pending'), 3)
            card.update(balance_wei=str(amount), balance_status='available')
            card['gas_status'] = ('Add ETH for gas' if amount == 0 else
                ('Below pending mint maximum' if amount < required else 'Within pending mint maximum') if required else
                'Gas checked when a mint is prepared')
        except Exception:
            pass  # An outage is never reported as a zero balance.
        finally:
            if web3 is not None:
                await web3.provider.disconnect()
    pending = [asyncio.create_task(balance(*check)) for check in checks]
    if pending:
        _, remaining = await asyncio.wait(pending, timeout=10)
        for job in remaining:
            job.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    return {'automation_paused':user.automation_paused, 'checked_at':now, 'wallets':result}
