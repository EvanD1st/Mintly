import uuid,json
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from sqlalchemy import select,func,text
import pytest
from app.models import MintOpportunity,MintTask,MintAuthorization,MintAttemptDiagnostic,FeedWalletCheck,AutomaticGrant,User
from app.services import reliability
from app.services.mint_lifecycle import read_model,preparation_disposition
from test_feed_automation_evm import free_feed,arm_free
from test_automatic_evm import lab
from test_copy_mints import copying


def test_lifecycle_does_not_expose_execution_secrets_or_guess_unknown_failures():
    task=SimpleNamespace(id='task',status='failed',failure_reason='Unknown legacy failure.',signed_tx_raw='private-bytes')
    result=read_model(task)
    assert result['source']=='execution_record' and result['terminal'] and result['reason_code'] is None
    assert 'private-bytes' not in json.dumps(result)
    task.failure_reason='This collection is sold out. No transaction sent.'
    assert read_model(task)['label']=='Sold out'


@pytest.mark.parametrize('status,reason,attempt,copy,expected',[
    (409,'supply_exhausted',1,False,(True,False)),
    (409,'wallet_limit',1,False,(False,False)),
    (503,None,40,False,(False,True)),
    (429,None,40,True,(False,False)),
    (409,'wallet_limit',6,True,(False,True)),
])
def test_retry_decisions_preserve_permanent_vs_reconcilable_failures(status,reason,attempt,copy,expected):
    assert preparation_disposition(status,reason,attempt,40,copy=copy)==expected


async def test_observation_deduplicates_and_never_creates_authority(free_feed):
    lab=free_feed['lab'];approval=free_feed['approval']['id']
    async with lab.factory() as db:
        grant=await db.get(AutomaticGrant,lab.grant.id);before=(grant.reserved_wei,grant.spent_wei,grant.context_hash,grant.scope)
    for _ in range(3):await reliability.observe(lab.factory,approval,lab.drop.id)
    async with lab.factory() as db:
        rows=(await db.scalars(select(MintOpportunity))).all()
        assert len(rows)==1 and rows[0].contract==lab.nft.address.lower()
        assert not await db.scalar(select(func.count()).select_from(MintTask))
        grant=await db.get(AutomaticGrant,lab.grant.id)
        assert (grant.reserved_wei,grant.spent_wei,grant.context_hash,grant.scope)==before


@pytest.mark.parametrize('condition',['expired','incomplete','wrong_contract','not_eligible'])
async def test_unverified_or_stale_checks_never_inflate_eligible_opportunities(free_feed,condition):
    lab=free_feed['lab']
    async with lab.factory() as db:
        check=await db.get(FeedWalletCheck,(lab.user.id,lab.wallet.id,lab.drop.id))
        if condition=='expired':check.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        elif condition=='incomplete':check.result={}
        elif condition=='wrong_contract':check.result={**check.result,'contract_address':'0x'+'0'*40}
        else:check.result={**check.result,'stages':[{**check.result['stages'][0],'eligibility':'not_eligible'}]}
        await db.commit()
    await reliability.observe(lab.factory,free_feed['approval']['id'],lab.drop.id)
    async with lab.factory() as db:assert not await db.scalar(select(func.count()).select_from(MintOpportunity))


async def test_telemetry_failure_does_not_block_real_auto_arming(free_feed):
    from app.services import feed_automation
    lab=free_feed['lab']
    async with lab.factory() as db:
        await db.execute(text('DROP TABLE mint_opportunities'));await db.commit()
    assert await feed_automation.step(lab.factory)
    async with lab.factory() as db:assert await db.scalar(select(func.count()).select_from(MintTask))==1


async def test_report_separates_market_failures_and_counts_distinct_incident_tasks(free_feed):
    lab=free_feed['lab'];task_id,_=await arm_free(free_feed)
    now=datetime.now(timezone.utc)
    async with lab.factory() as db:
        original=await db.get(MintTask,task_id)
        original.scheduled_for_utc=now-timedelta(minutes=10);original.status='confirmed'
        original.submitted_at=now-timedelta(minutes=9);original.confirmed_at=now-timedelta(minutes=8)
        for index in range(4):
            task=MintTask(id=str(uuid.uuid4()),authorization_id=original.authorization_id,wallet_id=original.wallet_id,
                drop_id=original.drop_id,stage_id=original.stage_id,status='failed',is_demo=False,
                idempotency_key=str(uuid.uuid4()),scheduled_for_utc=now-timedelta(minutes=10),expires_at_utc=now+timedelta(minutes=10))
            db.add(task);await db.flush()
            for n in range(3):db.add(MintAttemptDiagnostic(task_id=task.id,phase='preparation',attempt_number=n+1,
                started_at=now-timedelta(seconds=10-n),finished_at=now-timedelta(seconds=9-n),outcome='failed',
                signer_http_status=503,error_category='supply_exhausted' if index==3 else 'upstream_rate_limited',upstream_events=[]))
        await db.commit()
        result=await reliability.report(db,now=now)
        assert result['outcomes']=={'confirmed':1,'service_failure_needs_review':3,'sold_out':1}
        assert result['incidents'][0]['affected_tasks']==3
        assert result['modes']['auto_arm']['opening_to_submission']['p95_seconds']==60
        assert result['modes']['auto_arm']['opening_to_submission']['samples']==1
        assert 'signed_tx_raw' not in json.dumps(result,default=str)


