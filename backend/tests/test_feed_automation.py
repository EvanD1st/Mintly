import copy,json,uuid
from unittest.mock import AsyncMock
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.models import FeedMintApproval
from app.services import feed_automation,automatic
from test_permission_extension import extension


@pytest.fixture
async def approved(extension,monkeypatch):
    x=extension;monkeypatch.setattr(automatic,'enabled',lambda *args:None)
    key=str(uuid.uuid4())
    s={'id':key,'user_id':x.owner.id,'wallet_id':x.wallet.id,'grant_id':x.grant.id,'chain_id':1,
        'account':x.wallet.address,'quantity':1,'fee_cap_wei':100,'expiry':int(x.old.timestamp()),
        'sources':list(feed_automation.SOURCE_NAMES),'free_only':True}
    row=FeedMintApproval(id=key,user_id=x.owner.id,wallet_id=x.wallet.id,grant_id=x.grant.id,
        status='registering',snapshot=s,context_hash=automatic.digest(s),expires_at=x.old)
    x.db.add(row);await x.db.commit()
    await feed_automation.pin(x.db,x.journal,row.id,x.vault)
    row.status='active';await x.db.commit()
    x.approval=row;return x


async def test_standing_approval_is_independently_pinned_without_decrypting_a_key(approved):
    x=approved
    pin=x.journal.execute('SELECT * FROM feed_approvals WHERE id=?',(x.approval.id,)).fetchone()
    assert pin['intent']==automatic.digest(x.approval.snapshot) and pin['revoked']==0
    assert (x.grant.spent_wei,x.grant.reserved_wei)==(123,456)


@pytest.mark.parametrize('paused', [False, True])
async def test_status_reports_global_pause_without_changing_saved_approval(approved, paused):
    from app.api.feed_automation import status
    x = approved
    x.owner.automation_paused = paused
    await x.db.commit()
    original = copy.deepcopy(x.approval.snapshot)
    result = await status(user=x.owner, db=x.db)
    assert result['automation_paused'] is paused
    assert result['approvals'][0]['status'] == 'active'
    await x.db.refresh(x.approval)
    assert x.approval.status == 'active' and x.approval.snapshot == original


@pytest.mark.parametrize('change',[{'fee_cap_wei':200},{'quantity':2},{'free_only':False}])
async def test_existing_standing_approval_cannot_be_widened_or_replaced_in_place(approved,change):
    x=approved
    x.approval.snapshot={**x.approval.snapshot,**change};x.approval.context_hash=automatic.digest(x.approval.snapshot)
    await x.db.commit()
    with pytest.raises(ValueError):await feed_automation.pin(x.db,x.journal,x.approval.id,x.vault)


async def test_private_revocation_survives_database_reactivation(approved):
    x=approved
    await feed_automation.revoke(x.db,x.approval,x.vault);await x.db.commit()
    x.approval.status='active';await x.db.commit()
    with pytest.raises(ValueError,match='revived'):await feed_automation.pin(x.db,x.journal,x.approval.id,x.vault)
    with pytest.raises(ValueError,match='inactive'):await feed_automation.verify_task(x.db,x.journal,SimpleNamespace(),{'feed_approval_id':x.approval.id},x.grant)


async def test_expired_approval_is_displayed_as_expired_not_enabled(approved):
    x=approved;x.approval.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    assert feed_automation.public(x.approval)['status']=='expired'

async def test_due_wallets_are_drained_without_a_five_second_delay_each(monkeypatch):
    import asyncio
    factory=object();calls=[]
    monkeypatch.setattr(feed_automation,'step',AsyncMock(side_effect=[True,False]))
    async def sleep(delay):
        calls.append(delay)
        if len(calls)==2:raise asyncio.CancelledError()
    monkeypatch.setattr(feed_automation.asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError):await feed_automation.loop(factory)
    assert calls==[0.1,5]


async def test_enabled_once_is_account_scoped_and_survives_turning_off(approved):
    from app.models import User
    x=approved
    x.owner.feature_notices={'free_phase_copy_v1':True};await x.db.commit()
    assert await feed_automation.enabled_once(x.db,x.owner)
    await x.db.refresh(x.owner)
    assert x.owner.feature_notices=={'free_phase_copy_v1':True,feed_automation.ENABLED_ONCE:True}
    x.approval.status='revoked';await x.db.commit()
    assert await feed_automation.enabled_once(x.db,x.owner)
    admin=await x.db.scalar(select(User).where(User.username=='admin'))
    assert not await feed_automation.enabled_once(x.db,admin)


