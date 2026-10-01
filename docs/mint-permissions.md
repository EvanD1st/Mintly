# One-use mint permissions

Implemented through MetaMask's deployed delegation framework, not an unrestricted
ETH allowance. The standard ERC-7715 permission types currently cover transfers;
an exact mint uses a custom signed delegation with exact batch execution, timestamp and
one-use enforcers. The SDK 2.0.0 registry is pinned in the backend and live code,
chain ID and the delegator's EIP-7702 implementation are checked before approval.

Users must already have the compatible MetaMask Smart Account enabled on the
selected network. The address stays the same. Mintly never upgrades an account,
imports its key, stores seed phrases, or creates a custodial user wallet.
The user signs one exact spending permission in the browser. OpenSea and MetaMask
do not need to be opened again at the scheduled execution time.

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

Set `ENABLE_MINT_PERMISSIONS=true` for both containers and keep the default
`MINT_RELAYER_KEY_FILE=/run/opensea/mint-relayer.key`. The maximum estimated gas
fee per execution is `MINT_RELAYER_MAX_FEE_WEI` (default 0.001 ETH).
The relayer must hold at least that amount before requests can be accepted.
This is a relayer operating limit; L2 data fees can be additional. The user
permission fixes their exact debit independently of the operator's gas cost.
Legacy signer and unattended task routes remain disabled.

An operator-funded relayer and a verified RPC are required for live activation.
The repository default is disabled, so installing code alone never authorizes
spending. A compatible user account must still explicitly approve each permission.

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
367,152 gas and the confirmed local receipt used 300,098 gas. Fork gas prices and
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