async def test_admin_report_is_owner_protected_and_read_only(free_feed):
    lab=free_feed['lab']
    assert (await lab.client.get('/api/admin/reliability')).status_code==403
    async with lab.factory() as db:
        user=await db.get(User,lab.user.id);user.role='admin';await db.commit()
    result=await lab.client.get('/api/admin/reliability')
    assert result.status_code==200,result.text
    assert result.json()['observation_started_at'] is None
    assert (await lab.client.get('/api/admin/reliability?hours=999')).status_code==422


async def test_today_queue_and_history_share_terminal_lifecycle_without_breaking_old_clients(free_feed):
    lab=free_feed['lab'];task_id,_=await arm_free(free_feed)
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);task.status='failed'
        task.failure_reason='This collection is sold out. No transaction sent.'
        await db.commit()
        grant=await db.get(AutomaticGrant,lab.grant.id);reserved=grant.reserved_wei
    queue=(await lab.client.get('/api/tasks/queue')).json()['tasks'][0]
    history=(await lab.client.get('/api/history?section=mints')).json()['records'][0]
    response=await lab.client.get('/api/drops',params={'daily_only':'true','execution_states':'true','wallet_id':lab.wallet.id})
    assert response.status_code==200,response.text
    today=response.json()['drops'][0]['automatic_mint']
    assert queue['lifecycle']==history['lifecycle']==today['lifecycle']
    assert today['lifecycle']['label']=='Sold out'
    assert not response.json()['drops'][0]['wallet_check']['setup_enabled']
    legacy=(await lab.client.get('/api/drops?daily_only=true')).json()['drops'][0]
    assert legacy['automatic_mint'] is None
    async with lab.factory() as db:assert (await db.get(AutomaticGrant,lab.grant.id)).reserved_wei==reserved


async def test_tracked_opening_moves_opportunity_out_of_old_reporting_window(free_feed):
    lab=free_feed['lab'];now=datetime.now(timezone.utc)
    await reliability.observe(lab.factory,free_feed['approval']['id'],lab.drop.id)
    task_id,_=await arm_free(free_feed)
    async with lab.factory() as db:
        opportunity=await db.scalar(select(MintOpportunity));opportunity.opens_at=now-timedelta(hours=1)
        task=await db.get(MintTask,task_id);task.scheduled_for_utc=now+timedelta(days=2)
        await db.commit()
        result=await reliability.report(db,now=now)
        assert result['eligible_auto_arm_collections']==0


async def test_future_unarmed_signer_rejection_is_visible_without_inflating_due_opportunities(free_feed):
    from fastapi import HTTPException
    lab=free_feed['lab'];approval=free_feed['approval']['id']
    await reliability.observe(lab.factory,approval,lab.drop.id)
    await reliability.arm_result(lab.factory,approval,lab.drop.id,HTTPException(409,
        'The isolated signer has not confirmed this policy and keystore are ready. No task was armed.'))
    async with lab.factory() as db:
        result=await reliability.report(db)
        assert result['eligible_auto_arm_collections']==0
        assert result['incidents'][0]['affected_opportunities']==1
        assert result['incidents'][0]['reason_code']=='wallet_approval_changed'
    await reliability.arm_result(lab.factory,approval,lab.drop.id)
    async with lab.factory() as db:assert not (await reliability.report(db))['incidents']


async def test_future_preflight_warning_resolves_on_success_or_cancellation(free_feed):
    lab=free_feed['lab'];task_id,_=await arm_free(free_feed);now=datetime.now(timezone.utc)
    async with lab.factory() as db:
        db.add(MintAttemptDiagnostic(task_id=task_id,phase='preflight',started_at=now-timedelta(seconds=2),
            finished_at=now-timedelta(seconds=1),outcome='check_completed',signer_http_status=200,
            error_category='api_access_denied',upstream_events=[]))
        await db.commit()
        result=await reliability.report(db,now=now)
        assert not result['outcomes'] and result['incidents'][0]['affected_tasks']==1
        task=await db.get(MintTask,task_id);task.status='disarmed';await db.commit()
        assert not (await reliability.report(db,now=now))['incidents']


def test_arming_categories_never_retain_provider_or_exception_bodies():
    from fastapi import HTTPException
    assert reliability.arming_reason(HTTPException(503,{'private_key':'never-retain'}))=='arming_unavailable'
    assert reliability.arming_reason(RuntimeError('secret'))=='arming_error'


async def test_copy_activity_uses_task_lifecycle_and_detection_time_for_latency(copying):
    from app.services import copy_mints
    from app.models import CopyEvent
    c=copying;lab=c['lab']
    await c['approve']();await c['mint']();await c['scan']()
    assert await copy_mints.step(lab.factory)
    async with lab.factory() as db:
        event=await db.scalar(select(CopyEvent));task=await db.get(MintTask,event.task_id)
        task.status='failed';task.failure_reason='This collection is sold out. No transaction sent.'
        await db.commit()
        observed=event.created_at.replace(tzinfo=timezone.utc) if event.created_at.tzinfo is None else event.created_at
        task_id=task.id
    activity=(await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    queue=(await lab.client.get('/api/tasks/queue')).json()['tasks'][0]
    assert activity['lifecycle']==queue['lifecycle'] and activity['lifecycle']['label']=='Sold out'
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);task.status='confirmed'
        task.scheduled_for_utc=observed-timedelta(days=2);task.submitted_at=observed+timedelta(seconds=3)
        await db.commit()
        result=await reliability.report(db,now=observed+timedelta(seconds=10))
        assert result['modes']['copy']['activity_to_submission']['p95_seconds']==3
