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

