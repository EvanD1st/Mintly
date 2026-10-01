# MetaMask browser signing review — 2026-10-01

The real browser reported:

> External signature requests cannot sign delegations for internal accounts.

The site requested `eth_signTypedData_v4` with `primaryType: Delegation` and the
linked account as its delegator. MetaMask's signature controller deliberately
rejects that combination unless the request is a recognized, decoded wallet
permission. Mintly's custom exact-execution/timestamp/single-use delegation is not
one of the published Advanced Permissions types.

The proposed second signature has another incompatibility: its EIP-712 domain's
`verifyingContract` is the user's own wallet address. MetaMask rejects external
typed-data requests that use an internal account as the verifying contract.
Changing only the first signature request would not make this flow work.

MetaMask lists Robinhood under smart-account contract support but does not list it
under Advanced Permissions. Contract deployment and successful local EVM tests
prove the contract behavior, not that the browser can grant those permissions.
The earlier claim that two MetaMask signatures could arm this mint was incorrect.

Production now blocks creation, challenge and signature completion for the raw
mint flow, and both workers refuse to process it in production. The website never
requests either raw signature. The app explains that scheduled signing is unavailable
and retains the explicit OpenSea/MetaMask mint confirmation path. Wallet linking,
saved plans, eligibility, quantity and cost checks remain available.

Existing signed permissions can still be revoked with an explicit MetaMask
transaction even when activation is disabled. Unsigned requests can be cancelled
without an on-chain revocation. Nothing in this repair imports a user key or sends
a mint, transfer, account upgrade or other paid transaction.

Browser regression tests verify that an old mint challenge cannot trigger a
signature or transaction, while an existing revocation still requests its exact
transaction. Production API tests reject all raw signing endpoints even with the
old flags enabled and confirm that plans and revocation remain accessible.
Worker tests confirm that flags cannot override the production guard.

A future automatic-mint design needs a supported wallet permission that preserves
the original allowlisted minter and enforces the exact call, quantity, value,
validity window and gas limits. This is not solved by requesting a broader token
allowance or changing how the blocked signature is displayed.

Primary references:

- [MetaMask signature validation](https://github.com/MetaMask/core/blob/main/packages/signature-controller/src/utils/validation.ts)
- [Supported Advanced Permissions](https://docs.metamask.io/smart-accounts-kit/get-started/supported-advanced-permissions/)
- [Supported networks](https://docs.metamask.io/smart-accounts-kit/get-started/supported-networks/)
