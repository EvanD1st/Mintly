"""Local EVM Signer with strictly enforced policy boundary."""

from typing import Dict, Any
from eth_account import Account
from app.services.signer.base import SignerPolicy, SignerBoundaryException


class LocalServerSigner:
    """Signs transactions using an operator key, enforcing policy before signing."""

    def __init__(self, private_key_hex: str):
        if not private_key_hex:
            raise ValueError("Signer private key is required.")
        # Ensure 0x prefix is handled
        key = private_key_hex if private_key_hex.startswith("0x") else f"0x{private_key_hex}"
        self.account = Account.from_key(key)
        self.address = self.account.address

    def sign_transaction(self, tx_dict: Dict[str, Any], policy: SignerPolicy) -> Dict[str, Any]:
        """Validates policy and cryptographically signs the transaction."""
        # 1. Enforce boundary policy
        policy.validate_transaction(tx_dict)

        # 2. Verify from address matches signer account
        from_address = tx_dict.get("from")
        if from_address and from_address.lower() != self.address.lower():
            raise SignerBoundaryException(
                f"Signer account {self.address} does not match transaction from address {from_address}."
            )

        # 3. Sign transaction
        signed = self.account.sign_transaction(tx_dict)
        return {
            "raw_transaction": signed.raw_transaction.hex(),
            "transaction_hash": signed.hash.hex(),
            "r": signed.r,
            "s": signed.s,
            "v": signed.v,
        }
