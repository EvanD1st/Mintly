import copy
from datetime import datetime,timezone
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from app.models import MintTask,MintAuthorization
from app.services import automatic
from test_automatic_evm import lab


def detail(lab,start=None,end=None,price=10):
    return {'chain':'local-test','contract_address':lab.nft.address,'stages':[{
        'uuid':'public','stage_type':'public_sale','label':'Public',
        'start_time':datetime.fromtimestamp(start or lab.start,timezone.utc).isoformat(),
        'end_time':datetime.fromtimestamp(end or lab.end,timezone.utc).isoformat(),
        'price':str(price),'max_per_wallet':'20','price_currency_address':'0x'+'0'*40}]}


def update(lab,start,end,price=10):
    lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
    lab.w.eth.wait_for_transaction_receipt(lab.sea.functions.updatePublicDrop((price,start,end,20,500,True)).transact({'from':lab.nft.address}))
    lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])


@pytest.mark.parametrize('delta',[-30,30])
async def test_real_phase_change_reschedules_then_signs_once_with_immutable_consent(lab,monkeypatch,delta):
    provider=AsyncMock(return_value=detail(lab))
    monkeypatch.setattr('app.services.opensea.OpenSeaClient.get_drop',provider)
    response=await lab.client.post('/api/tasks/arm',json={**lab.request,'schedule_mode':'phase_open'})
    assert response.status_code==200,response.text
    task_id=response.json()['id']
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id);auth=await db.get(MintAuthorization,task.authorization_id)
        original=copy.deepcopy(auth.snapshot)
    new=lab.start+delta
    update(lab,new,lab.end);provider.return_value=detail(lab,new)
    refreshed=await lab.signer_client.post(f'/tasks/{task_id}/refresh-schedule')
    assert refreshed.status_code==200,refreshed.text
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert int(task.scheduled_for_utc.replace(tzinfo=timezone.utc).timestamp())==new
        assert (await db.get(MintAuthorization,task.authorization_id)).snapshot==original
        assert 'WAT' in task.schedule_note
    lab.w.provider.make_request('evm_setNextBlockTimestamp',[new]);lab.w.provider.make_request('evm_mine',[])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromtimestamp(lab.w.eth.get_block('latest').timestamp,tz)
    monkeypatch.setattr('app.services.automatic_signer.datetime',Clock)
    first=await lab.sign(task_id);second=await lab.sign(task_id)
    assert first['hash']==second['hash']
    after=await lab.signer_client.post(f'/tasks/{task_id}/refresh-schedule')
    assert after.status_code==409
    async with lab.factory() as db:
        signed=await db.get(MintTask,task_id)
        receipt=lab.w.eth.wait_for_transaction_receipt(lab.w.eth.send_raw_transaction(signed.signed_tx_raw))
    assert receipt.status==1
    assert lab.nft.functions.totalSupply().call()==2


async def test_real_price_change_stops_without_signing_or_moving_custom_time(lab,monkeypatch):
    provider=AsyncMock(return_value=detail(lab));monkeypatch.setattr('app.services.opensea.OpenSeaClient.get_drop',provider)
    response=await lab.client.post('/api/tasks/arm',json={**lab.request,'schedule_mode':'phase_open'})
    assert response.status_code==200,response.text
    task_id=response.json()['id'];provider.return_value=detail(lab,price=20)
    result=await lab.signer_client.post(f'/tasks/{task_id}/refresh-schedule')
    assert result.status_code==200 and result.json()['status']=='failed',result.text
    async with lab.factory() as db:
        task=await db.get(MintTask,task_id)
        assert task.signed_tx_raw is None and task.transaction_hash is None
        assert 'price' in task.failure_reason and 'Review' in task.failure_reason
