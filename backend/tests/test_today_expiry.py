from datetime import datetime,date,timezone,timedelta
from types import SimpleNamespace
import pytest
from app.services.feed_sources import carryover_visible

DAY=date(2026,11,6)
OPEN=datetime(2026,11,5,23,30,tzinfo=timezone.utc) # 00:30 WAT
def group(stages,day=date(2026,11,5)):
    return {'mentions':[(SimpleNamespace(list_date=day),{'stages':stages})]}
def stage(start):return {'starts_at':start.isoformat()}

def test_carryover_expires_exactly_one_hour_after_opening_across_midnight():
    g=group([stage(OPEN)])
    assert carryover_visible(g,DAY,OPEN+timedelta(minutes=59,seconds=59))
    assert not carryover_visible(g,DAY,OPEN+timedelta(hours=1))

def test_today_list_stays_and_last_phase_controls_collection_cutoff():
    assert carryover_visible(group([stage(OPEN)],DAY),DAY,OPEN+timedelta(hours=9))
    g=group([stage(OPEN),stage(OPEN+timedelta(hours=2))])
    assert carryover_visible(g,DAY,OPEN+timedelta(hours=2))
    assert not carryover_visible(g,DAY,OPEN+timedelta(hours=3))

@pytest.mark.parametrize('stages',[[],[{}],[{'starts_at':'bad'}],[{'starts_at':'2026-11-06T01:30:00'}]])
def test_unknown_schedule_is_retained(stages):
    assert carryover_visible(group(stages),DAY,OPEN+timedelta(hours=10))

def test_verified_postponement_overrides_old_source_opening():
    assert carryover_visible(group([stage(OPEN)]),DAY,OPEN+timedelta(hours=2),[stage(OPEN+timedelta(hours=3))])

def test_postponed_to_another_day_does_not_keep_yesterdays_card_on_today():
    assert not carryover_visible(group([stage(OPEN)]),DAY,OPEN+timedelta(hours=2),[stage(OPEN+timedelta(days=8))])
    assert not carryover_visible(group([stage(OPEN)]),DAY,OPEN+timedelta(hours=2),[stage(OPEN),stage(OPEN+timedelta(days=8))])