async def test_previously_enabled_then_disabled_user_is_not_prompted(approved):
    from app.models import ActivityEvent
    x=approved;x.approval.status='revoked'
    x.db.add(ActivityEvent(user_id=x.owner.id,event_type='free_list_approved',label='Enabled',detail='Confirmed approval',is_demo=False))
    await x.db.commit()
    assert await feed_automation.enabled_once(x.db,x.owner)
    events=(await x.db.scalars(select(ActivityEvent).where(ActivityEvent.user_id==x.owner.id))).all()
    for event in events:await x.db.delete(event)
    await x.db.delete(x.approval);await x.db.commit()
    assert await feed_automation.enabled_once(x.db,x.owner)


async def test_failed_confirmation_and_cancelled_setup_do_not_dismiss_prompt(extension,monkeypatch):
    from fastapi import HTTPException
    x=extension
    monkeypatch.setattr(automatic,'enabled',lambda *args:None)
    monkeypatch.setattr(feed_automation,'broker',AsyncMock(side_effect=RuntimeError('Unavailable')))
    req=SimpleNamespace(request_id=str(uuid.uuid4()),consent=True,grant_id=x.grant.id,native_symbol='ETH',
        fee_cap='0.0000000000000001',quantity=1,expires_at=x.old)
    with pytest.raises(HTTPException) as error:await feed_automation.create(x.db,x.owner,req)
    assert error.value.status_code==503
    assert not await feed_automation.enabled_once(x.db,x.owner)
    row=await x.db.get(FeedMintApproval,req.request_id);row.status='revoked';await x.db.commit()
    assert not await feed_automation.enabled_once(x.db,x.owner)


async def test_successful_signer_confirmation_records_enabled_once_atomically(extension,monkeypatch):
    x=extension
    monkeypatch.setattr(automatic,'enabled',lambda *args:None)
    async def confirm(key,operation='register'):
        result=await feed_automation.pin(x.db,x.journal,key,x.vault)
        await x.db.commit()
        return result
    monkeypatch.setattr(feed_automation,'broker',confirm)
    req=SimpleNamespace(request_id=str(uuid.uuid4()),consent=True,grant_id=x.grant.id,native_symbol='ETH',
        fee_cap='0.0000000000000001',quantity=1,expires_at=x.old)
    result=await feed_automation.create(x.db,x.owner,req)
    assert result['status']=='active'
    await x.db.refresh(x.owner)
    assert x.owner.feature_notices[feed_automation.ENABLED_ONCE] is True
    assert x.journal.execute('SELECT count(*) FROM signed').fetchone()[0]==0


async def test_one_tap_uses_only_selected_wallet_saved_limits_and_pins_maximum(extension,monkeypatch):
    x=extension;monkeypatch.setattr(automatic,'enabled',lambda *args:None)
    async def confirm(key,operation='register'):
        result=await feed_automation.pin(x.db,x.journal,key,x.vault)
        await x.db.commit();return result
    monkeypatch.setattr(feed_automation,'broker',confirm)
    original=copy.deepcopy(x.grant.scope),x.grant.context_hash,x.grant.budget_wei,x.grant.reserved_wei
    req=SimpleNamespace(request_id=str(uuid.uuid4()),wallet_id=x.wallet.id,consent=True)
    result=await feed_automation.enable_for_today_wallet(x.db,x.owner,req)
    snapshot=result['approvals'][0]['snapshot']
    assert snapshot['quantity_mode']=='wallet_max' and snapshot['quantity']==65535
    assert snapshot['fee_cap_wei']==x.grant.scope['max_task_wei']
    assert snapshot['wallet_id']==x.wallet.id and snapshot['expiry']==int(x.old.timestamp())
    assert original==(x.grant.scope,x.grant.context_hash,x.grant.budget_wei,x.grant.reserved_wei)
    req.request_id=str(uuid.uuid4())
    again=await feed_automation.enable_for_today_wallet(x.db,x.owner,req)
    assert again['approvals'][0]['id']==result['approvals'][0]['id']
    assert x.journal.execute('SELECT count(*) FROM feed_approvals').fetchone()[0]==1
    assert x.journal.execute('SELECT count(*) FROM signed').fetchone()[0]==0


