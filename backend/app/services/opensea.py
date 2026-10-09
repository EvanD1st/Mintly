"""Narrow, read-oriented OpenSea Drops integration for linked MetaMask wallets.

An instant API key is free and expires after seven days. It is kept on a
server-only volume and never returned to a client or included in errors.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from eth_utils import is_address, to_checksum_address
from web3 import AsyncWeb3

from app.config import settings
from app.services.signer.base import SEADROP_V1_ADDRESS

API_ROOT = "https://api.opensea.io/api/v2"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
HEX_RE = re.compile(r"^0x[0-9a-fA-F]*$")
DECIMAL_WEI_RE = re.compile(r"^[0-9]{1,19}$")
CHAINS = {"ethereum": (1, "Ethereum"), "base": (8453, "Base"),
          "robinhood": (4663, "Robinhood Chain"),
          "arbitrum": (42161, "Arbitrum One"), "optimism": (10, "Optimism")}


def chain_rpc(chain: str) -> str:
    return {"ethereum": settings.RPC_ETHEREUM, "base": settings.RPC_BASE,
            "robinhood": settings.RPC_ROBINHOOD, "arbitrum": settings.RPC_ARBITRUM,
            "optimism": settings.RPC_OPTIMISM}[chain]


def transaction_value_wei(value: str) -> int:
    """OpenSea's mint API specifies decimal wei, not hexadecimal."""
    if not isinstance(value, str) or not DECIMAL_WEI_RE.fullmatch(value):
        raise OpenSeaUnavailable("OpenSea returned an invalid mint value.")
    amount = int(value, 10)
    if amount >= 2**63:
        raise OpenSeaUnavailable("OpenSea returned a mint value outside supported limits.")
    return amount


class OpenSeaUnavailable(Exception):
    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


def collection_slug(url: str) -> str:
    """Accept only canonical OpenSea collection pages, never arbitrary URLs."""
    try:
        parsed = urlparse(url.strip())
        port = parsed.port
    except ValueError as error:
        raise OpenSeaUnavailable("Invalid OpenSea drop URL.", 400) from error
    parts = parsed.path.rstrip("/").split("/")
    if (parsed.scheme != "https" or parsed.hostname != "opensea.io" or port
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or len(parts) not in (3, 4) or parts[1] != "collection"
            or (len(parts) == 4 and parts[3] != "drops")
            or not SLUG_RE.fullmatch(parts[2])):
        raise OpenSeaUnavailable("Use a direct https://opensea.io/collection/<slug> drop link.", 400)
    return parts[2]


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as error:
        raise OpenSeaUnavailable("OpenSea returned a stage with an invalid time.") from error


def stage_schedule(drop: dict) -> list[dict]:
    stages = []
    for raw in drop.get("stages", []):
        try:
            start = parse_utc(raw["start_time"])
            end = parse_utc(raw["end_time"])
            price = int(raw["price"]) if raw.get("price") is not None else None
            limit = int(raw["max_per_wallet"])
            currency = str(raw.get("price_currency_address") or "").lower()
            if (end <= start or price is not None and not 0 <= price < 2**63
                    or limit < 0 or currency != "0x" + "0" * 40):
                raise ValueError("invalid stage range")
            stages.append({
                "uuid": str(raw["uuid"]),
                "name": str(raw.get("label") or raw["stage_type"])[:80],
                "type": str(raw["stage_type"]),
                "starts_at": start,
                "ends_at": end,
                "price_wei": price,
                "max_per_wallet": limit,
            })
        except (KeyError, TypeError, ValueError) as error:
            raise OpenSeaUnavailable("OpenSea returned incomplete drop stages.") from error
    return sorted(stages, key=lambda stage: stage["starts_at"])


