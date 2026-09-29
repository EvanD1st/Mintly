"""Mock / Demo Signer that verifies policy and generates deterministic signatures."""

import hashlib
from typing import Dict, Any
from app.services.signer.base import SignerPolicy, SignerBoundaryException


class MockSigner:
    """Simulated signer for demo and testing; validates the same boundary policies."""

    def __init__(self, address: str = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"):
        self.address = address

    def sign_transaction(self, tx_dict: Dict[str, Any], policy: SignerPolicy) -> Dict[str, Any]:
        """Validates policy and returns a simulated signature and transaction hash."""
        # Enforce same boundary validation
        policy.validate_transaction(tx_dict)

        serialized = f"{tx_dict.get('to')}:{tx_dict.get('value')}:{tx_dict.get('data')}:{tx_dict.get('nonce')}"
        tx_hash = "0x" + hashlib.sha256(serialized.encode()).hexdigest()
        
        return {
            "raw_transaction": "0x" + hashlib.sha256(tx_hash.encode()).hexdigest(),
            "transaction_hash": tx_hash,
            "is_simulated": True,
        }
