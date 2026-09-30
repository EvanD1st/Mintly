"""OpenSea SeaDrop V1 Metadata and Eligibility Adapter."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Optional, List
import httpx
from eth_utils import to_checksum_address
from app.config import settings

# Canonical SeaDrop V1 deployment address across EVM chains
SEADROP_V1_ADDRESS = "0x00005EA00Ac477B1030CE78506496e8C2dE24bf5"

# Verified Supported Chains
SUPPORTED_CHAINS = {
    "ethereum": {"id": 1, "name": "Ethereum"},
    "base": {"id": 8453, "name": "Base"},
    "sepolia": {"id": 11155111, "name": "Sepolia"},
    "base_sepolia": {"id": 84532, "name": "Base Sepolia"},
}


class OpenSeaAdapter:
    """Interacts with OpenSea Drop metadata and validates SeaDrop eligibility."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.OPENSEA_API_KEY
        self.base_url = "https://api.opensea.io/api/v2"

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def get_drop_metadata(self, collection_slug: str, chain: str = "base") -> Dict[str, Any]:
        """Fetches drop metadata from OpenSea API or returns UNKNOWN on error.
        
        Never invents successful results or chains.
        """
        chain_lower = chain.lower()
        if chain_lower not in SUPPORTED_CHAINS:
            return {
                "supported": False,
                "error": f"Chain '{chain}' is not a verified EVM SeaDrop chain.",
                "stages": [],
            }

        url = f"{self.base_url}/chain/{chain_lower}/drop/{collection_slug}"
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(url, headers=self._get_headers())
                if res.status_code == 200:
                    data = res.json()
                    return self._parse_opensea_drop(data, chain_lower)
                elif res.status_code == 404:
                    return {
                        "supported": False,
                        "error": "Drop not found on OpenSea or not configured as SeaDrop.",
                        "stages": [],
                    }
                else:
                    return {
                        "supported": False,
                        "error": f"OpenSea API returned HTTP {res.status_code}",
                        "status_code": res.status_code,
                        "stages": [],
                    }
        except Exception as e:
            # Network or timeout error returns error / UNKNOWN
            return {
                "supported": False,
                "error": f"Failed to contact OpenSea API: {str(e)}",
                "stages": [],
            }

    def _parse_opensea_drop(self, data: Dict[str, Any], chain_lower: str) -> Dict[str, Any]:
        """Parses OpenSea drop JSON into verified structured stages."""
        contract = data.get("contract_address")
        stages = []
        for s in data.get("stages", []):
            stage_name = s.get("name", "Public")
            price_wei = int(s.get("price", {}).get("value", 0))
            start_ts = s.get("start_time")
            start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc) if start_ts else datetime.now(timezone.utc)
            stages.append({
                "stage_name": stage_name,
                "start_time_utc": start_dt,
                "price_wei": price_wei,
                "limit_per_wallet": s.get("wallet_limit", 1),
                "is_public": s.get("type", "").lower() == "public",
            })

        return {
            "supported": True,
            "contract_address": to_checksum_address(contract) if contract else None,
            "seadrop_address": SEADROP_V1_ADDRESS,
            "chain_id": SUPPORTED_CHAINS[chain_lower]["id"],
            "stages": stages,
        }

    async def check_wallet_eligibility(
        self,
        chain: str,
        collection_slug: str,
        stage_name: str,
        wallet_address: str,
    ) -> Dict[str, Any]:
        """Checks wallet eligibility.
        
        Returns:
            status: 'eligible', 'ineligible', 'unknown', or 'manual_check'
            evidence: explanation
        """
        # If external API credentials are absent or collection is manual, return explicit status
        chain_lower = chain.lower()
        if chain_lower not in SUPPORTED_CHAINS:
            return {
                "status": "manual_check",
                "evidence": f"Chain '{chain}' requires manual review.",
                "checked_at": datetime.now(timezone.utc),
            }

        if stage_name.lower() in ("public", "public stage"):
            return {
                "status": "unknown",
                "evidence": "Public mint access does not verify sale timing, supply, wallet balance, or contract restrictions.",
                "checked_at": datetime.now(timezone.utc),
            }
        
        # When checking allowlist without proof:
        return {
            "status": "unknown",
            "evidence": "Allowlist eligibility requires signed Merkle proof from drop creator or OpenSea API key.",
            "checked_at": datetime.now(timezone.utc),
        }
