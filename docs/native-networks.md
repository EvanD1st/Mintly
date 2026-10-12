# HyperEVM, ApeChain and Ink

These networks use the same verified SeaDrop public/allowlist/signed mint path,
immutable approval checks, execution lock, nonce journal and recovery rules as
the existing networks. Following a wallet grants no signing authority. Existing
wallet policies and copy approvals do not automatically expand to new chains.

| Network | Chain ID | OpenSea slug | Native currency | Fee model | Default RPC |
| --- | --- | --- | --- | --- | --- |
| HyperEVM | 999 | hyperevm | HYPE (18 decimals) | EVM gas | https://rpc.hypurrscan.io |
| ApeChain | 33139 | ape_chain | APE (18 decimals) | Nitro parent-inclusive gas | https://rpc.apechain.com/http |
| Ink | 57073 | ink | ETH (18 decimals) | OP Stack gas plus parent/operator fees | https://rpc-gel.inkonchain.com |

The chain registry, matching SeaDrop deployment, historical calls, finalized
block support, HyperEVM 300-block log queries and Ink fee-oracle methods were
checked read-only on 12 October 2026. HyperEVM's restricted default RPC is not
used: copy observation needs historical state and the existing 300-block query
window. Public RPC availability is still a dependency; failures retain bounded
retry and pending liabilities rather than claiming zero costs or signing blindly.

References: [OpenSea chain API](https://docs.opensea.io/reference/get_chains),
[HyperEVM RPC restrictions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/json-rpc),
[HyperEVM providers](https://hyperliquid.gitbook.io/hyperliquid-docs/builder-tools/hyperevm-tools),
[ApeChain providers](https://docs.apechain.com/node-providers),
[Ink network](https://docs.inkonchain.com/general/connect-wallet),
[Ink fee contracts](https://docs.inkonchain.com/useful-information/contracts).

## Budget and consent boundaries

ETH, HYPE and APE are never added into one monetary total. Ethereum, Base,
Robinhood and Ink share the existing optional account-wide ETH daily limit.
HYPE and APE each have their own optional daily ceiling across that user's
wallets and both mint bots. Changing a limit does not reset spending or pending
liabilities. New native limits have separate independently hashed signer pins;
existing ETH configurations and hashes retain their exact original meaning.

One copy consent groups only grants using the same native currency. Switching
currency clears form amounts and consent. Other currencies need a separate
approval. Each grant still has its own network budget, maximum per mint and
expiry. Available budget cards report signing allowances, not wallet balances.
HYPE/APE USD estimates remain unavailable rather than applying an ETH quote.

Cumulative HYPE/APE budgets use exact integer storage and must stay below one
million tokens. Individual transaction prices, gas and total debit caps retain
the existing signed 64-bit wei boundary: strictly below 9.223372036854775808
native tokens. The wallet form defaults the per-mint maximum to the budget,
capped at 9 native tokens; the user can review a smaller maximum. A higher NFT
price cannot be approved by raising only a lifetime budget. ETH budget parsing
retains its existing boundary.

Ink reserves additional parent/operator fees using its oracle and rechecks them
before broadcasting. Inclusion may still change parent fees; actual full receipt
costs are recorded and an overspent policy is stopped. ApeChain gas estimation
uses Nitro's parent-inclusive total and does not add that component twice.

## Migration and rollout

Apply `alembic upgrade head`: revision `023_native_currency_budgets` widens
only cumulative grant/copy budgets, adds a currency to debit records (existing
rows default to ETH), and creates separate native daily-limit records. It does
not rewrite approvals, authorization snapshots, nonce allocations, signer
entries or private keys. SQLite budgets use fixed-width decimal strings to avoid
floating-point rounding; PostgreSQL uses NUMERIC(30,0). Independent journal
aggregation uses Python exact integers, avoiding SQLite SUM overflow.

Take protected database and consistent signer-journal backups before migration.
Enable `ENABLE_HYPEREVM_AUTOMATIC`, `ENABLE_APECHAIN_AUTOMATIC` and
`ENABLE_INK_AUTOMATIC` explicitly, and provide the matching `RPC_*` routes to
the API, importer, signer and workers via the custody overlay. Default flags are
false. Confirm each endpoint's chain ID before activation. Users must explicitly
approve new network signing limits and have the corresponding gas currency.

Do not downgrade after native accounting or wider budgets have been recorded.
The migration refuses truncating downgrade; an older app revision cannot safely
manage the new records. Restore only through an audited recovery that preserves
signed transactions and nonce liabilities.

## Verification and throughput

`test_native_networks.py` exercises real signatures, nonce/journal idempotency,
public/allowlist/signed SeaDrop execution and source-to-owned-copy preparation
on separate disposable EVM nodes with IDs 999, 33139 and 57073. Local Hardhat
has no OP/Nitro fee infrastructure: signer execution instruments those fee RPC
responses, and separate regressions exercise parent/operator and Nitro quotes
and receipt accounting. This does not claim production fee or speed results.
CI also runs the native regressions against PostgreSQL.

The mobile regressions exercise all six budget choices with exact native units,
large text and currency-specific copy consent. The approved compact dark UI uses
screen titles, real collection thumbnails when available and separate mint/copy
activity. OTA changes add no native plugins, dependencies, fonts or assets; the
existing installed-release asset/font audits remain required for all five
supported Android releases.

Copy observation/retry behavior and the global execution lock remain unchanged.
OpenSea defaults remain global gap 6 seconds, mint gap 20 seconds, queue wait
8 seconds and maximum preparation attempts 40. Additional chains do not increase
provider quota or guarantee every collection supports a qualifying mint stage.
