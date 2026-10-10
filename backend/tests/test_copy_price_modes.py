"""Price filters work independently of public, allowlist and signed eligibility."""
import pytest
from sqlalchemy import select
from app.models import CopyEvent,CopyRule,MintTask,MintAuthorization
from app.services import copy_mints
from app.services.custody import CustodyVault
from test_copy_mints import copying
from test_copy_presales import presale
from test_automatic_evm import lab


@pytest.mark.parametrize('kind',['public','allowlist','signed'])
@pytest.mark.parametrize('free',[False,True])
@pytest.mark.parametrize('price',[0,5])
async def test_free_paid_selection_uses_receiving_wallet_price(copying,presale,kind,free,price):
    c,state,configure,mint_source=presale;lab=c['lab']
    c['request'].update(free_only=free,paid_only=not free,include_presales=True,
        price_cap_eth='0' if free else '0.00000000000000001')
    if kind=='public':
        lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
        lab.w.provider.make_request('hardhat_setBalance',[lab.nft.address,hex(10**18)])
        lab.w.eth.wait_for_transaction_receipt(lab.sea.functions.updatePublicDrop((price,lab.start,lab.end,20,500,True)).transact({'from':lab.nft.address}))
        lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
    else:
        state.kind=kind;state.own_price=price;configure()
    await c['approve']()
    await (c['mint'](1) if kind=='public' else mint_source())
    await c['scan']()
    event=(await lab.client.get('/api/copy-mints/activity')).json()['events'][0]
    matches=(price==0)==free
    if not matches:
        assert event['status']=='skipped' and event['task_id'] is None
        assert 'selected' in event['note']
        journal=CustodyVault().journal()
        assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0]==0
        journal.close()
    else:
        assert event['task_id'],event['note']
        async with lab.factory() as db:
            task=await db.get(MintTask,event['task_id']);auth=await db.get(MintAuthorization,task.authorization_id)
            assert auth.snapshot['price_wei']==price and auth.snapshot['mint_kind']==kind
            rule=await db.get(CopyRule,task.copy_rule_id)
            assert rule.snapshot.get('paid_only',False)==(not free)
        await lab.sign(event['task_id'])
        async with lab.factory() as db:
            assert (await db.get(MintTask,event['task_id'])).signed_tx_raw


async def test_signer_rejects_free_mint_under_pinned_paid_approval_even_after_db_tampering(copying):
    c=copying;lab=c['lab'];c['request'].update(paid_only=True)
    await c['approve']();await c['mint'](1);await c['scan']()
    lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
    lab.w.provider.make_request('hardhat_setBalance',[lab.nft.address,hex(10**18)])
    lab.w.eth.wait_for_transaction_receipt(lab.sea.functions.updatePublicDrop((0,lab.start,lab.end,20,500,True)).transact({'from':lab.nft.address}))
    lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
    free_hash=await c['mint'](1)
    provider=await copy_mints.automatic.provider()
    try:source=await copy_mints.observe(provider,31337,free_hash,c['source'].address,lab.nft.address)
    finally:await provider.provider.disconnect()
    async with lab.factory() as db:
        e=await db.scalar(select(CopyEvent).where(CopyEvent.watch_id==c['watch_id']))
        tid=e.task_id;task=await db.get(MintTask,tid);auth=await db.get(MintAuthorization,task.authorization_id)
        auth.snapshot={**auth.snapshot,'price_wei':0,'copy_source':source,
            'execution':{**auth.snapshot['execution'],'value':'0'}}
        await db.commit()
    response=await lab.signer_client.post(f'/tasks/{tid}/prepare')
    assert response.status_code==409
    journal=CustodyVault().journal()
    assert journal.execute('SELECT COUNT(*) FROM signed').fetchone()[0]==0
    journal.close()


@pytest.mark.parametrize('flags,cap',[
    ({'free_only':True,'paid_only':True},'0'),
    ({'free_only':False,'paid_only':True},'0'),
])
async def test_invalid_price_selection_is_rejected_before_registration(copying,flags,cap):
    c=copying;lab=c['lab']
    response=await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/rules',json={**c['request'],**flags,'price_cap_eth':cap})
    assert response.status_code==422
    async with lab.factory() as db:assert not (await db.scalars(select(CopyRule))).all()


async def test_paid_selection_cannot_be_removed_from_an_existing_request(copying):
    c=copying;lab=c['lab'];c['request'].update(paid_only=True)
    await c['approve']()
    response=await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/rules',json={**c['request'],'paid_only':False})
    assert response.status_code==409


@pytest.mark.parametrize('price',[0,5])
def test_legacy_mixed_price_approval_retains_its_scope(price):
    assert copy_mints.accepts_price({'free_only':False,'price_cap_wei':10},price)


@pytest.mark.parametrize('flags',[
    {'free_only':True,'paid_only':True},
    {'free_only':False,'paid_only':'false'},
])
def test_independent_price_validation_rejects_ambiguous_flags(flags):
    with pytest.raises(ValueError):copy_mints.quantity_mode({**flags,'price_cap_wei':10,'quantity':1})


async def test_check_only_paid_selection_skips_a_free_public_mint(copying):
    from datetime import datetime,timezone
    import uuid
    c=copying;lab=c['lab']
    response=await lab.client.post(f'/api/copy-mints/watches/{c["watch_id"]}/checks',json={
        'request_id':str(uuid.uuid4()),'wallet_id':lab.wallet.id,'quantity':1,
        'price_cap_eth':'0.00000000000000001','fee_cap_eth':'0.0005','budget_eth':'0.001',
        'free_only':False,'paid_only':True,'include_presales':True,
        'expires_at':datetime.fromtimestamp(lab.end,timezone.utc).isoformat()})
    assert response.status_code==200,response.text
    lab.w.provider.make_request('hardhat_impersonateAccount',[lab.nft.address])
    lab.w.provider.make_request('hardhat_setBalance',[lab.nft.address,hex(10**18)])
    lab.w.eth.wait_for_transaction_receipt(lab.sea.functions.updatePublicDrop((0,lab.start,lab.end,20,500,True)).transact({'from':lab.nft.address}))
    lab.w.provider.make_request('hardhat_stopImpersonatingAccount',[lab.nft.address])
    await c['mint'](1);await c['scan']()
    result=(await lab.client.get('/api/copy-mints/check-results')).json()['results'][0]
    assert result['status']=='would_skip' and 'selected free or paid mode' in result['note']
    async with lab.factory() as db:assert not (await db.scalars(select(MintTask))).all()
