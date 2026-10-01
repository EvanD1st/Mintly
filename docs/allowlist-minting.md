# Automatic allowlist minting

Implemented locally 2026-10-01 for SeaDrop V1 ERC-721 native-ETH mints using `mintAllowList` and `mintSigned`. The canonical SeaDrop contract is required. Token-holder-gated calls, custom mint contracts and ERC-1155 drops remain rejected.

## User flow

Import the OpenSea link with the original linked wallet and chosen quantity. When OpenSea supplies that wallet's eligible transaction, Mintly identifies the exact presale by its price and start/end times. The quote button is available for verified active presales as well as public mints. The backend validates the transaction and on-chain eligibility before offering approval.

Approve the exact mint when arming. Direct-wallet gas requires the exact delegation and gas-capped UserOperation signatures described in [direct wallet gas](direct-wallet-gas-investigation.md). Mintly then submits the approved operation without another wallet prompt. NFT ownership stays at the original wallet; a separate Mintly mint wallet is not used. Legacy gas-reimbursement permissions also use the same presale validation.

## Checks before authorization and submission

- Canonical target, supported selector, exact original wallet, NFT contract, quantity and price; only canonical ABI encoding and the known OpenSea attribution suffix are accepted.
- Exact eligible stage instead of assuming the first overlapping stage is the user's stage. Ambiguous stage metadata is rejected.
- Merkle proofs use SeaDrop's `keccak256(abi.encode(minter, MintParams))` leaf and sorted sibling hashing against the current on-chain root.
- Presale signatures use SeaDrop's chain-specific EIP-712 domain and include NFT, wallet, fee recipient, stage parameters and salt. The recovered signer must have enabled on-chain validation bounds. Noncanonical signatures and parameters outside those bounds are rejected.
- Wallet cumulative mint limit, collection and stage supply limits, allowed fee recipient and creator payout address. The stage's default `max_per_wallet` is not assumed to equal the wallet's cumulative allocation.
- A read-only simulation when the stage is active catches consumed signed-mint digests and additional collection/payout restrictions. The worker repeats proof/signature checks before estimating and submitting. No new proof, stage, price, quantity or signature is silently substituted after arming.

## Timing and activation limits

The OpenSea mint API selects eligible active stages. If no stage is open, it normally does not provide the wallet's presale calldata/proof. Mintly keeps that opportunity scheduled and cannot arm an unverified future allowlist stage. The user must approve once the API provides its transaction. This implementation does not claim unattended authorization of an unknown future proof.

The existing on-chain timestamp caveat bounds the approved mint. An included failed operation can still consume capped gas, including if a signed operation is submitted prematurely or after its execution window. Eligibility, supply and network fees can change after approval; simulation catches these changes where possible but cannot guarantee inclusion or success.

Direct-wallet submission remains disabled by default and needs a verified bundler endpoint and a user-reviewed live browser test before activation. No live user funds were spent in these tests.

## Verification

Local chain 31337 tests deploy the real SeaDrop source at commit `757590f11babfd81f4608f736e79e388469377f2`, the real MetaMask account/delegation contracts and real EntryPoint v0.7. The SeaDrop runtime is relocated to the canonical test address with its immutable domain separator adjusted and constructor reentrancy lock initialized. A minimal test NFT supplies collection mint statistics and configuration; SeaDrop's proof, signature and payment logic is real.

Both presale types mint through owner-approved UserOperations. Tests assert original-wallet NFT ownership and wallet-plus-EntryPoint-deposit debit equal to mint value plus actual gas. They reject changed wallets, prices, stage terms, fee recipients and proof/signature data; prevent operation replay; detect used presale signatures and replaced roots; and cover overlapping stage selection, API approval and durable worker submission.

Compiled fixtures include the source commit and compiler version. `seadrop-presale-sources.json` contains the complete Solidity compilation input, preserving upstream source license headers; corresponding third-party license texts accompany the fixtures. These contracts are test dependencies, not new production deployments.

## Primary references

- [OpenSea mint transaction API](https://docs.opensea.io/reference/build_drop_mint_transaction)
- [OpenSea drop stages and cumulative limits](https://docs.opensea.io/reference/get_drop_by_slug)
- [SeaDrop proof, presale signature and payment enforcement](https://github.com/ProjectOpenSea/seadrop/blob/757590f11babfd81f4608f736e79e388469377f2/src/SeaDrop.sol)
