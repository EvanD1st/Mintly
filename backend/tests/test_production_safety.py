"""Regression checks for public deployments and real transaction receipts."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.services.mint_executor import ExecutionException, MintExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/wallets", "/api/tasks/queue", "/api/source/status"])
async def test_production_read_endpoints_require_auth_even_with_debug(monkeypatch, path):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DEBUG", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_broadcast_disabled_before_any_rpc_call(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_LIVE_BROADCAST", False)
    with pytest.raises(ExecutionException, match="disabled"):
        await MintExecutor().broadcast_transaction("0x" + "ab" * 100, "base")


@pytest.mark.asyncio
async def test_real_hash_requires_a_real_receipt(monkeypatch):
    receipt = AsyncMock(return_value={"status": 0, "gasUsed": 42, "effectiveGasPrice": 10, "blockNumber": 123})
    monkeypatch.setattr("app.services.mint_executor.AsyncWeb3", type("FakeWeb3", (), {
        "AsyncHTTPProvider": staticmethod(lambda url: None),
        "__new__": staticmethod(lambda cls, provider: SimpleNamespace(eth=SimpleNamespace(get_transaction_receipt=receipt))),
    }))
    tx_hash = "0x" + "1" * 64
    result = await MintExecutor().reconcile_transaction(tx_hash, "base")
    receipt.assert_awaited_once_with(tx_hash)
    assert result["status"] == "reverted"


@pytest.mark.asyncio
async def test_only_explicit_demo_receipts_are_simulated():
    result = await MintExecutor().reconcile_transaction("0x" + "1" * 64, "base", is_demo=True)
    assert result["status"] == "confirmed"
