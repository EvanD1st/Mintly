"""Guided UX cannot change wallet authority, exact stage or old copy consent."""
from datetime import datetime,timezone
from sqlalchemy import select,func
import pytest
from app.models import Wallet,MintTask,MintAuthorization,AutomaticGrant,CopyRule,CopyEvent
from app.services import automatic
from app.services.custody import CustodyVault
from test_automatic_evm import lab
from test_copy_mints import copying
from test_copy_presales import presale


async def test_address_only_wallet_creates_no_signing_authority(lab):
    result=await lab.client.post('/api/wallets/watch',json={'label':'Read-only address','address':lab.w.eth.accounts[5]})
    assert result.status_code==200,result.text
    wid=result.json()['id']
    again=await lab.client.post('/api/wallets/watch',json={'label':'Same address','address':lab.w.eth.accounts[5]})
    assert again.json()['id']==wid
    async with lab.factory() as db:
        wallet=await db.get(Wallet,wid)
        assert wallet.signing_capability=='watch_only'
        assert not (await db.scalars(select(AutomaticGrant).where(AutomaticGrant.wallet_id==wid))).all()
    attempt=await lab.client.post('/api/tasks/arm',json={**lab.request,'wallet_id':wid})
    assert attempt.status_code==409


@pytest.mark.parametrize('kind',['public','allowlist','signed'])
async def test_guided_preview_derives_exact_stage_and_limits_without_signing(lab,kind):
    lab.kind=kind
    if kind!='public':
        # Prevent accidental match to public metadata while the exact presale remains valid.
        lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
        lab.sea.functions.updatePublicDrop((11,lab.start,lab.end,20,500,True)).transact({'from':lab.nft.address})
        lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
    request={'wallet_id':lab.wallet.id,'grant_id':lab.grant.id,'drop_id':lab.drop.id,'stage_id':lab.stage.id,
        'quantity':2,'maximum_total_eth':'0.00050000000000002',
        'scheduled_for_utc':datetime.fromtimestamp(lab.start,timezone.utc).isoformat()}
    result=await lab.client.post('/api/tasks/guided-preview',json=request)
    assert result.status_code==200,result.text
    data=result.json()
    assert data['snapshot']['mint_kind']==kind
    assert data['snapshot']['price_wei']==10
    assert data['snapshot']['total_cap_wei']==500000000000020
    assert data['snapshot']['fee_cap_wei']==500000000000000
    assert data['request']['onchain_stage_index']==(None if kind=='public' else 1)
    async with lab.factory() as db:assert not (await db.scalars(select(MintTask))).all()
    armed=await lab.client.post('/api/tasks/arm',json={**data['request'],'review_hash':data['review_hash'],
        'user_consent_confirmed':True,'idempotency_key':'guided-consent-'+kind})
    assert armed.status_code==200,armed.text
    # Chosen future time is still a hard gate.
    assert (await lab.sign(armed.json()['id']))['status']=='armed'


@pytest.mark.parametrize('bad',['foreign_wallet','insufficient_total','past_time'])
async def test_guided_missing_prerequisite_or_bad_amount_never_creates_a_task(lab,bad):
    body={'wallet_id':lab.wallet.id,'grant_id':lab.grant.id,'drop_id':lab.drop.id,'stage_id':lab.stage.id,
        'quantity':2,'maximum_total_eth':'0.00050000000000002','scheduled_for_utc':datetime.fromtimestamp(lab.start,timezone.utc).isoformat()}
    if bad=='foreign_wallet':body['wallet_id']='not-owned'
    if bad=='insufficient_total':body['maximum_total_eth']='0.00000000000000002'
    if bad=='past_time':body['scheduled_for_utc']='2020-01-01T00:00:00Z'
    result=await lab.client.post('/api/tasks/guided-preview',json=body)
    assert result.status_code in (404,409,422)
    async with lab.factory() as db:assert await db.scalar(select(func.count()).select_from(MintTask))==0


