"""Phase-stop explanations describe observed changes without changing consent."""
import copy
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from app.models import MintTask,MintAuthorization,MintAttemptDiagnostic,AutomaticGrant,DailyDebit,AutomaticNonce
from app.services import phase_explanations as messages,reliability
from app.services.mint_lifecycle import read_model,reason_from_note
from test_feed_automation_evm import free_feed,arm_free
from test_phase_tracking_evm import update
from test_automatic_evm import lab


def phase(**changes):
    return {'type':'public_sale','price_wei':0,'max_per_wallet':5,**changes}


@pytest.mark.parametrize('chain,currency',[(1,'ETH'),(4663,'ETH'),(33139,'APE'),(999,'HYPE')])
def test_free_to_paid_names_exact_price_and_preserves_native_units(chain,currency):
    original=phase();actual=phase(price_wei=2*10**15)
    before=copy.deepcopy((original,actual))
    note=messages.explain(original,actual,chain,free_only=True)
    assert note==f'Public mint price changed from free to 0.002 {currency} per NFT. Free-only mint stopped. Review the updated stage.'
    assert (original,actual)==before
    model=read_model(SimpleNamespace(id='task',status='failed',failure_reason=note))
    assert model['reason_code']=='terms_changed' and model['label']=='Mint terms changed'
    assert model['detail']==note


def test_paid_price_drop_still_requires_review_and_one_wei_stays_exact():
    assert messages.price(1,'ETH')=='0.000000000000000001 ETH'
    note=messages.explain(phase(price_wei=1),phase(),1)
    assert 'from 0.000000000000000001 ETH to free' in note and 'Review' in note
    assert 'Free-only' not in note
    assert messages.explain(phase(),phase(),1) is None


def test_unknown_price_is_not_presented_as_free_and_other_changes_are_specific():
    note=messages.explain(phase(),phase(price_wei=None),1,free_only=True)
    assert 'can no longer be verified' in note and 'Free-only' not in note
    note=messages.explain(phase(),phase(type='allowlist',max_per_wallet=2),1)
    assert 'method changed from public to whitelist' in note
    assert 'limit changed from 5 to 2 NFTs' in note
    assert reason_from_note(note)=='terms_changed'


def test_legacy_phase_stop_is_classified_without_inventing_old_prices():
    task=SimpleNamespace(id='old',status='failed',failure_reason='The approved phase price, method or allowance changed. Review this mint again.')
    result=read_model(task)
    assert result['reason_code']=='terms_changed' and result['label']=='Mint terms changed'
    assert 'after arming' in result['detail'] and '0.002' not in result['detail']
    assert reason_from_note('Unknown legacy failure.') is None


@pytest.mark.parametrize('diagnostic_fails',[False,True])
async def test_price_change_stays_stopped_releases_hold_and_explains_every_view(free_feed,monkeypatch,diagnostic_fails):
    f=free_feed;lab=f['lab'];task_id,_=await arm_free(f)
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);auth=await db.get(MintAuthorization,task.authorization_id)
        original=copy.deepcopy(auth.snapshot)
        grant=await db.get(AutomaticGrant,lab.grant.id)
        authority=copy.deepcopy((grant.scope,grant.context_hash,grant.budget_wei,grant.spent_wei))
    update(lab,lab.start,lab.end,price=2*10**15)
    f['metadata'].return_value['stages'][0]['price']=str(2*10**15)
    if diagnostic_fails:
        monkeypatch.setattr('app.services.mint_diagnostics.save',AsyncMock(side_effect=RuntimeError('diagnostics offline')))
    response=await lab.signer_client.post('/tasks/'+task_id+'/refresh-schedule')
    assert response.status_code==200 and response.json()['status']=='failed',response.text
    note='Public mint price changed from free to 0.002 ETH per NFT. Free-only mint stopped. Review the updated stage.'
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);auth=await db.get(MintAuthorization,task.authorization_id)
        assert task.failure_reason==task.schedule_note==note
        assert task.signed_tx_raw is None and task.transaction_hash is None
        assert task.preparation_attempts==task.broadcast_attempts==0
        assert await db.get(AutomaticNonce,task_id) is None
        assert auth.snapshot==original
        grant=await db.get(AutomaticGrant,lab.grant.id)
        assert (grant.scope,grant.context_hash,grant.budget_wei,grant.spent_wei)==authority
        assert grant.reserved_wei==0 and (await db.get(DailyDebit,task_id)).actual_wei==0
        ds=(await db.scalars(select(MintAttemptDiagnostic).where(MintAttemptDiagnostic.task_id==task_id))).all()
        assert len(ds)==(0 if diagnostic_fails else 1)
        if ds:assert ds[0].phase=='schedule' and ds[0].error_category=='terms_changed'
        result=await reliability.report(db,now=datetime.fromtimestamp(lab.start+1,timezone.utc))
        assert result['outcomes']=={'wallet_or_stage_constraint':1}
        assert result['failures_needing_review']==0
        assert result['recent_failures'][0]['reason_code']=='terms_changed'
    queue=(await lab.client.get('/api/tasks/queue')).json()['tasks'][0]
    history=(await lab.client.get('/api/history?section=mints')).json()['records'][0]
    for row in (queue,history):
        assert row['failure_reason']==note
        assert row['lifecycle']['reason_code']=='terms_changed'
        assert row['lifecycle']['detail']==note
