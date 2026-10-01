# Direct smart-wallet gas investigation

Investigated and implemented locally 2026-10-01. Live direct-wallet submission remains disabled pending a verified bundler endpoint.

## Verified read-only on Robinhood mainnet

- Chain ID: 4663.
- Linked wallet: `0x5f1A65c4C3011eb22c2882c3e9ea8299f42Ccf7E`.
- Wallet code delegates to the configured MetaMask implementation, `0x63c0c19a282a1B52b07dD5a65b58948a07DAE32B`.
- Its `entryPoint()` returns `0x0000000071727De22E5E9d8BAf0edAc6f37da032`, with deployed code (16,035 bytes).
- Balance at inspection: 0.000350813264484 Robinhood ETH. This is not a gas or mint quote.
- The public RPC rejected the bundler-method probe with HTTP 403. That endpoint has not been verified as a usable bundler.

## Signing and payment distinction

MetaMask's account core validates owner-signed UserOperations and sends missing prefund from the wallet to EntryPoint. A bundler can therefore submit an operation with gas ultimately paid by the user's smart wallet, without funding Mintly's operator wallet.

The stateless implementation accepts the original wallet owner's ECDSA signature. The existing delegation signature does not authorize Mintly's operator key to sign UserOperations for that wallet. Switching the existing relayer to direct wallet gas is not a configuration toggle.

## Candidate implementation

Have the user approve a complete, exact UserOperation when arming, then retain that signed operation for scheduled bundler submission. Bind contract, calldata, quantity, mint value, chain, nonce and gas limits/fee ceilings. Add an on-chain validity window and single-use enforcement; a plain UserOperation signature alone does not add expiry. Evaluate a self-delegation with the existing timestamp and exact-execution enforcers for that window.

The backend must not change signed calldata, nonce or fee fields. If the operation becomes invalid or market fees exceed the signed ceiling, require renewed approval. Provide cancellation/revocation and test their races with submission. Preserve the original wallet as the minter for allowlist identity. Merkle allowlist and signed-presale validation is now implemented; see [allowlist minting](allowlist-minting.md) for tested scope and proof-availability limits.

Actual gas is determined at execution. Display an estimate and a maximum debit, not a guaranteed exact future fee. Included operations can charge gas even when the mint reverts. Any EntryPoint deposit residue must be disclosed and recoverable.

## Outstanding before activation

- Obtain and verify a Robinhood bundler supporting this exact EntryPoint and MetaMask's account validation.
- Validate Robinhood-specific bundler behavior, gas estimation and browser signing against the live deployed account.
- Validate browser typed-data signing and bundler estimation/submission with a user-reviewed test operation.
- Implement durable scheduling and receipts without unrestricted signing or custody of the user's key.

No live transaction was signed or broadcast in this investigation. No production signing flow was changed.

## Implemented flow and local verification

`ENABLE_DIRECT_WALLET_GAS=true` selects direct wallet gas for new permissions. `ENABLE_DIRECT_WALLET_BROADCAST=false` allows approvals and live bundler simulation without sending; set it true only after verifying compatibility. The default is false. Existing legacy permissions retain their original execution path. Direct mode requires no operator key or balance and does not fall back to the legacy relayer when its bundler is missing.

The user signs two typed messages during arming: a self-delegation with exact-execution, timestamp and single-use caveats, then an owner-signed UserOperation wrapping redemption of that delegation. Signing the delegation alone does not arm the plan. The operation uses an independent random nonce key, no factory and no paymaster. No user private key reaches the backend.

The backend verifies the wallet EntryPoint, bundler chain ID and supported EntryPoint. It quotes bounded gas limits and a fee ceiling before approval. At mint time it estimates the signed operation and rejects gas requirements above its limits. It stores the expected operation hash before submission, never changes signed fields, never obtains a fresh nonce for retries and tracks receipts after ambiguous submission outcomes. The permission status hash is a UserOperation hash in this mode, rather than an enclosing transaction hash.

Tests with the real MetaMask contracts and EntryPoint v0.7 on chain 31337 prove NFT ownership stays at the original wallet and total wallet-plus-deposit debit equals mint value plus EntryPoint actualGasCost. Fee, calldata and nonce tampering fail validation. Replays fail. Early, expired, revoked and invalid-price mints fail without minting; their included operations still charge gas and consume the nonce. The Python typed-data digest and operation hash match the real contracts. API and worker tests exercise the two-signature requirement, private signature storage, no operator dependency and durable immutable submission.

Timestamp checks occur during execution, not UserOperation signature validation. Someone possessing the signed operation could submit it early or after expiry and consume its capped gas without minting. Revocation stops the mint but cannot guarantee zero gas loss from submission of the already-signed operation. The interface explicitly discloses this limitation. A new account validation contract would be required to enforce that window before execution.

EntryPoint can retain unused prefund as a deposit belonging to the wallet. That deposit is included in test accounting; it is not paid to Mintly. The current balance check conservatively requires the full quote in the wallet, without treating an existing EntryPoint deposit as spendable balance.

## Bundler setup before live use

Create a provider app for Robinhood mainnet and obtain an authenticated ERC-4337 endpoint supporting EntryPoint v0.7. Check the provider's current plan and limits; provider account/API availability has not been verified here. Keep its URL out of source control and chat because it may contain an API key.

Place a mode-600 JSON file at `/run/opensea/mint-bundlers.json`, mapping supported chain ID strings to HTTPS bundler URLs. For example, the object should have key `"4663"` and your provider endpoint as its value. This is already inside the backend/worker private mounted directory. Alternatively set `MINT_BUNDLER_CONFIG_FILE` to another private mounted path.

Enable `ENABLE_DIRECT_WALLET_GAS` after verifying the endpoint, with `ENABLE_DIRECT_WALLET_BROADCAST=false` for the user-reviewed browser/simulation test. Enable broadcasting only after that test passes. Keep `ENABLE_MINT_PERMISSIONS=true` for the permission API/worker. Then deploy the backend and the Flutter review wording together. No database migration or new native mobile dependency is required.

## Primary references

- [MetaMask stateless account signature rules](https://github.com/MetaMask/delegation-framework/blob/main/src/EIP7702/EIP7702StatelessDeleGator.sol)
- [MetaMask account core and prefunding](https://github.com/MetaMask/delegation-framework/blob/main/src/EIP7702/EIP7702DeleGatorCore.sol)
- [ERC-4337 specification](https://eips.ethereum.org/EIPS/eip-4337)
- [Alchemy bundler methods and supported EntryPoint discovery](https://www.alchemy.com/docs/wallets/transactions/low-level-infra/bundler/overview)

Setup verification on 2026-10-01: authenticated Alchemy endpoints for Ethereum chain 1 and Robinhood chain 4663 returned matching chain IDs, supported EntryPoint v0.7 and priority-fee quotes. Endpoint secrets are stored only in private configuration. No live user operation has been sent.