async def test_guided_whitelist_rejects_provider_public_fallback(lab,monkeypatch):
    lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
    lab.sea.functions.updatePublicDrop((11,lab.start,lab.end,20,500,True)).transact({'from':lab.nft.address})
    lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
    from eth_abi import encode
    from app.services.signer.base import SEADROP_V1_ADDRESS,MINT_PUBLIC_SELECTOR
    async def public(*args):return 200,{'chain':'local-test','to':SEADROP_V1_ADDRESS,'value':'20','data':'0x'+MINT_PUBLIC_SELECTOR+encode(
        ['address','address','address','uint256'],[lab.nft.address,lab.w.eth.accounts[1],lab.owner.address,2]).hex()}
    monkeypatch.setattr('app.services.opensea.OpenSeaClient.build_mint',public)
    result=await lab.client.post('/api/tasks/guided-preview',json={'wallet_id':lab.wallet.id,'grant_id':lab.grant.id,
        'drop_id':lab.drop.id,'stage_id':lab.stage.id,'quantity':2,'maximum_total_eth':'0.0005',
        'scheduled_for_utc':datetime.fromtimestamp(lab.start,timezone.utc).isoformat()})
    assert result.status_code==409
    assert 'Public fallback' in result.json()['detail']


async def test_paid_maximum_public_quantity_obeys_wallet_and_spending_limits(copying):
    c=copying;lab=c['lab']
    c['request'].update(quantity=100,quantity_mode='max_available',include_presales=True,fee_cap_eth='0.00099',budget_eth='0.002')
    result=await c['approve']()
    assert result['status']=='active'
    await c['mint'](1);await c['scan']()
    async with lab.factory() as db:
        event=await db.scalar(select(CopyEvent));task=await db.get(MintTask,event.task_id)
        assert task is not None,event.note
        auth=await db.get(MintAuthorization,task.authorization_id)
        assert auth.quantity==20
        assert auth.snapshot['copy_quantity_mode']=='max_available'
        assert auth.total_spend_cap_wei<=1000000000000000
    await lab.sign(task.id)
    journal=CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0]==1
    journal.close()


async def test_paid_maximum_does_not_expand_an_old_fixed_approval(copying):
    c=copying;lab=c['lab']
    await c['approve']()
    changed=await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/rules',json={**c['request'],
        'quantity':100,'quantity_mode':'max_available','include_presales':True})
    assert changed.status_code==409
    async with lab.factory() as db:
        rule=await db.get(CopyRule,c['request']['request_id'])
        assert rule.snapshot['quantity']==1 and rule.snapshot.get('mint_kinds',['public'])==['public']


async def test_legacy_idempotency_digest_is_preserved(lab):
    from app.schemas.task import ArmTaskRequest
    body=ArmTaskRequest(**lab.request)
    result=await lab.client.post('/api/tasks/arm',json=lab.request)
    assert result.status_code==200,result.text
    async with lab.factory() as db:
        task=await db.get(MintTask,result.json()['id'])
        assert task.request_hash==automatic.digest(body.model_dump(mode='json',exclude={'idempotency_key','guided'}))
    assert (await lab.client.post('/api/tasks/arm',json=lab.request)).json()['id']==result.json()['id']


@pytest.mark.parametrize('kind',['allowlist','signed'])
async def test_paid_maximum_whitelist_uses_receiving_wallet_allowance(presale,kind):
    c,state,_,mint_source=presale
    lab=c['lab'];state.kind=kind
    c['request'].update(quantity=100,quantity_mode='max_available',fee_cap_eth='0.0009')
    await c['approve']();await mint_source();await c['scan']()
    async with lab.factory() as db:
        event=await db.scalar(select(CopyEvent));task=await db.get(MintTask,event.task_id)
        assert task is not None,event.note
        auth=await db.get(MintAuthorization,task.authorization_id)
        assert auth.quantity==7 and auth.snapshot['price_wei']==5
        assert auth.snapshot['copy_quantity_mode']=='max_available'
        assert auth.snapshot['onchain_stage_index']==7
    assert (lab.owner.address.lower(),7) in state.calls
    await lab.sign(task.id)
    journal=CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0]==1
    journal.close()