class OpenSeaClient:
    async def _request(self, method: str, path: str, *, payload: dict | None = None,
                       key: str | None = None) -> tuple[int, dict]:
        import time
        from app.services.mint_diagnostics import record_http
        started=time.monotonic();status=None;retry_after=None;failure=None
        headers = {"Accept": "application/json"}
        if key:headers["X-API-KEY"] = key
        timeout = aiohttp.ClientTimeout(total=12)
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.request(method, f"{API_ROOT}{path}", headers=headers,
                                           json=payload, allow_redirects=False) as response:
                    status=response.status;retry_after=response.headers.get('Retry-After')
                    if 300 <= response.status < 400:
                        failure='redirect'
                        raise OpenSeaUnavailable("OpenSea unexpectedly redirected a request.")
                    if response.content_length and response.content_length > 256 * 1024:
                        failure='response_too_large'
                        raise OpenSeaUnavailable("OpenSea response was too large.")
                    body = await response.content.read(256 * 1024 + 1)
                    if len(body) > 256 * 1024:
                        failure='response_too_large'
                        raise OpenSeaUnavailable("OpenSea response was too large.")
                    data = json.loads(body) if body else {}
                    if not isinstance(data, dict):
                        failure='invalid_response'
                        raise OpenSeaUnavailable("OpenSea returned an unexpected response.")
                    return response.status, data
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            failure='timeout' if isinstance(error,TimeoutError) else 'invalid_response' if isinstance(error,ValueError) else 'network_error'
            raise OpenSeaUnavailable("OpenSea is temporarily unavailable.") from error
        finally:
            try:record_http(method,path,status,retry_after,started,failure)
            except Exception:pass  # Diagnostic logging never changes the HTTP outcome.

    async def _key(self) -> str:
        path = Path(settings.OPENSEA_KEY_FILE)
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if parse_utc(saved["expires_at"]) > datetime.now(timezone.utc) + timedelta(hours=1):
                key = saved["api_key"]
                if isinstance(key, str) and len(key) >= 16:
                    return key
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, OpenSeaUnavailable):
            pass
        status, fresh = await self._request("POST", "/auth/keys")
        key = fresh.get("api_key")
        if status != 201 or not isinstance(key, str) or len(key) < 16:
            raise OpenSeaUnavailable("Could not obtain a free OpenSea API key.")
        expiry = parse_utc(fresh.get("expires_at"))
        if expiry <= datetime.now(timezone.utc) + timedelta(hours=1):
            raise OpenSeaUnavailable("OpenSea returned an expired API key.")
        path.parent.mkdir(parents=True, exist_ok=True)
        mask = os.umask(0o077)
        temporary = None
        try:
            fd, name = tempfile.mkstemp(prefix=".opensea-", dir=path.parent)
            temporary = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"api_key": key, "expires_at": fresh["expires_at"]}, stream)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except OSError as error:
            raise OpenSeaUnavailable("Could not save the OpenSea API key securely.") from error
        finally:
            os.umask(mask)
            if temporary and temporary.exists():
                temporary.unlink()
        return key

    async def get_drop(self, slug: str) -> dict:
        if not SLUG_RE.fullmatch(slug):
            raise OpenSeaUnavailable("Invalid OpenSea collection slug.", 400)
        status, data = await self._request("GET", f"/drops/{slug}", key=await self._key())
        if status == 404:
            raise OpenSeaUnavailable("This collection has no OpenSea drop.", 404)
        if status != 200:
            raise OpenSeaUnavailable("OpenSea could not verify this drop.")
        if data.get("chain") not in CHAINS:
            raise OpenSeaUnavailable(
                "This drop's network is not supported yet. Supported networks: Ethereum, Base, Robinhood Chain, Arbitrum One, Optimism.", 400)
        if data.get("drop_type") != "seadrop_v1_erc721":
            raise OpenSeaUnavailable("This collection does not use the supported SeaDrop V1 ERC-721 mint flow.", 400)
        if (data.get("collection_slug") != slug or not is_address(data.get("contract_address", ""))
                or data.get("opensea_url") != f"https://opensea.io/collection/{slug}"):
            raise OpenSeaUnavailable("OpenSea returned inconsistent collection details; mint preparation was stopped.")
        stage_schedule(data)
        return data

    async def collection_for_contract(self, chain_id: int, contract: str) -> str:
        chains = {cid: name for name, (cid, _) in CHAINS.items()}
        chain = chains.get(chain_id)
        if not chain or not is_address(contract):
            raise OpenSeaUnavailable('Whitelist discovery is unavailable for this contract or network.', 409)
        status, data = await self._request('GET', f'/chain/{chain}/contract/{to_checksum_address(contract)}', key=await self._key())
        slug = data.get('collection')
        if (status != 200 or data.get('chain') != chain or data.get('address', '').lower() != contract.lower()
                or data.get('contract_standard') != 'erc721' or not isinstance(slug, str) or not SLUG_RE.fullmatch(slug)):
            raise OpenSeaUnavailable('Whitelist collection metadata could not be verified.', 409 if status in (400,404) else 503)
        detail = await self.get_drop(slug)
        if detail['chain'] != chain or detail['contract_address'].lower() != contract.lower():
            raise OpenSeaUnavailable('Whitelist drop does not match the followed NFT.', 409)
        return slug

    async def build_mint(self, slug: str, wallet_address: str, quantity: int = 1) -> tuple[int, dict | None]:
        """Read-only preparation: OpenSea returns calldata; this never signs or sends it."""
        if not SLUG_RE.fullmatch(slug) or not is_address(wallet_address) or type(quantity) is not int or not 1 <= quantity <= 100:
            raise OpenSeaUnavailable("Invalid drop or wallet address.", 400)
        status, data = await self._request("POST", f"/drops/{slug}/mint",
                                           payload={"minter": to_checksum_address(wallet_address),
                                                    "quantity": quantity}, key=await self._key())
        if status == 200:
            target, calldata, value = data.get("to"), data.get("data"), data.get("value")
            if (not is_address(target or "") or target.lower() != SEADROP_V1_ADDRESS.lower()
                    or not isinstance(calldata, str) or len(calldata) < 10
                    or not HEX_RE.fullmatch(calldata) or len(calldata) % 2):
                raise OpenSeaUnavailable("OpenSea returned an unexpected mint transaction.")
            transaction_value_wei(value)
            return status, data
        if status in (409, 422):
            return status, None
        if status == 429:
            raise OpenSeaUnavailable("OpenSea is rate-limiting mint checks. Your wallet's eligibility has not been determined; Mintly will retry later.", 503)
        if status in (401, 403):
            raise OpenSeaUnavailable("OpenSea denied the server's mint API access. This is not a wallet eligibility result.", 503)
        if status == 404:
            raise OpenSeaUnavailable("OpenSea could not find this mint drop. Check the collection link.", 404)
        if status == 400:
            raise OpenSeaUnavailable("OpenSea rejected the mint request. The drop or wallet is not supported by this mint endpoint.", 400)
        if status >= 500:
            raise OpenSeaUnavailable("OpenSea's mint service is temporarily unavailable. Mintly will retry later.", 503)
        raise OpenSeaUnavailable("OpenSea could not prepare this wallet's mint.")


async def estimate_network_fee(transaction: dict, wallet_address: str, chain: str) -> int | None:
    """A snapshot estimate; MetaMask shows the actual fee before signing."""
    if chain not in CHAINS:
        return None
    rpc = chain_rpc(chain)
    provider = AsyncWeb3.AsyncHTTPProvider(rpc, request_kwargs={"timeout": 8})
    web3 = AsyncWeb3(provider)
    try:
        if await web3.eth.chain_id != CHAINS[chain][0]:
            return None
        tx = {"from": to_checksum_address(wallet_address),
              "to": to_checksum_address(transaction["to"]),
              "data": transaction["data"], "value": transaction_value_wei(transaction["value"])}
        if CHAINS[chain][0] == 4663:
            from app.services.automatic_fees import quote_gas
            gas_units, gas_price = await quote_gas(web3, tx, 4663)
            return gas_units * gas_price
        gas_units = await web3.eth.estimate_gas(tx)
        gas_price = await web3.eth.gas_price
        if CHAINS[chain][0] == 8453:
            from app.services.automatic_fees import maximum_fee
            return await maximum_fee(web3, tx, 8453, gas_units, gas_price)
        return int(gas_units) * int(gas_price)
    except Exception:
        return None
    finally:
        await provider.disconnect()
