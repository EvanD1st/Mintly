"""Independent network routing, Base outside-gas fees and inclusion accounting."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from eth_abi import encode
import pytest
from fastapi import HTTPException
from web3.datastructures import AttributeDict
from app.config import settings
from app.services import automatic
from app.services.automatic_fees import additional_fee, maximum_fee, receipt_cost


@pytest.mark.parametrize('chain,flag,rpc', [(1,'ENABLE_ETHEREUM_AUTOMATIC','RPC_ETHEREUM'),(8453,'ENABLE_BASE_AUTOMATIC','RPC_BASE')])
def test_each_mainnet_needs_its_own_opt_in_and_https(monkeypatch, chain, flag, rpc):
    monkeypatch.setattr(settings, 'ENABLE_CUSTODIAL_AUTOMATIC', True)
    monkeypatch.setattr(settings, 'AUTOMATIC_CHAIN_ID', 4663)
    monkeypatch.setattr(settings, flag, False)
    with pytest.raises(HTTPException): automatic.enabled(chain)
    monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, rpc, 'https://rpc.example.test')
    automatic.enabled(chain)
    assert automatic.rpc_for(chain) == 'https://rpc.example.test'
    monkeypatch.setattr(settings, rpc, 'http://rpc.example.test')
    with pytest.raises(HTTPException): automatic.enabled(chain)


async def test_provider_routes_selected_chain_and_rejects_wrong_rpc(monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_CUSTODIAL_AUTOMATIC', True)
    monkeypatch.setattr(settings, 'ENABLE_BASE_AUTOMATIC', True)
    monkeypatch.setattr(settings, 'AUTOMATIC_CHAIN_ID', 4663)
    monkeypatch.setattr(settings, 'RPC_BASE', 'https://base.example.test')
    class Eth:
        @property
        async def chain_id(self): return 1
    disconnector = AsyncMock()
    class Provider:
        def __init__(self, url, **kwargs):
            assert url == settings.RPC_BASE
        disconnect = disconnector
    class Web3:
        AsyncHTTPProvider = Provider
        def __init__(self, provider): self.provider, self.eth = provider, Eth()
    monkeypatch.setattr(automatic, 'AsyncWeb3', Web3)
    with pytest.raises(ValueError, match='mismatch'): await automatic.provider_for(8453)
    disconnector.assert_awaited_once()


async def test_base_quote_reserves_parent_and_operator_fees_beyond_l2_gas():
    call = AsyncMock(side_effect=[encode(['uint256'], [1000]), encode(['uint256'], [200])])
    w = SimpleNamespace(eth=SimpleNamespace(call=call))
    fee = await maximum_fee(w, {'data':'0x1234'}, 8453, 100, 10)
    assert fee == 1000 + 1800
    assert call.await_count == 2
    assert call.call_args_list[0].args[1] == 'pending'
    assert await additional_fee(w, 1, 100, 300) == 0


@pytest.mark.parametrize('status', [0,1])
async def test_base_receipt_charges_all_fees_even_on_revert(status):
    w = SimpleNamespace(eth=SimpleNamespace(call=AsyncMock(return_value=encode(['uint256'], [20]))))
    receipt = AttributeDict(dict(gasUsed=100,effectiveGasPrice=10,status=status,l1Fee='0x64',blockNumber=5))
    assert await receipt_cost(w, receipt, 8453, 200) == 1120 + (200 if status else 0)
    assert w.eth.call.call_args.args[1] == 5
    assert await receipt_cost(w, receipt, 1, 200) == 1000 + (200 if status else 0)


async def test_base_missing_receipt_fee_data_cannot_report_false_spend():
    receipt = AttributeDict(dict(gasUsed=100,effectiveGasPrice=10,status=1,blockNumber=5))
    with pytest.raises(ValueError, match='parent fee'):
        await receipt_cost(SimpleNamespace(), receipt, 8453, 200)
