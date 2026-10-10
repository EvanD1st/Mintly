"""Personal OpenSea plans must never become unattended mint authorizations."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_db
from app.main import app
from app.models import MintPlan, User, Wallet
from app.services.opensea import CHAINS, OpenSeaClient, OpenSeaUnavailable, chain_rpc, collection_slug, stage_schedule, transaction_value_wei
from app.services.signer.base import SEADROP_V1_ADDRESS
from app.services.mint_plans import verified_stage_schedule

@pytest.fixture(autouse=True)
def mock_display_quote(monkeypatch):
    monkeypatch.setattr("app.services.mint_plans.eth_usdt_quote", AsyncMock(return_value=("2500", datetime.now(timezone.utc))))


@pytest.mark.parametrize("url", [
    "http://opensea.io/collection/example",
    "https://opensea.io.evil.test/collection/example",
    "https://opensea.io/collection/example?redirect=evil",
    "https://opensea.io:bad/collection/example",
    "https://opensea.io/collection/../../private",
])
def test_only_direct_opensea_collection_urls(url):
    with pytest.raises(OpenSeaUnavailable):
        collection_slug(url)


def test_stage_schedule_is_sorted_and_uses_native_price():
    now = datetime.now(timezone.utc)
    def stage(index, minutes):
        return {"uuid": str(index), "stage_type": "public_sale", "label": "Public",
                "start_time": (now + timedelta(minutes=minutes)).isoformat(),
                "end_time": (now + timedelta(minutes=minutes + 30)).isoformat(),
                "price": "1000000000000000", "max_per_wallet": "2",
                "price_currency_address": "0x" + "0" * 40}
    sorted_stages = stage_schedule({"stages": [stage(2, 60), stage(1, 10)]})
    assert [s["uuid"] for s in sorted_stages] == ["1", "2"]


@pytest.mark.asyncio
async def test_public_plan_review_uses_current_seadrop_terms(monkeypatch):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    public = {"uuid": "public", "stage_type": "public_sale", "label": "Public",
              "start_time": (now - timedelta(hours=2)).isoformat(),
              "end_time": (now + timedelta(days=1)).isoformat(),
              "price": "0", "max_per_wallet": "5",
              "price_currency_address": "0x" + "0" * 40}
    presale = dict(public, uuid="team", stage_type="signed_presale", label="Team")
    detail = {"stages": [public, presale]}
    web3 = SimpleNamespace(provider=SimpleNamespace(disconnect=AsyncMock()))
    lookup = AsyncMock(return_value=web3)
    chain_terms = AsyncMock(return_value={
        'start': int((now - timedelta(hours=1)).timestamp()),
        'end': int((now + timedelta(days=2)).timestamp()),
        'price_wei': 10**15, 'limit': 3})
    monkeypatch.setattr('app.services.automatic.provider_for', lookup)
    monkeypatch.setattr('app.services.copy_mints.public_stage', chain_terms)

    stages = await verified_stage_schedule(detail, 4663, '0x' + '2' * 40)
    actual = next(stage for stage in stages if stage['uuid'] == 'public')
    assert actual['starts_at'] == now - timedelta(hours=1)
    assert actual['ends_at'] == now + timedelta(days=2)
    assert actual['price_wei'] == 10**15
    assert actual['max_per_wallet'] == 3
    assert next(stage for stage in stages if stage['uuid'] == 'team')['starts_at'] == now - timedelta(hours=2)
    lookup.assert_awaited_once_with(4663)
    chain_terms.assert_awaited_once_with(web3, '0x' + '2' * 40)
    web3.provider.disconnect.assert_awaited_once()

    chain_terms.side_effect = ValueError('No bounded public stage')
    with pytest.raises(OpenSeaUnavailable, match='could not be verified on chain'):
        await verified_stage_schedule(detail, 4663, '0x' + '2' * 40)


@pytest.mark.asyncio
@pytest.mark.parametrize("chain", list(CHAINS))
@pytest.mark.parametrize("quantity", [1, 2])
async def test_member_import_checks_wallet_and_never_creates_mint_task(test_db, monkeypatch, chain, quantity):
    user = (await test_db.execute(select(User).where(User.username == "member"))).scalar_one()
    wallet = Wallet(user_id=user.id, label="MetaMask", address="0x" + "1" * 40,
                    signing_capability="interactive", supported_chains=["Base"], is_default=True)
    test_db.add(wallet)
    await test_db.commit()

    now = datetime.now(timezone.utc)
    detail = {
        "collection_slug": "example", "collection_name": "Example",
        "opensea_url": "https://opensea.io/collection/example",
        "drop_type": "seadrop_v1_erc721", "chain": chain,
        "contract_address": "0x" + "2" * 40,
        "stages": [{"uuid": "public-1", "stage_type": "public_sale", "label": "Public",
                    "start_time": (now - timedelta(minutes=1)).isoformat(),
                    "end_time": (now + timedelta(hours=1)).isoformat(),
                    "price": "1000000000000000", "max_per_wallet": "2",
                    "price_currency_address": "0x" + "0" * 40}],
    }
    transaction = {"chain": chain, "to": SEADROP_V1_ADDRESS,
                   "data": "0x12345678", "value": str(10**15 * quantity)}
    fake = type("FakeOpenSea", (), {"get_drop": AsyncMock(return_value=detail),
                                    "build_mint": AsyncMock(return_value=(200, transaction))})()
    fake.mint_error=OpenSeaClient().mint_error
    monkeypatch.setattr("app.api.mint_plans.OpenSeaClient", lambda: fake)
    monkeypatch.setattr("app.services.mint_plans.OpenSeaClient", lambda: fake)
    monkeypatch.setattr("app.services.mint_plans.estimate_network_fee", AsyncMock(return_value=10**13))

    async def get_test_db():
        yield test_db
    app.dependency_overrides[get_db] = get_test_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/api/mint-plans", json={
                "url": "https://opensea.io/collection/example"})).status_code == 401
            login = await client.post("/api/auth/login", json={
                "username": "member", "password": "Member test password 123"})
            client.headers["Authorization"] = "Bearer " + login.json()["token"]
            imported = await client.post("/api/mint-plans", json={
                "url": "https://opensea.io/collection/example", "quantity": quantity})
            assert imported.status_code == 200, imported.text
            assert imported.json()["status"] == "ready_for_approval"
            assert imported.json()["chain"] == CHAINS[chain][1]
            assert imported.json()["mint_value_eth"] == ("0.001" if quantity == 1 else "0.002")
            assert imported.json()["quantity"] == quantity
            fake.build_mint.assert_awaited_once_with("example", wallet.address, quantity)
            assert imported.json()["estimated_network_fee_eth"] == "0.00001"
            assert imported.json()["estimated_total_eth"] == ("0.00101" if quantity == 1 else "0.00201")
            assert imported.json()["estimated_total_usdt"] == ("2.5250" if quantity == 1 else "5.0250")
            assert len((await client.get("/api/mint-plans")).json()) == 1
            assert (await client.get("/api/tasks/queue")).json()["tasks"] == []
            stored_plan = (await test_db.execute(select(MintPlan))).scalar_one()
            assert stored_plan.wallet_id == wallet.id
            stored_plan.last_checked_at = now - timedelta(minutes=1)
            await test_db.commit()

            fake.build_mint.return_value = (422, None)
            refreshed = await client.post(f"/api/mint-plans/{imported.json()['id']}/refresh")
            assert refreshed.status_code == 200, refreshed.text
            assert refreshed.json()["status"] == "not_ready"
            assert refreshed.json()["mint_value_eth"] is None
            stored_plan.last_checked_at = now - timedelta(minutes=1)
            await test_db.commit()
            fake.build_mint.side_effect = OpenSeaUnavailable("OpenSea is rate-limiting mint checks.", 503)
            retrying = await client.post(f"/api/mint-plans/{imported.json()['id']}/refresh")
            assert retrying.status_code == 200
            assert retrying.json()["status"] == "unverified"
            assert "rate-limiting" in retrying.json()["status_note"]
            assert retrying.json()["mint_value_eth"] is None
            admin_login = await client.post("/api/auth/login", json={
                "username": "admin", "password": "Admin test password 123"})
            client.headers["Authorization"] = "Bearer " + admin_login.json()["token"]
            assert (await client.get("/api/mint-plans")).json() == []
            assert (await client.post(f"/api/mint-plans/{imported.json()['id']}/refresh")).status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("chain", list(CHAINS))
async def test_drop_validation_accepts_supported_networks(chain):
    client = OpenSeaClient()
    client._key = AsyncMock(return_value="test-key")
    data = {"collection_slug": "example", "chain": chain, "drop_type": "seadrop_v1_erc721",
            "contract_address": "0x" + "2" * 40,
            "opensea_url": "https://opensea.io/collection/example", "stages": []}
    client._request = AsyncMock(return_value=(200, data))
    assert await client.get_drop("example") == data


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value,message", [
    ("chain", "unsupported", "network is not supported"),
    ("drop_type", "custom", "SeaDrop V1 ERC-721"),
    ("contract_address", "invalid", "inconsistent collection"),
])
async def test_drop_rejection_identifies_actual_reason(field, value, message):
    client = OpenSeaClient()
    client._key = AsyncMock(return_value="test-key")
    data = {"collection_slug": "example", "chain": "robinhood", "drop_type": "seadrop_v1_erc721",
            "contract_address": "0x" + "2" * 40,
            "opensea_url": "https://opensea.io/collection/example", "stages": []}
    data[field] = value
    client._request = AsyncMock(return_value=(200, data))
    with pytest.raises(OpenSeaUnavailable, match=message):
        await client.get_drop("example")


def test_robinhood_fee_rpc_never_falls_back_to_ethereum():
    assert CHAINS["robinhood"][0] == 4663
    assert chain_rpc("robinhood") == "https://rpc.mainnet.chain.robinhood.com"
    with pytest.raises(KeyError):
        chain_rpc("unsupported")


@pytest.mark.parametrize("value", ["-1", "0x123", "1.5", " 12", "1e18", None, 12, str(2**63)])
def test_mint_value_rejects_invalid_or_excessive_amounts(value):
    with pytest.raises(OpenSeaUnavailable):
        transaction_value_wei(value)


def test_free_mint_value_is_valid():
    assert transaction_value_wei("0") == 0


@pytest.mark.asyncio
async def test_real_decimal_mint_response_passes_contract_validation():
    client = OpenSeaClient()
    client._key = AsyncMock(return_value="test-key")
    tx = {"chain": "robinhood", "to": SEADROP_V1_ADDRESS,
          "data": "0x12345678", "value": "37000000000000"}
    client._request = AsyncMock(return_value=(200, tx))
    status, prepared = await client.build_mint("example", "0x" + "1" * 40)
    assert status == 200
    assert transaction_value_wei(prepared["value"]) == 37000000000000
    tx["to"] = "0x" + "2" * 40
    with pytest.raises(OpenSeaUnavailable, match="unexpected mint transaction"):
        await client.build_mint("example", "0x" + "1" * 40)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,message", [(429, "rate-limiting"), (403, "API access"),
    (400, "rejected the mint request"), (404, "could not find"), (503, "temporarily unavailable")])
async def test_mint_api_errors_have_specific_reasons(status, message):
    client = OpenSeaClient()
    client._key = AsyncMock(return_value="test-key")
    client._request = AsyncMock(return_value=(status, {"errors": ["private upstream detail"]}))
    with pytest.raises(OpenSeaUnavailable, match=message):
        await client.build_mint("example", "0x" + "1" * 40)
