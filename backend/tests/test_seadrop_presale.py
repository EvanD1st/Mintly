"""Presale decoding and exact metadata binding; no live wallet or funds."""
from datetime import datetime,timezone
from eth_abi import encode
from eth_account import Account
import pytest

from app.services.seadrop_mint import decode_mint, match_stage, PARAM_TYPE, ALLOW_SELECTOR, SIGNED_SELECTOR
from app.services.signer.base import SEADROP_V1_ADDRESS
from app.services.opensea import OpenSeaUnavailable


@pytest.mark.parametrize('selector',[ALLOW_SELECTOR,SIGNED_SELECTOR])
def test_presale_rejects_redirected_wallet_quantity_price_and_noncanonical_data(selector):
    wallet=Account.create().address;contract=Account.create().address;fee=Account.create().address
    params=(10,5,100,200,1,100,500,True)
    types=['address','address','address','uint256',PARAM_TYPE]+(['bytes32[]'] if selector==ALLOW_SELECTOR else ['uint256','bytes'])
    tail=[[]] if selector==ALLOW_SELECTOR else [42,b'\x01'*65]
    values=[contract,fee,wallet,2,params]+tail
    tx={'to':SEADROP_V1_ADDRESS,'data':'0x'+selector+encode(types,values).hex(),'value':'20'}
    decoded=decode_mint(tx,contract,wallet,2)
    assert decoded['params']==params
    assert decode_mint({**tx,'data':tx['data']+'3d958fe2'},contract,wallet,2)['execution']['data'].endswith('3d958fe2')
    for changed in [{**tx,'value':'21'},{**tx,'to':contract},{**tx,'data':tx['data']+'00'*32}]:
        with pytest.raises(OpenSeaUnavailable):decode_mint(changed,contract,wallet,2)
    for wrong_wallet,qty in [(Account.create().address,2),(wallet,3)]:
        with pytest.raises(OpenSeaUnavailable):decode_mint(tx,contract,wrong_wallet,qty)
    stage={'uuid':'eligible','type':'presale','starts_at':datetime.fromtimestamp(100,timezone.utc),'ends_at':datetime.fromtimestamp(200,timezone.utc),'price_wei':10}
    other={**stage,'uuid':'other','price_wei':20}
    assert match_stage(decoded,[other,stage])['uuid']=='eligible'
    with pytest.raises(OpenSeaUnavailable):match_stage(decoded,[other])
    with pytest.raises(OpenSeaUnavailable):match_stage(decoded,[stage,{**stage,'uuid':'ambiguous'}])
