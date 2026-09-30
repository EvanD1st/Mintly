"""Isolated EVM Signer Boundary and Policy Validator."""

from decimal import Decimal
from typing import Dict, Any, Optional
from eth_utils import to_checksum_address, function_signature_to_4byte_selector
from eth_abi import decode

# Canonical SeaDrop V1 deployment address
SEADROP_V1_ADDRESS = "0x00005EA00Ac477B1030CE78506496e8C2dE24bf5"

# SeaDrop V1 Function Selectors
# mintPublic(address nftContract, address feeRecipient, address minterIfNotPayer, uint256 quantity)
MINT_PUBLIC_SIG = "mintPublic(address,address,address,uint256)"
MINT_PUBLIC_SELECTOR = function_signature_to_4byte_selector(MINT_PUBLIC_SIG).hex()

ALLOWED_SELECTORS = {
    f"0x{MINT_PUBLIC_SELECTOR}": "mintPublic",
}


class SignerBoundaryException(Exception):
    """Raised when an execution request violates signer security policy."""
    pass


class SignerPolicy:
    """Enforces immutable authorization limits at the cryptographic signer boundary."""

    def __init__(
        self,
        chain_id: int,
        authorized_minter: str,
        authorized_recipient: str,
        allowed_nft_contract: str,
        allowed_seadrop_contract: str,
        authorized_quantity: int,
        max_price_per_token_wei: int,
        max_fee_wei: int,
        total_spend_cap_wei: int,
        stage_name: str,
    ):
        self.chain_id = chain_id
        self.authorized_minter = to_checksum_address(authorized_minter)
        self.authorized_recipient = to_checksum_address(authorized_recipient)
        self.allowed_nft_contract = to_checksum_address(allowed_nft_contract)
        self.allowed_seadrop_contract = to_checksum_address(allowed_seadrop_contract)
        self.authorized_quantity = authorized_quantity
        self.max_price_per_token_wei = max_price_per_token_wei
        self.max_fee_wei = max_fee_wei
        self.total_spend_cap_wei = total_spend_cap_wei
        self.stage_name = stage_name

    def validate_transaction(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        """Validates all fields of a raw transaction before signing.
        
        Fails closed on any mismatch.
        """
        # 1. Chain ID Verification
        tx_chain_id = tx.get("chainId")
        if tx_chain_id != self.chain_id:
            raise SignerBoundaryException(
                f"Chain ID mismatch: transaction has {tx_chain_id}, authorized for {self.chain_id}."
            )

        if self.stage_name.lower() not in ("public", "public stage"):
            raise SignerBoundaryException("Only a verified public stage may use mintPublic calldata.")
        if to_checksum_address(tx.get("from", "")) != self.authorized_minter:
            raise SignerBoundaryException("Transaction sender does not match authorized minter.")

        # 2. Target Contract Verification (must be canonical SeaDrop)
        to_address = to_checksum_address(tx.get("to", ""))
        if to_address != self.allowed_seadrop_contract:
            raise SignerBoundaryException(
                f"Target address mismatch: to={to_address}, expected SeaDrop={self.allowed_seadrop_contract}."
            )

        # 3. Value and Fee Caps
        value_wei = int(tx.get("value", 0))
        max_mint_cost = self.authorized_quantity * self.max_price_per_token_wei
        if value_wei > max_mint_cost:
            raise SignerBoundaryException(
                f"Transaction value {value_wei} wei exceeds authorized mint spend cap {max_mint_cost} wei."
            )

        gas_limit = int(tx.get("gas", 0))
        gas_price = int(tx.get("maxFeePerGas", tx.get("gasPrice", 0)))
        max_tx_fee = gas_limit * gas_price

        if max_tx_fee > self.max_fee_wei:
            raise SignerBoundaryException(
                f"Max transaction gas fee {max_tx_fee} wei exceeds authorized fee cap {self.max_fee_wei} wei."
            )

        total_potential_spend = value_wei + max_tx_fee
        if total_potential_spend > self.total_spend_cap_wei:
            raise SignerBoundaryException(
                f"Total spend {total_potential_spend} wei exceeds hard cap {self.total_spend_cap_wei} wei."
            )

        # 4. Calldata Decoding and Inspection
        data = tx.get("data", "")
        if not data or len(data) < 10:
            raise SignerBoundaryException("Missing or invalid calldata in mint transaction.")

        selector = data[:10].lower()
        if selector not in ALLOWED_SELECTORS:
            raise SignerBoundaryException(
                f"Unsupported function selector: {selector}. Only SeaDrop minting functions are permitted."
            )

        # Decode mintPublic calldata
        if selector == f"0x{MINT_PUBLIC_SELECTOR}":
            try:
                # (address nftContract, address feeRecipient, address minterIfNotPayer, uint256 quantity)
                raw_bytes = bytes.fromhex(data[10:])
                decoded = decode(["address", "address", "address", "uint256"], raw_bytes)
                nft_contract, fee_recipient, minter_if_not_payer, quantity = decoded
                
                nft_contract_cs = to_checksum_address(nft_contract)
                if nft_contract_cs != self.allowed_nft_contract:
                    raise SignerBoundaryException(
                        f"Calldata NFT contract {nft_contract_cs} does not match authorized contract {self.allowed_nft_contract}."
                    )

                if quantity != self.authorized_quantity:
                    raise SignerBoundaryException(
                        f"Calldata quantity {quantity} does not match authorized quantity {self.authorized_quantity}."
                    )

                recipient_cs = to_checksum_address(minter_if_not_payer)
                if recipient_cs != self.authorized_recipient:
                    raise SignerBoundaryException(
                        f"Calldata recipient {recipient_cs} does not match authorized recipient {self.authorized_recipient}."
                    )
                if fee_recipient != "0x0000000000000000000000000000000000000000":
                    raise SignerBoundaryException("Unexpected fee recipient in calldata.")

            except Exception as e:
                raise SignerBoundaryException(f"Failed to decode or validate SeaDrop calldata: {str(e)}")

        return {
            "verified": True,
            "selector": selector,
            "function": ALLOWED_SELECTORS[selector],
            "value_wei": value_wei,
            "max_fee_wei": max_tx_fee,
        }
