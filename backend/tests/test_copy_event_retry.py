"""Each copy event retains its own outcome; transient failures cannot undo peers."""
from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select
from app.models import CopyEvent,MintTask
from app.services import copy_mints as copying
from app.services.opensea import OpenSeaUnavailable
from test_copy_presales import presale
from test_copy_mints import copying
from test_automatic_evm import lab


async def prepared_events(presale):
    c,state,_,mint_source=presale
    await c['approve']();await mint_source()
    lab=c['lab']
    original=copying.arm_event
    # Observe the real source while temporarily holding preparation.
    async def wait(*args):raise OpenSeaUnavailable('temporary fixture hold',retry_after_seconds=1)
    from unittest.mock import patch
    with patch.object(copying,'arm_event',wait):await c['scan']()
    async with lab.factory() as db:
        event=await db.scalar(select(CopyEvent).where(CopyEvent.watch_id==c['watch_id']))
        event.next_attempt_at=None;event.note=None;event.last_error_category=None
        observation=dict(event.observation);eid=event.id
        await db.commit()
    return c,state,original,eid,observation


async def test_deferral_does_not_rollback_previous_event_or_block_later_event(presale,monkeypatch):
    c,_,original,eid,observation=await prepared_events(presale);lab=c['lab']
    now=datetime.now(timezone.utc)
    async with lab.factory() as db:
        first=await db.get(CopyEvent,eid);first.created_at=now-timedelta(seconds=3)
        for i in (1,2):db.add(CopyEvent(id=str(i)*64,watch_id=c['watch_id'],user_id=lab.user.id,observation=observation,status='detected',created_at=now-timedelta(seconds=3-i)))
        await db.commit()
    async def process(db,event,rule,web3):
        if event.id=='1'*64:raise OpenSeaUnavailable('provider cooldown',retry_after_seconds=600)
        event.status='skipped';event.note='Persisted independently.'
    monkeypatch.setattr(copying,'arm_event',process)
    async with lab.factory() as db:await copying.process_copy_events(db,c['watch_id'],31337)
    async with lab.factory() as db:
        rows=(await db.scalars(select(CopyEvent).where(CopyEvent.watch_id==c['watch_id']).order_by(CopyEvent.created_at))).all()
        assert [e.status for e in rows]==['skipped','detected','skipped']
        assert rows[1].next_attempt_at is not None and 'Waiting for wallet-specific' in rows[1].note
        assert rows[0].note==rows[2].note=='Persisted independently.'
        assert not (await db.scalars(select(MintTask).where(MintTask.copy_rule_id.is_not(None)))).all()


async def test_expired_phase_skips_without_upstream_call(presale,monkeypatch):
    c,_,_,eid,o=await prepared_events(presale);lab=c['lab']
    async with lab.factory() as db:
        e=await db.get(CopyEvent,eid);e.observation={**o,'end':int(datetime.now(timezone.utc).timestamp())-1};await db.commit()
    async def unexpected(*args):raise AssertionError('Expired phase must not be prepared')
    monkeypatch.setattr(copying,'arm_event',unexpected)
    async with lab.factory() as db:await copying.process_copy_events(db,c['watch_id'],31337)
    async with lab.factory() as db:
        e=await db.get(CopyEvent,eid);assert e.status=='skipped' and e.last_error_category=='phase_ended'
        assert e.next_attempt_at is None and e.task_id is None


async def test_temporary_422_retries_and_never_claims_ineligible(presale,monkeypatch):
    c,state,original,eid,o=await prepared_events(presale);lab=c['lab']
    from app.services.opensea import OpenSeaClient
    async def unavailable(*args,**kwargs):return 422,None
    monkeypatch.setattr(OpenSeaClient,'build_mint',unavailable)
    async with lab.factory() as db:await copying.process_copy_events(db,c['watch_id'],31337)
    async with lab.factory() as db:
        e=await db.get(CopyEvent,eid)
        assert e.status=='detected' and e.task_id is None and e.next_attempt_at is not None
        assert 'cannot mint' not in e.note and 'Waiting' in e.note


@pytest.mark.parametrize('kind',['allowlist','signed'])
async def test_max_quantity_reuses_one_receiving_wallet_proof(presale,kind):
    c,state,configure,mint_source=presale;lab=c['lab']
    state.kind=kind;state.own_price=0;configure()
    c['request'].update(free_only=True,quantity=100,quantity_mode='max_free',price_cap_eth='0',fee_cap_eth='0.001')
    await c['approve']();await mint_source();await c['scan']()
    activity=(await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    assert activity['task_id'],activity['note']
    assert len(state.calls)==1 and state.calls[0][0]==lab.owner.address.lower()
    async with lab.factory() as db:
        from app.models import MintAuthorization
        t=await db.get(MintTask,activity['task_id']);a=await db.get(MintAuthorization,t.authorization_id)
        assert a.quantity==7 and a.max_fee_wei==10**15
