from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from app.services import auto_arm_funding as funding, reservation_quote as quote


@pytest.mark.parametrize('currency,price,expected', [('APE','0.1',10*10**18),('HYPE','80',125*10**14)])
def test_one_dollar_conversion(currency,price,expected):
    assert quote.parse_quote({'data':{'base':currency,'currency':'USD','amount':price}},currency)==expected


@pytest.mark.parametrize('value', ['0','-1','NaN','Infinity','0.00000001'])
def test_invalid_price_is_not_used(value):
    with pytest.raises(ValueError):quote.parse_quote({'data':{'base':'APE','currency':'USD','amount':value}},'APE')


def test_wrong_currency_is_not_used():
    with pytest.raises(ValueError):quote.parse_quote({'data':{'base':'ETH','currency':'USD','amount':'10'}},'APE')


async def test_native_queued_hold_is_capped_by_existing_approval(monkeypatch):
    monkeypatch.setattr(quote,'dollar_native_wei',AsyncMock(return_value=10*10**18))
    assert await funding.queued_amount(33139,9*10**18)==9*10**18
    assert await funding.queued_amount(999,20*10**18)==10*10**18
    assert await funding.queued_amount(1,20*10**18)==10**13
    assert await funding.queued_amount(8453,1)==1


async def test_quote_outage_retries_new_arming_and_preserves_existing_hold(monkeypatch):
    monkeypatch.setattr(quote,'dollar_native_wei',AsyncMock(return_value=None))
    auth=SimpleNamespace(snapshot={'chain_id':33139,'feed_approval_id':'approval'},total_spend_cap_wei=9*10**18)
    with pytest.raises(HTTPException) as error:await funding.queued(auth,strict=True)
    assert error.value.status_code==503 and '$1' in error.value.detail
    assert await funding.queued(auth)==auth.total_spend_cap_wei
    auth.snapshot={}
    assert await funding.queued(auth)==auth.total_spend_cap_wei


async def test_expired_quote_is_not_reused_during_outage(monkeypatch):
    quote._cache['APE']=(10*10**18,datetime.now(timezone.utc)-timedelta(minutes=2))
    def unavailable(**kwargs):raise TimeoutError()
    monkeypatch.setattr(quote.aiohttp,'ClientSession',unavailable)
    assert await quote.dollar_native_wei('APE') is None
    quote._cache.clear()


@pytest.mark.parametrize('stats,reason', [((0,1500,1500),'supply_exhausted'),((1,2,1500),'wallet_limit')])
async def test_sold_out_and_wallet_limit_keep_distinct_reasons(stats,reason):
    from eth_abi import encode
    from app.services.free_copy import require_unminted
    web3=SimpleNamespace(eth=SimpleNamespace(call=AsyncMock(return_value=encode(['uint256']*3,stats))))
    with pytest.raises(HTTPException) as error:
        await require_unminted(web3,'0x'+'1'*40,'0x'+'2'*40)
    assert error.value.headers['X-Mintly-Reason']==reason
    if reason=='supply_exhausted':assert 'sold out' in error.value.detail
