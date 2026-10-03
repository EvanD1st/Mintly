# Robinhood signer adapter — 2026-10-02

Implemented, but not activated on a funded mainnet wallet. No user key has been
imported and no mainnet mint has been signed or broadcast by this work.

## Account fix

The old signer rejected any nonempty account code. EIP-7702 explicitly permits
an account with a valid 23-byte delegation indicator to originate ordinary
owner-key transactions. The new `eip7702-direct` adapter uses that route: the
same account sends the exact validated SeaDrop transaction, retaining its address
and eligibility. It does not use MetaMask token grants or create/remove a delegation.

Operator provisioning must explicitly select `--account-mode eip7702-direct`.
It reads and pins the delegation indicator and delegate bytecode hash inside the
independent signer policy, prints the pins before custody acknowledgment, and
rejects empty or chained delegates. Readiness and signing recheck the pins.
Existing policies without this field continue to require an account with no code.
Changing a delegation requires a new policy. Ordinary contracts cannot use this adapter.

Pins detect bytecode changes; they do not establish that wallet code, its storage,
or NFT receiver callbacks are safe. A change after signing cannot invalidate the
signature. Existing signed transactions retain their original liability and nonce.

## Fees and settlement

Chain 4663 requires both `ENABLE_CUSTODIAL_AUTOMATIC=true` and
`ENABLE_ROBINHOOD_AUTOMATIC=true`, an HTTPS RPC, and a verified RPC chain ID.
Other mainnets remain unsupported.

The signer queries both `eth_estimateGas` and Nitro NodeInterface
`gasEstimateComponents`, uses the larger total with 20% upward-rounded padding,
and enforces the authorized gas and total debit ceilings. Parent data gas is
already included in the Nitro total and is never added twice. Missing or invalid
component responses prevent signing. Actual accounting uses receipt gas used
times effective gas price, plus mint value only on success.

Canonical receipts must also be covered by the RPC's `finalized` block before
budget is released. The real Robinhood RPC returned latest block 78549087 and
finalized block 78538224 during the read-only check on October 2. Soft receipts
remain submitted while settlement is pending; uncertainty never authorizes a
second mint with a fresh nonce.

## Deployment configuration

The existing isolated custody Compose overlay now accepts `CUSTODY_CHAIN_ID`
(default 11155111), `CUSTODY_RPC` (falling back to `CUSTODY_SEPOLIA_RPC`), and the
separate Robinhood opt-in. For Robinhood these must be 4663, a verified Robinhood
HTTPS endpoint, and true, respectively, consistently across API, signer and worker.
Protected vault/password/journal mounts and operator provisioning remain required;
see [custody setup](automatic-custody.md). This template was not deployed here.

The requested one-NFT, $0.50 test has **not** been executed. The previous dollar
quote is historical. Policies enforce ETH/wei ceilings, not a live USD oracle;
do not reuse that historical conversion as a current $0.50 guarantee. A newly
reviewed task must specify quantity one, the exact collection and current total
ceiling including fees. Do not paste keys into chat or app fields.

## Verification

The full backend suite passed **148 tests in 190.95 seconds**, with the local EVM
enabled and no skips. The focused adapter and execution suite passed **39 tests
in 100.00 seconds**. The custody Compose YAML parsed with the opt-in propagated
to API, signer and worker; Docker deployment was not run. A fresh read-only full
mainnet adapter simulation attempt timed out at the public RPC while reading
allowed fee recipients, so it produced no new successful simulation report.

Three new real local Prague EVM
cases install a delegation through a signed type-4 authorization, then run the
authenticated API → isolated signer → scheduler path for public, allowlist and
signed-presale mints. Receipt sender, NFT ownership, recovered signer, balance
debit, budget accounting and lack of a duplicate mint are checked.

Additional tests reject unprovisioned, malformed, changed, empty and chained
delegations; require explicit mainnet opt-in and HTTPS; include a positive
parent-data fee without double charging; and hold settlement until finalized.
The Nitro component test uses a controlled RPC response, not a local Nitro node.
The delegation implementation is a test receiver, not deployed MetaMask code.
These tests do not constitute a successful mainnet execution or production audit.

Sources: [EIP-7702 transaction origination](https://eips.ethereum.org/EIPS/eip-7702#transaction-origination),
[Nitro gas estimation](https://docs.arbitrum.io/arbitrum-essentials/how-to-estimate-gas),
[Robinhood fees](https://docs.robinhood.com/chain/gas-and-fees/),
[Robinhood finality](https://docs.robinhood.com/chain/transaction-finality/).
