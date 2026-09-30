"""Account roles, session revocation, and MetaMask signature pairing."""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.main import app


@pytest.fixture(autouse=True)
def override_db(test_db):
    async def get_test_db():
        yield test_db
    app.dependency_overrides[get_db] = get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)


async def signed_in(client, name: str, password: str):
    result = await client.post("/api/auth/login", json={"username": name, "password": password})
    assert result.status_code == 200, result.text
    return {"Authorization": "Bearer " + result.json()["token"]}


@pytest.mark.asyncio
async def test_admin_provisioning_forced_change_and_reset_revocation(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        member_headers = await signed_in(client, "member", "Member test password 123")
        assert (await client.get("/api/admin/users", headers=member_headers)).status_code == 403
        admin_headers = await signed_in(client, "admin", "Admin test password 123")
        created = await client.post("/api/admin/users", headers=admin_headers, json={
            "username": "alice", "admin_password": "Admin test password 123",
        })
        assert created.status_code == 200, created.text
        user_id = created.json()["user"]["id"]
        temporary = created.json()["temporary_password"]
        alice = await signed_in(client, "alice", temporary)
        assert (await client.get("/api/drops", headers=alice)).status_code == 403
        changed = await client.post("/api/auth/change-password", headers=alice, json={
            "current_password": temporary, "new_password": "Alice permanent password 123",
        })
        assert changed.status_code == 200, changed.text
        assert (await client.get("/api/auth/me", headers=alice)).status_code == 401
        alice = await signed_in(client, "alice", "Alice permanent password 123")
        assert (await client.get("/api/drops", headers=alice)).status_code == 200
        reset = await client.post(f"/api/admin/users/{user_id}/reset-password", headers=admin_headers,
                                  json={"admin_password": "Admin test password 123"})
        assert reset.status_code == 200, reset.text
        assert (await client.get("/api/auth/me", headers=alice)).status_code == 401
        assert (await client.post("/api/auth/login", json={
            "username": "alice", "password": "Alice permanent password 123",
        })).status_code == 401


@pytest.mark.asyncio
async def test_wallet_pairing_requires_valid_signature_and_code_is_one_use(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        member_headers = await signed_in(client, "member", "Member test password 123")
        pairing = await client.post("/api/wallets/pairings", headers=member_headers)
        assert pairing.status_code == 200, pairing.text
        code = pairing.json()["code"]
        wallet = Account.create()
        other = Account.create()
        challenge = await client.post("/api/wallet-link/challenge", json={
            "code": code, "address": wallet.address,
        })
        assert challenge.status_code == 200, challenge.text
        message = challenge.json()["message"]
        assert "mintly.duckdns.org" in message
        bad = Account.sign_message(encode_defunct(text=message), other.key).signature.hex()
        assert (await client.post("/api/wallet-link/complete", json={
            "code": code, "address": wallet.address, "signature": bad,
        })).status_code == 400
        signature = Account.sign_message(encode_defunct(text=message), wallet.key).signature.hex()
        linked = await client.post("/api/wallet-link/complete", json={
            "code": code, "address": wallet.address, "signature": signature,
        })
        assert linked.status_code == 200, linked.text
        assert (await client.post("/api/wallet-link/complete", json={
            "code": code, "address": wallet.address, "signature": signature,
        })).status_code == 404
        wallets = await client.get("/api/wallets", headers=member_headers)
        assert wallets.status_code == 200
        assert [item["address"] for item in wallets.json()] == [wallet.address]
        admin_headers = await signed_in(client, "admin", "Admin test password 123")
        assert (await client.get("/api/wallets", headers=admin_headers)).json() == []
        unlinked = await client.delete(f"/api/wallets/{wallets.json()[0]['id']}", headers=member_headers)
        assert unlinked.status_code == 200, unlinked.text
        assert (await client.get("/api/wallets", headers=member_headers)).json() == []
