"""Tests for isolated Signer Boundary policy enforcement."""

import pytest
from app.services.signer.base import SignerPolicy, SignerBoundaryException, SEADROP_V1_ADDRESS
from app.services.mint_executor import MintExecutor


@pytest.fixture
def base_policy():
    return SignerPolicy(
        chain_id=8453,
        authorized_minter="0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        authorized_recipient="0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        allowed_nft_contract="0x1234567890123456789012345678901234567890",
        allowed_seadrop_contract=SEADROP_V1_ADDRESS,
        authorized_quantity=2,
        max_price_per_token_wei=200_000_000_000_000,  # 0.0002 ETH
        max_fee_wei=100_000_000_000_000,             # 0.0001 ETH
        total_spend_cap_wei=500_000_000_000_000,     # 0.0005 ETH (400k mint + 100k fee)
        stage_name="Allowlist",
    )


def test_signer_policy_valid_tx(base_policy):
    """Verifies that a valid transaction matching authorized limits passes inspection."""
    executor = MintExecutor()
    calldata = executor.build_mint_public_calldata(
        nft_contract=base_policy.allowed_nft_contract,
        fee_recipient="0x0000000000000000000000000000000000000000",
        minter_if_not_payer=base_policy.authorized_recipient,
        quantity=2,
    )

    valid_tx = {
        "from": base_policy.authorized_minter,
        "to": base_policy.allowed_seadrop_contract,
        "value": 400_000_000_000_000,  # 2 * 0.0002 ETH
        "data": calldata,
        "nonce": 0,
        "gas": 50000,
        "maxFeePerGas": 1500000000,  # max fee = 50000 * 1.5 Gwei = 75,000,000,000,000 <= 100k
        "chainId": 8453,
    }

    result = base_policy.validate_transaction(valid_tx)
    assert result["verified"] is True
    assert result["function"] == "mintPublic"


def test_signer_policy_rejects_chain_mismatch(base_policy):
    """Rejects transaction if chainId does not match authorized network."""
    executor = MintExecutor()
    calldata = executor.build_mint_public_calldata(
        nft_contract=base_policy.allowed_nft_contract,
        fee_recipient="0x0000000000000000000000000000000000000000",
        minter_if_not_payer=base_policy.authorized_recipient,
        quantity=2,
    )
    bad_tx = {
        "to": base_policy.allowed_seadrop_contract,
        "value": 400_000_000_000_000,
        "data": calldata,
        "gas": 50000,
        "maxFeePerGas": 1000000000,
        "chainId": 1,  # Chain mismatch! Expected 8453
    }
    with pytest.raises(SignerBoundaryException, match="Chain ID mismatch"):
        base_policy.validate_transaction(bad_tx)


def test_signer_policy_rejects_target_mismatch(base_policy):
    """Rejects transaction if 'to' address is not the canonical SeaDrop contract."""
    executor = MintExecutor()
    calldata = executor.build_mint_public_calldata(
        nft_contract=base_policy.allowed_nft_contract,
        fee_recipient="0x0000000000000000000000000000000000000000",
        minter_if_not_payer=base_policy.authorized_recipient,
        quantity=2,
    )
    bad_tx = {
        "to": "0x9999999999999999999999999999999999999999",  # Arbitrary contract!
        "value": 400_000_000_000_000,
        "data": calldata,
        "gas": 50000,
        "maxFeePerGas": 1000000000,
        "chainId": 8453,
    }
    with pytest.raises(SignerBoundaryException, match="Target address mismatch"):
        base_policy.validate_transaction(bad_tx)


def test_signer_policy_rejects_excessive_value(base_policy):
    """Rejects transaction if mint value exceeds authorized cap."""
    executor = MintExecutor()
    calldata = executor.build_mint_public_calldata(
        nft_contract=base_policy.allowed_nft_contract,
        fee_recipient="0x0000000000000000000000000000000000000000",
        minter_if_not_payer=base_policy.authorized_recipient,
        quantity=2,
    )
    bad_tx = {
        "to": base_policy.allowed_seadrop_contract,
        "value": 900_000_000_000_000,  # Exceeds authorized mint spend cap (400k)
        "data": calldata,
        "gas": 50000,
        "maxFeePerGas": 1000000000,
        "chainId": 8453,
    }
    with pytest.raises(SignerBoundaryException, match="exceeds authorized mint spend cap"):
        base_policy.validate_transaction(bad_tx)


def test_signer_policy_rejects_calldata_tampering(base_policy):
    """Rejects transaction if calldata specifies a different contract or higher quantity."""
    executor = MintExecutor()
    # Build calldata for 5 NFTs instead of authorized 2
    tampered_calldata = executor.build_mint_public_calldata(
        nft_contract=base_policy.allowed_nft_contract,
        fee_recipient="0x0000000000000000000000000000000000000000",
        minter_if_not_payer=base_policy.authorized_recipient,
        quantity=5,  # Tampered quantity!
    )
    bad_tx = {
        "to": base_policy.allowed_seadrop_contract,
        "value": 400_000_000_000_000,
        "data": tampered_calldata,
        "gas": 50000,
        "maxFeePerGas": 1000000000,
        "chainId": 8453,
    }
    with pytest.raises(SignerBoundaryException, match="Calldata quantity .* does not match authorized"):
        base_policy.validate_transaction(bad_tx)
