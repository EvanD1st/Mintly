# One-use mint permissions

## Production status: unsupported browser signing (2026-10-01)

Scheduled automatic minting through the linked MetaMask wallet is unavailable.
MetaMask rejects the custom delegation signature from an external website. It also
rejects the proposed owner UserOperation typed signature because its verifying
contract is an internal wallet account. Local contract tests used ephemeral signing
keys and did not establish compatibility with the MetaMask browser prompt.

Production API and worker guards reject this experimental path even if its old
activation flags are enabled. The app and website no longer request these signatures.
Mint plans, eligibility checks, quantity selection and cost estimates remain available.
Users must use **Open on OpenSea** for a wallet-ready plan and confirm the actual mint
and fee in MetaMask when the eligible stage opens. Existing signed permissions remain
revocable; cancelled unsigned requests do not need on-chain revocation.

MetaMask's published Advanced Permissions types cover token transfers. Its supported
Advanced Permissions network table does not include Robinhood, although its smart-account
contracts support Robinhood. Broadening the wallet permission is not a substitute for
the promised exact-mint scope. See [browser signing review](metamask-browser-signing.md).

## Local contract experiments

The experimental contract implementation uses exact batch execution, timestamp and
one-use enforcers. The SDK 2.0.0 registry is pinned in the backend. These contracts and
their tests are retained for research; they are not a working production wallet flow.

Users must already have the compatible MetaMask Smart Account enabled on the
selected network. The address stays the same. Mintly never upgrades an account,
imports its key, stores seed phrases, or creates a custodial user wallet.
The local tests create exact spending signatures with disposable test keys. Real
MetaMask accounts cannot produce these signatures through Mintly's browser flow.

Scope: native ETH SeaDrop public mints. Future stages can be authorized up to 24
hours before opening, only when the on-chain public stage matches OpenSea's price,
schedule, quantity limit and allowed fee recipient. Allowlist stages stay manual.
The exact value, calldata, recipient, quantity and target cannot be changed by
the relayer. The permission is valid for at most 30 minutes from execution start.
The on-chain single-use enforcer prevents a second successful execution, including
if the server is compromised. It does not guarantee NFT value or mint availability.

The operator's separate relayer fronts network gas and needs operating ETH.
The user reimburses a fixed quoted ETH fee in the same atomic batch as the mint.
The exact mint and reimbursement target and amounts are signed; neither can be
increased. A reverted mint also reverts reimbursement. The operator still bears
the network cost of a reverted transaction. Mintly holds no user deposit or key.
The app and browser display fee, total ETH debit and estimated USDT before signing.

The quote budgets 450,000 gas units at the current RPC gas price, capped at the
operator maximum. This is a fixed execution fee, not a guarantee of actual gas or
an automatic refund of the difference. Simulation with 20% gas padding must fit
the signed quote or the worker refuses to send. Additional L2 data costs remain
operator costs and never enlarge the user's debit. Revocation costs separate gas.

## Operator setup

The API and worker already share the private `/run/opensea` volume. Generate an
operator-only key with `tools/setup_mint_relayer.py --key-file
~/Mintly/shared/opensea/mint-relayer.key --create` using the backend dependencies.
The helper prints the public address only and writes a mode-600 key. Never put a
user wallet key there. Keep a secure operator backup; keep gas balances small.

For isolated local experiments only, `ENABLE_MINT_PERMISSIONS=true` enables the
test lifecycle. Keep production disabled. The experimental default is
`MINT_RELAYER_KEY_FILE=/run/opensea/mint-relayer.key`. The maximum estimated gas
fee per execution is `MINT_RELAYER_MAX_FEE_WEI` (default 0.001 ETH).
The relayer must hold at least the current quoted gas budget before requests
can be accepted. The 0.001 ETH ceiling is not a required minimum deposit.
This is a relayer operating limit; L2 data fees can be additional. The user
permission fixes their exact debit independently of the operator's gas cost.
Legacy signer and unattended task routes remain disabled.

An operator-funded relayer and verified RPC alone do not establish browser support.
Production rejects this signing path regardless of those balances or flags.

## Cancellation and transaction recovery

Cancel before preparation stops the worker. The user may then request an on-chain
revocation code and approve `disableDelegation` in MetaMask. Cancellation in the
database does not revoke an already signed delegation on-chain. Once transaction
bytes are persisted, cancellation is rejected; submitted transactions cannot be
undone through the app. Signed bytes and their hash are committed before sending;
network retries reuse that hash, never a new mint nonce. Receipt tracking marks
success or revert. Price/supply changes cause simulation failure, not a wider
permission or automatic reauthorization.

Tests compare EIP-712 hashes and calldata to official SDK golden vectors, exercise
cross-user isolation and signature replay, and deploy the real MetaMask contracts
on a local Prague EVM to check single use, exact execution, expiry and revocation.

Sources:
- https://docs.metamask.io/smart-accounts-kit/get-started/supported-networks/
- https://docs.metamask.io/smart-accounts-kit/get-started/supported-advanced-permissions/
- https://docs.metamask.io/smart-accounts-kit/reference/delegation/caveats/
- https://github.com/ProjectOpenSea/seadrop/blob/main/src/lib/SeaDropStructs.sol

## Robinhood verification (2026-10-01)

All five production RPCs and the SeaDrop and pinned permission contracts were
checked. Ethereum's unauthenticated Ankr endpoint failed; PublicNode chain ID 1
and contract deployment checks passed and it replaces the default endpoint.
Robinhood's RPC verified chain ID 4663 and successfully simulated an EIP-7702
(type 4) authorization using ephemeral accounts and `eth_estimateGas` state
balance overrides. No authorization or mint was broadcast to a live network.

A local fork of Robinhood's real state successfully minted 2 Robinhood Ape Club
NFTs to an ephemeral smart account. The user debit matched exactly the mint
price plus signed fixed reimbursement; a replay failed. The padded estimate was
367,254 gas and the confirmed local receipt used 300,182 gas. Fork gas prices and
fees are test data, not a production quote. The local Prague EVM tests the real
contracts but does not reproduce every Orbit gas or L1 data fee rule.

Reproduce while this public stage is open (requires Hardhat 3.1.8):

```powershell
cd backend/tests/evm
npm ci --ignore-scripts
npx hardhat node --config robinhood-fork.config.js --network hardhat --hostname 127.0.0.1 --port 18546
# In another PowerShell at the repository root:
$env:PYTHONPATH = "$PWD/backend"
python tools/test_robinhood_fork.py --rpc http://127.0.0.1:18546
```

The helper refuses non-localhost endpoints and any chain ID except 31337.
Never fund the public Hardhat accounts on a real network. Users' compatible
accounts and the relayer's operating balance remain prerequisites for live use.

OpenSea's known four-byte SIP-6 suffix (`3d958fe2`) is accepted after the static
public-mint arguments and preserved in the exact signed calldata. Unknown suffixes
and extra arguments are rejected. The collection, recipient and quantity are
still validated against the plan.
