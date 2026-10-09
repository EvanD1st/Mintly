from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from eth_abi import encode

from app.services.mint_plans import refresh_mint_plan
from app.services.seadrop_mint import PARAM_TYPE,ALLOW_SELECTOR
from app.services.signer.base import SEADROP_V1_ADDRESS


@pytest.mark.asyncio
async def test_overlapping_stages_bind_eligible_presale_not_first_or_most_expensive(monkeypatch):
    now=datetime.now(timezone.utc).replace(microsecond=0)
    start=now-timedelta(minutes=1);end=now+timedelta(hours=1)
    wallet=SimpleNamespace(id='wallet',user_id='member',address='0x'+'1'*40)
    plan=SimpleNamespace(wallet_id='wallet',user_id='member',chain_id=8453,contract_address='0x'+'2'*40,collection_slug='example',quantity=2)
    def stage(uuid,kind,price,ends):return {'uuid':uuid,'stage_type':kind,'label':uuid,'start_time':start.isoformat(),'end_time':ends.isoformat(),'price':str(price),'max_per_wallet':'1','price_currency_address':'0x'+'0'*40}
    details={'chain':'base','contract_address':plan.contract_address,'stages':[stage('public','public_sale',20,end+timedelta(hours=1)),stage('wallet-presale','presale',10,end)]}
    params=(10,4,int(start.timestamp()),int(end.timestamp()),1,100,500,True)
    tx={'chain':'base','to':SEADROP_V1_ADDRESS,'value':'20','data':'0x'+ALLOW_SELECTOR+encode(['address','address','address','uint256',PARAM_TYPE,'bytes32[]'],[plan.contract_address,'0x'+'3'*40,wallet.address,2,params,[]]).hex()}
    fake=SimpleNamespace(build_mint=AsyncMock(return_value=(200,tx)))
    monkeypatch.setattr('app.services.mint_plans.eth_usdt_quote',AsyncMock(return_value=None))
    monkeypatch.setattr('app.services.mint_plans.estimate_network_fee',AsyncMock(return_value=100))
    await refresh_mint_plan(plan,wallet,fake,now=now,detail=details)
    assert plan.status=='ready_for_approval'
    assert plan.stage_uuid=='wallet-presale' and plan.stage_name=='wallet-presale'
    assert plan.stage_type=='presale' and plan.price_wei==10 and plan.ends_at==end
    # Stage defaults are not the cumulative wallet-specific allowed quantity.
    assert plan.quantity==2


@pytest.mark.asyncio
async def test_future_presale_does_not_claim_eligibility_without_a_proof(monkeypatch):
    now=datetime.now(timezone.utc)
    plan=SimpleNamespace(wallet_id='wallet',user_id='member',chain_id=8453,contract_address='0x'+'2'*40,collection_slug='example',quantity=1)
    wallet=SimpleNamespace(id='wallet',user_id='member',address='0x'+'1'*40)
    details={'chain':'base','contract_address':plan.contract_address,'stages':[{'uuid':'future','stage_type':'presale','label':'Allowlist','start_time':(now+timedelta(hours=1)).isoformat(),'end_time':(now+timedelta(hours=2)).isoformat(),'price':'10','max_per_wallet':'1','price_currency_address':'0x'+'0'*40}]}
    client=SimpleNamespace(build_mint=AsyncMock())
    monkeypatch.setattr('app.services.mint_plans.eth_usdt_quote',AsyncMock(return_value=None))
    await refresh_mint_plan(plan,wallet,client,now=now,detail=details)
    assert plan.status=='scheduled' and plan.mint_value_wei is None
    client.build_mint.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_public_phase_never_switches_to_an_eligible_presale(monkeypatch):
    now=datetime.now(timezone.utc).replace(microsecond=0)
    start=now-timedelta(minutes=1);end=now+timedelta(hours=1)
    wallet=SimpleNamespace(id='wallet',user_id='member',address='0x'+'1'*40)
    plan=SimpleNamespace(wallet_id='wallet',user_id='member',chain_id=8453,contract_address='0x'+'2'*40,collection_slug='example',quantity=1)
    def stage(uid,kind,price,ends):return {'uuid':uid,'stage_type':kind,'label':uid,'start_time':start.isoformat(),
        'end_time':ends.isoformat(),'price':str(price),'max_per_wallet':'2','price_currency_address':'0x'+'0'*40}
    details={'chain':'base','contract_address':plan.contract_address,'stages':[
        stage('public','public_sale',20,end+timedelta(hours=1)),stage('gtd','presale',10,end)]}
    from app.services.mint_stage_choice import pinned
    from app.services.opensea import stage_schedule
    plan.selected_stage=pinned(stage_schedule(details)[0])
    params=(10,4,int(start.timestamp()),int(end.timestamp()),1,100,500,True)
    tx={'chain':'base','to':SEADROP_V1_ADDRESS,'value':'10','data':'0x'+ALLOW_SELECTOR+encode(
        ['address','address','address','uint256',PARAM_TYPE,'bytes32[]'],[plan.contract_address,'0x'+'3'*40,wallet.address,1,params,[]]).hex()}
    fake=SimpleNamespace(build_mint=AsyncMock(return_value=(200,tx)))
    monkeypatch.setattr('app.services.mint_plans.eth_usdt_quote',AsyncMock(return_value=None))
    outgoing={}
    await refresh_mint_plan(plan,wallet,fake,now=now,detail=details,transaction_out=outgoing)
    assert plan.stage_uuid=='public' and plan.stage_type=='public_sale'
    assert plan.status=='not_ready' and outgoing=={}
    assert 'will not switch' in plan.status_note
