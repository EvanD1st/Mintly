"""Owner-scoped unlinking preserves history and permanently stops old actions."""
from datetime import datetime, timezone
from sqlalchemy import select
from app.models import Wallet, AutomaticGrant, CopyRule, MintTask, MintPlan, MintPermission, ActivityEvent
from app.services import automatic
from app.services.copy_mints import pause_rule


async def unlink(db, wallet):
    # Caller holds the same execution lock as the signer and copy scheduler.
    if wallet.archived_at:
        return
    now = datetime.now(timezone.utc)
    grants = (await db.scalars(select(AutomaticGrant).where(AutomaticGrant.wallet_id == wallet.id))).all()
    for grant in grants:
        grant.status = 'disabled'
    rules = (await db.scalars(select(CopyRule).join(AutomaticGrant, AutomaticGrant.id == CopyRule.grant_id)
        .where(AutomaticGrant.wallet_id == wallet.id, CopyRule.user_id == wallet.user_id))).all()
    for rule in rules:
        await pause_rule(db, rule)
        rule.status = 'revoked'
    await db.flush()  # Do not release the same unsigned copy reservation twice.
    tasks = (await db.scalars(select(MintTask).where(MintTask.wallet_id == wallet.id))).all()
    for task in tasks:
        if task.status in ('armed', 'preparing') and not task.signed_tx_raw:
            task.status = 'disarmed'
            if task.execution_mode == automatic.MODE:
                await automatic.release_reservation(db, task)
        if task.signed_tx_raw and task.status not in automatic.TERMINAL:
            task.broadcast_disabled_at = now
        task.archived_at = task.archived_at or now
    plans = (await db.scalars(select(MintPlan).where(MintPlan.wallet_id == wallet.id))).all()
    from app.api.mint_plans import record_plan
    for plan in plans:
        if not plan.archived_at:
            plan.archived_at, plan.next_check_at = now, None
            record_plan(db, plan, wallet, 'wallet_unlinked')
        permissions = (await db.scalars(select(MintPermission).where(MintPermission.plan_id == plan.id))).all()
        for permission in permissions:
            if permission.status in ('awaiting_signature', 'armed') and not permission.raw_transaction:
                permission.status, permission.note = 'cancelled', 'Wallet unlinked; future execution disabled.'
    wallet.archived_at, wallet.is_default = now, False
    other = await db.scalar(select(Wallet).where(Wallet.user_id == wallet.user_id, Wallet.id != wallet.id,
        Wallet.archived_at.is_(None)).order_by(Wallet.is_default.desc(), Wallet.created_at).limit(1))
    if other:
        other.is_default = True
    db.add(ActivityEvent(user_id=wallet.user_id, event_type='wallet_unlinked', label='Wallet unlinked',
        detail=f'{wallet.label}: {wallet.address}. Copying and automatic minting disabled; history retained.',
        icon_name='wallet', is_demo=False))
