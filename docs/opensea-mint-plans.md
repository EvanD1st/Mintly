# Personal OpenSea mint plans

Every signed-in user can import a direct `https://opensea.io/collection/<slug>`
link after linking MetaMask. The import creates a private plan for that user's
default linked wallet. It does not add a drop to the shared @lakzonevn feed.
Admin text-list imports still use the shared feed.

The first supported integration is native-ETH SeaDrop V1 ERC-721 drops on
Ethereum, Base, Robinhood Chain, Arbitrum One and Optimism. Users select 1–100 NFTs;
OpenSea enforces the wallet's stage limits, remaining supply and balance for that quantity.
Mintly reads the contract, stage schedule,
and price from OpenSea's official Drops API. It sorts stages by their start
time and rechecks the wallet when a stage opens. A successful mint preparation
response from OpenSea is required for **ready for approval**. Missing allowlist
access, balance, supply, or wallet limit leaves the plan **not ready**. Before
a presale opens, eligibility remains unverified; a public stage may be checked
later even if an earlier presale cannot be used.

When a timed check becomes ready, the worker submits a notification to that
user's opted-in devices. The free API rate limit can delay checks during busy
periods, and delivery to a phone is not guaranteed. Opening OpenSea rechecks
the plan before handing off to the official mint page. Use the same wallet
shown on the plan, and approve the transaction in MetaMask. On a phone, use
MetaMask's built-in browser if the normal browser cannot connect to MetaMask.
Existing MetaMask links work across the supported EVM networks without relinking.
Select the drop's network in MetaMask and hold ETH there for mint price and gas.
Unsupported networks and other mint contract types return separate explanatory errors.

The mint price comes from OpenSea in integer wei. Network gas is an RPC
estimate at the time of checking; it can change before inclusion in a block.
MetaMask displays the transaction's fee and total before the user signs.
Mintly's preparation flow does not sign, broadcast, import a recovery phrase,
or create an unattended mint authorization.

The cost card shows selected quantity, unit stage price, prepared mint value,
estimated gas and the combined ETH total. A Coinbase ETH-USDT quote converts
the total for display only. Quotes expire after five minutes; unavailable gas
or pricing leaves the corresponding total unavailable rather than inventing it.
No exchange or USDT payment is performed.

Automatic execution remains disabled. The product must not hold users' primary
wallet keys or create server-custodied user wallets. Future automation requires
user-approved, revocable on-chain permission with a specific collection, chain,
mint call, quantity, recipient, expiration and maximum spend. An ordinary
address-link signature grants none of those permissions. Network support,
allowlist behavior and gas accounting must be verified before activation.

The server obtains an [instant free OpenSea API key](https://docs.opensea.io/reference/api-keys)
and renews it near its seven-day expiry. The key lives in the private
`~/Mintly/shared/opensea` directory, mounted into the API and worker. It is not
included in the app or API responses. Rate-limit errors pause checks rather
than generating additional keys to gain throughput.

Source references: [drop details](https://docs.opensea.io/reference/get_drop_by_slug),
[mint preparation](https://docs.opensea.io/reference/build_drop_mint_transaction),
and [wallet-scoped eligibility](https://docs.opensea.io/reference/get_drop_eligibility).
