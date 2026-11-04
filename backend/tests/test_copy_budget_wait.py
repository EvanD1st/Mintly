from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.models import AutomaticGrant,User
from app.services import copy_budget_wait,copy_mints,daily_budget


@pytest.mark.parametrize('reserved,spent,required,waiting',[
    (90,0,20,True),(0,0,20,False),(10,90,20,False),(90,0,101,False),
])
async def test_wait_only_when_settlement_can_restore_every_approved_cap(monkeypatch,reserved,spent,required,waiting):
    grant=SimpleNamespace(budget_wei=100,spent_wei=spent,reserved_wei=reserved)
    owner=SimpleNamespace(id='owner',daily_limit_wei=None)
    rule=SimpleNamespace(grant_id='grant',user_id='owner',chain_id=1,snapshot={},
        budget_wei=100,spent_wei=spent,reserved_wei=reserved)
    db=SimpleNamespace(get=AsyncMock(side_effect=lambda model,key:grant if model is AutomaticGrant else owner))
    monkeypatch.setattr(daily_budget,'limit_owner',AsyncMock(return_value=owner))
    if waiting:
        with pytest.raises(copy_budget_wait.ReservationWait):
            await copy_budget_wait.wait_if_reserved(db,rule,required)
    else:
        await copy_budget_wait.wait_if_reserved(db,rule,required)
    assert grant.reserved_wei==reserved and rule.reserved_wei==reserved


def test_wait_retains_phase_selection_and_never_outlives_approval():
    now=datetime.now(timezone.utc);deadline=now+timedelta(seconds=3)
    event=SimpleNamespace(phase_plan={'selected_phase':'fcfs'})
    copy_budget_wait.defer(event,SimpleNamespace(id='approval'),deadline,now)
    assert event.status=='detected' and event.next_attempt_at==deadline
    assert event.phase_plan=={'selected_phase':'fcfs','rule_id':'approval'}
    assert event.last_error_category=='waiting_reserved_budget'