async def test_one_tap_failed_confirmation_retries_identical_pending_approval(extension,monkeypatch):
    from fastapi import HTTPException
    x=extension;monkeypatch.setattr(automatic,'enabled',lambda *args:None)
    monkeypatch.setattr(feed_automation,'broker',AsyncMock(side_effect=RuntimeError('Unavailable')))
    req=SimpleNamespace(request_id=str(uuid.uuid4()),wallet_id=x.wallet.id,consent=True)
    with pytest.raises(HTTPException) as error:await feed_automation.enable_for_today_wallet(x.db,x.owner,req)
    assert error.value.status_code==503
    row=(await x.db.scalars(select(FeedMintApproval))).one()
    original=copy.deepcopy(row.snapshot)
    assert not await feed_automation.enabled_once(x.db,x.owner)
    async def confirm(key,operation='register'):
        result=await feed_automation.pin(x.db,x.journal,key,x.vault)
        await x.db.commit();return result
    monkeypatch.setattr(feed_automation,'broker',confirm)
    req.request_id=str(uuid.uuid4())
    result=await feed_automation.enable_for_today_wallet(x.db,x.owner,req)
    assert result['approvals'][0]['snapshot']==original
    assert await feed_automation.enabled_once(x.db,x.owner)


async def test_one_tap_requires_consent_and_owned_signing_wallet(extension):
    from fastapi import HTTPException
    x=extension
    req=SimpleNamespace(request_id=str(uuid.uuid4()),wallet_id=x.wallet.id,consent=False)
    with pytest.raises(HTTPException) as error:await feed_automation.enable_for_today_wallet(x.db,x.owner,req)
    assert error.value.status_code==422
    req.consent=True;req.wallet_id='someone-else'
    with pytest.raises(HTTPException) as error:await feed_automation.enable_for_today_wallet(x.db,x.owner,req)
    assert error.value.status_code==409
    assert (await x.db.scalars(select(FeedMintApproval))).all()==[]


async def test_one_tap_does_not_widen_existing_fixed_approval(approved):
    from fastapi import HTTPException
    x=approved;original=copy.deepcopy(x.approval.snapshot),x.approval.context_hash
    req=SimpleNamespace(request_id=str(uuid.uuid4()),wallet_id=x.wallet.id,consent=True)
    with pytest.raises(HTTPException) as error:await feed_automation.enable_for_today_wallet(x.db,x.owner,req)
    assert error.value.status_code==409
    await x.db.refresh(x.approval)
    assert original==(x.approval.snapshot,x.approval.context_hash)


def test_maximum_quantity_does_not_widen_fixed_approvals():
    assert not feed_automation.quantity_allowed({'quantity':2},3)
    assert feed_automation.quantity_allowed({'quantity':2},2)
    maximum={'quantity':65535,'quantity_mode':'wallet_max'}
    assert feed_automation.quantity_allowed(maximum,200)
    assert not feed_automation.quantity_allowed(maximum,0)
    assert not feed_automation.quantity_allowed(maximum,65536)


def test_large_free_quantity_calldata_is_supported_but_manual_consent_stays_bounded():
    from eth_abi import encode
    from pydantic import ValidationError
    from app.schemas.task import DraftTaskRequest
    from app.services.seadrop_mint import decode_mint,BASE_TYPES
    from app.services.signer.base import SEADROP_V1_ADDRESS,MINT_PUBLIC_SELECTOR
    nft='0x'+'1'*40;wallet='0x'+'2'*40;fee='0x'+'3'*40
    tx={'to':SEADROP_V1_ADDRESS,'value':'0','data':'0x'+MINT_PUBLIC_SELECTOR+encode(BASE_TYPES,[nft,fee,wallet,200]).hex()}
    assert decode_mint(tx,nft,wallet,200)['quantity']==200
    req=dict(wallet_id='wallet',drop_id='drop',stage_id='stage',quantity=200,fee_cap_eth='0.001')
    with pytest.raises(ValidationError):DraftTaskRequest(**req)
    assert DraftTaskRequest(**req,feed_approval_id='separately-verified').quantity==200
