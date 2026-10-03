from types import SimpleNamespace
from unittest.mock import AsyncMock

from eth_abi import encode
from eth_utils import keccak
import pytest
from fastapi import HTTPException

from app.config import settings
from app.services import automatic
from app.services.custody_accounts import inspect_account, verify_account
from app.services.automatic_fees import quote_gas
from app.services.automatic_signer import final_receipt

ADDRESS = '0x' + '11' * 20
CODE = bytes.fromhex('ef0100' + '22' * 20)


@pytest.mark.parametrize('code', [b'\x60\x00', CODE[:-1], CODE+b'\x00', CODE])
async def test_unprovisioned_code_fails_closed(code):
    web3 = SimpleNamespace(eth=SimpleNamespace(get_code=AsyncMock(return_value=code)))
    with pytest.raises(ValueError):
        await verify_account(web3, {'account':ADDRESS})


@pytest.mark.parametrize('changed', ['delegation', 'implementation', 'empty', 'chained'])
async def test_changed_or_unsupported_delegate_rejected(changed):
    pin = {'mode':'eip7702-direct','delegation':'0x'+CODE.hex(),
        'delegate_code_hash':'0x'+keccak(b'\x00').hex()}
    actual_code = bytes.fromhex('ef0100'+'33'*20) if changed == 'delegation' else CODE
    implementation = {'implementation':b'\x60\x00', 'empty':b'', 'chained':CODE}.get(changed,b'\x00')
    web3 = SimpleNamespace(eth=SimpleNamespace(get_code=AsyncMock(side_effect=[actual_code,implementation])))
    with pytest.raises(ValueError):
        await verify_account(web3, {'account':ADDRESS,'account_adapter':pin})


async def test_nitro_quote_includes_positive_parent_fee_once():
    class Eth:
        @property
        async def gas_price(self): return 10
        estimate_gas = AsyncMock(return_value=100000)
        call = AsyncMock(return_value=encode(['uint64','uint64','uint256','uint256'],[120000,20000,12,100]))
    gas, price = await quote_gas(SimpleNamespace(eth=Eth()),
        {'from':ADDRESS,'to':ADDRESS,'value':0,'data':'0x1234'},4663)
    assert (gas,price)==(144000,12)
    assert gas*price == 1728000


async def test_robinhood_finality_waits_for_finalized_block(monkeypatch):
    monkeypatch.setattr(settings,'AUTOMATIC_CHAIN_ID',4663)
    receipt = SimpleNamespace(blockNumber=10,blockHash=b'h')
    class Eth:
        @property
        async def block_number(self): return 50
        get_transaction_receipt = AsyncMock(return_value=receipt)
        get_block = AsyncMock(side_effect=[SimpleNamespace(hash=b'h'),SimpleNamespace(number=9),
            SimpleNamespace(hash=b'h'),SimpleNamespace(number=10)])
    web3 = SimpleNamespace(eth=Eth())
    assert await final_receipt(web3,'hash') is None
    assert await final_receipt(web3,'hash') is receipt


def test_mainnet_needs_explicit_opt_in_and_https(monkeypatch):
    monkeypatch.setattr(settings,'ENABLE_CUSTODIAL_AUTOMATIC',True)
    monkeypatch.setattr(settings,'AUTOMATIC_CHAIN_ID',4663)
    monkeypatch.setattr(settings,'AUTOMATIC_RPC','https://example.com')
    monkeypatch.setattr(settings,'ENABLE_ROBINHOOD_AUTOMATIC',False)
    with pytest.raises(HTTPException): automatic.enabled()
    monkeypatch.setattr(settings,'ENABLE_ROBINHOOD_AUTOMATIC',True)
    automatic.enabled()
    monkeypatch.setattr(settings,'AUTOMATIC_RPC','http://example.com')
    with pytest.raises(HTTPException): automatic.enabled()
