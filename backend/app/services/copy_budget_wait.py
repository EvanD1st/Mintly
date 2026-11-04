"""Wait for existing liabilities without spending the same allowance twice."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.models import CopyRule, AutomaticGrant, User
from app.services.networks import symbol


class ReservationWait(Exception):
    pass


async def wait_if_reserved(db, rule, required):
    """Called under the execution lock; every applicable cap must fit after settlement."""
    from app.services.copy_mints import budget_group, group_remaining
    from app.services.daily_budget import usage, limit_owner
    grant=await db.get(AutomaticGrant,rule.grant_id)
    user=await db.get(User,rule.user_id)
    if not grant or not user:
        return
    capacities=[(rule.budget_wei-rule.spent_wei-rule.reserved_wei,rule.budget_wei-rule.spent_wei),
        (grant.budget_wei-grant.spent_wei-grant.reserved_wei,grant.budget_wei-grant.spent_wei)]
    group=budget_group(rule.snapshot)
    if group:
        available=await group_remaining(db,rule)
        members=(await db.scalars(select(CopyRule).where(CopyRule.id.in_(group['members'])))).all()
        capacities.append((available,group['budget_wei']-sum(r.spent_wei for r in members)))
    owner=await limit_owner(db,user,symbol(rule.chain_id))
    if owner.daily_limit_wei is not None:
        daily=await usage(db,user.id,currency=symbol(rule.chain_id))
        capacities.append((owner.daily_limit_wei-sum(daily.values()),owner.daily_limit_wei-daily['spent_wei']))
    if all(unreserved>=required for _,unreserved in capacities) and any(available<required for available,_ in capacities):
        raise ReservationWait()


def defer(event, rule, deadline, now=None):
    now=now or datetime.now(timezone.utc)
    event.status='detected'
    event.note='Waiting for another pending mint’s reserved budget. Mintly will recheck before this phase ends.'
    event.next_attempt_at=min(deadline,now+timedelta(seconds=10))
    event.last_error_category='waiting_reserved_budget'
    # Retain a free-phase selection if present; the owner/approval marker also
    # ensures pause and expiry paths terminate this waiting signal normally.
    event.phase_plan={**(event.phase_plan or {}),'rule_id':rule.id}
