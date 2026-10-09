"""Selected WAT/UTC time is reviewed, persisted, held by the worker and enforced by the signer."""
from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select
from app.models import MintTask, MintAuthorization
from app.automatic_worker import step
from test_automatic_evm import lab


def iso(value):
    return datetime.fromtimestamp(value,timezone.utc).isoformat()


async def test_future_wat_time_pins_schedule_and_no_signature_or_worker_execution_before_it(lab,monkeypatch):
    selected = lab.start + 60
    # A WAT (+01:00) API request is equivalent to its UTC instant.
    wat = datetime.fromtimestamp(selected,timezone(timedelta(hours=1))).isoformat()
    request = {**lab.request,'scheduled_for_utc':wat,'quantity':1,'idempotency_key':'wat-time-1'}
    preview = await lab.client.post('/api/tasks/draft',json=request)
    assert preview.status_code == 200,preview.text
    assert preview.json()['snapshot']['execute_at'] == selected
    armed = await lab.client.post('/api/tasks/arm',json={**request,'review_hash':preview.json()['review_hash']})
    assert armed.status_code == 200,armed.text
    tid = armed.json()['id']
    assert datetime.fromisoformat(armed.json()['scheduled_for_utc']).timestamp() == selected
    async with lab.factory() as db:
        auth = await db.get(MintAuthorization,(await db.get(MintTask,tid)).authorization_id)
        assert auth.snapshot['execute_at'] == selected
    called=[]
    async def unexpected_sign(task_id):
        called.append(task_id)
    assert await step(lab.factory,unexpected_sign,now=datetime.fromtimestamp(selected-1,timezone.utc)) is False
    assert not called
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[selected])
    lab.w.provider.make_request('evm_mine',[])
    # Even a premature direct signer call cannot use the task's future nonce.
    early = await lab.signer_client.post(f'/tasks/{tid}/prepare')
    assert early.status_code == 200 and early.json()['status'] == 'armed'
    async with lab.factory() as db:
        assert (await db.get(MintTask,tid)).signed_tx_raw is None
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime.fromtimestamp(selected,tz)
    monkeypatch.setattr('app.services.automatic_signer.datetime',Clock)
    await lab.due()
    await lab.tick()
    await lab.due()
    await lab.tick()
    lab.w.provider.make_request('evm_mine',[])
    await lab.due()
    await lab.tick()
    async with lab.factory() as db:
        assert (await db.get(MintTask,tid)).status == 'confirmed'
    assert lab.nft.functions.totalSupply().call() == 1


@pytest.mark.parametrize('invalid',['before_stage','at_end','past','naive'])
async def test_invalid_mint_time_creates_no_task_or_spending_reservation(lab,invalid):
    values={'before_stage':iso(lab.start-1),'at_end':iso(lab.end),
        'past':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),
        'naive':datetime.fromtimestamp(lab.start).isoformat()}
    result = await lab.client.post('/api/tasks/arm',json={**lab.request,'scheduled_for_utc':values[invalid]})
    assert result.status_code in (409,422)
    async with lab.factory() as db:
        assert (await db.scalars(select(MintTask))).all() == []


async def test_task_schedule_database_change_is_rejected_by_independent_signer(lab,monkeypatch):
    selected=lab.start+60
    response=await lab.client.post('/api/tasks/arm',json={**lab.request,'scheduled_for_utc':iso(selected)})
    assert response.status_code==200,response.text
    tid=response.json()['id']
    async with lab.factory() as db:
        (await db.get(MintTask,tid)).scheduled_for_utc=datetime.fromtimestamp(lab.start,timezone.utc)
        await db.commit()
    result=await lab.signer_client.post(f'/tasks/{tid}/prepare')
    assert result.status_code==409
    async with lab.factory() as db:
        assert (await db.get(MintTask,tid)).signed_tx_raw is None


async def test_schedule_change_after_review_and_same_key_reuse_cannot_change_the_authorization(lab):
    request={**lab.request,'scheduled_for_utc':iso(lab.start+60)}
    preview=await lab.client.post('/api/tasks/draft',json=request)
    assert preview.status_code==200
    changed=await lab.client.post('/api/tasks/arm',json={**request,'scheduled_for_utc':iso(lab.start+120),
        'review_hash':preview.json()['review_hash']})
    assert changed.status_code==409
    original=await lab.client.post('/api/tasks/arm',json=request)
    assert original.status_code==200
    retry=await lab.client.post('/api/tasks/arm',json={**request,'scheduled_for_utc':iso(lab.start+120)})
    assert retry.status_code==409
