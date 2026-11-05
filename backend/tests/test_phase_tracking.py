import copy
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock
import pytest
from app.services import phase_tracking
from app.services.mint_stage_choice import pinned
from app.services.opensea import stage_schedule,OpenSeaUnavailable


def metadata(start,end,**changes):
    raw={'uuid':'gtd','stage_type':'signed_presale','label':'GTD','start_time':start.isoformat(),
        'end_time':end.isoformat(),'price':'0','max_per_wallet':'2','price_currency_address':'0x'+'0'*40}
    raw.update(changes)
    return {'chain':'base','contract_address':'0x'+'1'*40,'stages':[raw]}


@pytest.fixture
def phase():
    now=datetime.now(timezone.utc).replace(microsecond=0)
    start=now+timedelta(hours=1);end=now+timedelta(hours=3)
    detail=metadata(start,end)
    identity=pinned(stage_schedule(detail)[0])
    snapshot={'schedule_mode':'phase_open','phase_identity':identity,'chain_id':8453,'contract':detail['contract_address'],
        'mint_page_url':'https://opensea.io/collection/test','mint_kind':'signed','price_wei':0,'price_cap_wei':0,
        'start':int(start.timestamp()),'end':int(end.timestamp()),'expiry':int(end.timestamp()),'execute_at':int(start.timestamp()),
        'fee_cap_wei':100,'total_cap_wei':100,'selected_phase':copy.deepcopy(identity),'execution':{'data':'original'}}
    return now,start,end,detail,snapshot


@pytest.mark.parametrize('minutes',[-30,30])
async def test_follow_opening_moves_both_ways_without_rewriting_approval(phase,monkeypatch,minutes):
    now,start,end,detail,snapshot=phase;original=copy.deepcopy(snapshot)
    new=start+timedelta(minutes=minutes)
    monkeypatch.setattr('app.services.phase_tracking.OpenSeaClient.get_drop',AsyncMock(return_value=metadata(new,end)))
    result=await phase_tracking.resolve(snapshot,now=now)
    assert result['start']==result['execute_at']==int(new.timestamp())
    assert result['selected_phase']['starts_at']==result['start']
    assert 'execution' not in result
    assert snapshot==original
    assert all(result[k]==original[k] for k in ('expiry','fee_cap_wei','total_cap_wei','price_cap_wei','phase_identity'))


@pytest.mark.parametrize('change',[{'uuid':'different'},{'price':'1'},{'max_per_wallet':'3'}, {'stage_type':'public_sale'}])
async def test_changed_identity_or_terms_requires_review(phase,monkeypatch,change):
    now,start,end,detail,snapshot=phase
    monkeypatch.setattr('app.services.phase_tracking.OpenSeaClient.get_drop',AsyncMock(return_value=metadata(start,end,**change)))
    with pytest.raises(phase_tracking.PhaseChanged):await phase_tracking.resolve(snapshot,now=now)


async def test_opening_beyond_deadline_requires_review_and_never_extends_expiry(phase,monkeypatch):
    now,start,end,detail,snapshot=phase
    monkeypatch.setattr('app.services.phase_tracking.OpenSeaClient.get_drop',AsyncMock(return_value=metadata(end+timedelta(hours=1),end+timedelta(hours=2))))
    with pytest.raises(phase_tracking.PhaseChanged,match='approved deadline'):await phase_tracking.resolve(snapshot,now=now)
    assert snapshot['expiry']==int(end.timestamp())


async def test_fixed_approval_never_fetches_or_follows_changed_schedule(phase,monkeypatch):
    snapshot=phase[-1];snapshot['schedule_mode']='fixed'
    request=AsyncMock();monkeypatch.setattr('app.services.phase_tracking.OpenSeaClient.get_drop',request)
    assert await phase_tracking.resolve(snapshot)==snapshot
    request.assert_not_called()


async def test_unavailable_provider_leaves_approval_untouched(phase,monkeypatch):
    snapshot=phase[-1];original=copy.deepcopy(snapshot)
    monkeypatch.setattr('app.services.phase_tracking.OpenSeaClient.get_drop',AsyncMock(side_effect=OpenSeaUnavailable('Temporary',retry_after_seconds=30)))
    with pytest.raises(OpenSeaUnavailable):await phase_tracking.resolve(snapshot)
    assert snapshot==original
