"""Mint Executor: coordinates nonces, calldata building, signing, broadcasting, and recovery."""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from eth_utils import to_checksum_address
from web3 import AsyncWeb3
from app.services.signer.base import SignerPolicy, SignerBoundaryException, SEADROP_V1_ADDRESS, MINT_PUBLIC_SELECTOR
from app.services.signer.mock_signer import MockSigner
from app.services.signer.local_signer import LocalServerSigner
from app.config import settings


class ExecutionException(Exception):
    """Raised on execution errors."""
    pass


class MintExecutor:
    """Manages transaction preparation, signing, submission, and confirmation tracking."""

    def __init__(self, signer=None):
        if signer:
            self.signer = signer
        elif settings.SIGNER_MODE == "isolated_server_signer" and settings.SIGNER_PRIVATE_KEY:
            self.signer = LocalServerSigner(settings.SIGNER_PRIVATE_KEY)
        else:
            self.signer = MockSigner()

    def build_mint_public_calldata(
        self,
        nft_contract: str,
        fee_recipient: str,
        minter_if_not_payer: str,
        quantity: int,
    ) -> str:
        """Constructs ABI-encoded calldata for SeaDrop mintPublic."""
        from eth_abi import encode
        selector = f"0x{MINT_PUBLIC_SELECTOR}"
        encoded_args = encode(
            ["address", "address", "address", "uint256"],
            [
                to_checksum_address(nft_contract),
                to_checksum_address(fee_recipient),
                to_checksum_address(minter_if_not_payer),
                quantity,
            ]
        )
        return selector + encoded_args.hex()

    def prepare_and_sign(
        self,
        policy: SignerPolicy,
        from_address: str,
        nonce: int,
        calldata: str,
        gas_limit: int = 150000,
        max_fee_per_gas_wei: int = 2000000000,  # 2 Gwei
    ) -> Dict[str, Any]:
        """Prepares the transaction payload, validates against policy, and signs it."""
        value_wei = policy.authorized_quantity * policy.max_price_per_token_wei

        tx_dict = {
            "from": to_checksum_address(from_address),
            "to": to_checksum_address(policy.allowed_seadrop_contract),
            "value": value_wei,
            "data": calldata,
            "nonce": nonce,
            "gas": gas_limit,
            "maxFeePerGas": max_fee_per_gas_wei,
            "maxPriorityFeePerGas": 1000000000,  # 1 Gwei
            "chainId": policy.chain_id,
            "type": 2,  # EIP-1559
        }

        # Sign transaction (will raise SignerBoundaryException if any check fails)
        signed_result = self.signer.sign_transaction(tx_dict, policy)
        return {
            "tx_dict": tx_dict,
            "transaction_hash": signed_result["transaction_hash"],
            "raw_transaction": signed_result.get("raw_transaction"),
            "is_simulated": signed_result.get("is_simulated", False),
        }

    async def broadcast_transaction(self, raw_tx_hex: str, chain: str) -> str:
        """Broadcasts signed raw transaction to RPC network."""
        # For simulated / demo mode or test without live RPC:
        if raw_tx_hex.startswith("0x") and len(raw_tx_hex) < 100:
            # Simulated hash
            return raw_tx_hex

        rpc_url = settings.RPC_BASE if chain.lower() == "base" else settings.RPC_ETHEREUM
        w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))
        
        try:
            tx_bytes = bytes.fromhex(raw_tx_hex.replace("0x", ""))
            tx_hash = await w3.eth.send_raw_transaction(tx_bytes)
            return tx_hash.hex()
        except Exception as e:
            raise ExecutionException(f"RPC broadcast error on {chain}: {str(e)}")

    async def reconcile_transaction(self, tx_hash: str, chain: str) -> Dict[str, Any]:
        """Checks status of a broadcasted transaction to handle crash recovery and reorgs."""
        # If simulated hash
        if tx_hash.startswith("0x") and len(tx_hash) == 66:
            # Deterministic simulation response
            return {
                "status": "confirmed",
                "gas_used": 85000,
                "effective_gas_price": 1500000000,
                "total_fee_wei": 85000 * 1500000000,
                "block_number": 19500000,
            }

        rpc_url = settings.RPC_BASE if chain.lower() == "base" else settings.RPC_ETHEREUM
        w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))
        
        try:
            receipt = await w3.eth.get_transaction_receipt(tx_hash)
            if receipt is None:
                return {"status": "pending"}

            success = receipt.get("status") == 1
            gas_used = receipt.get("gasUsed", 0)
            gas_price = receipt.get("effectiveGasPrice", 0)
            fee_wei = gas_used * gas_price

            return {
                "status": "confirmed" if success else "reverted",
                "gas_used": gas_used,
                "effective_gas_price": gas_price,
                "total_fee_wei": fee_wei,
                "block_number": receipt.get("blockNumber"),
            }
        except Exception as e:
            return {"status": "unknown", "error": str(e)}
