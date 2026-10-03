# Robinhood Ape Club: read-only mainnet check

At 16:00 WAT on 2 October 2026, a read-only probe validated the selected
collection's public mint on Robinhood chain 4663. It did not sign, arm or broadcast
a transaction. Mainnet automatic execution remains disabled.

The [machine-readable report](robinhood-ape-preflight.json) records the observations.

| Item | Observation |
|---|---|
| Collection | https://opensea.io/collection/robinhood-ape-club-449348279/ |
| Collection contract | `0xAA19274645CbFdC4De5C9C10586CBaCA409b2C72` |
| Executing address checked | `0x5f1A65c4C3011eb22c2882c3e9ea8299f42Ccf7E` |
| Quantity / stage | 1 NFT / public |
| Mint price | 0.000037 ETH |
| Gas limit with 20% padding | 141,216 |
| Gas price observed | 31,912,000 wei |
| Padded gas allowance | 0.000004506484992 ETH |
| Mint + padded gas | 0.000041506484992 ETH |
| ETH/USD reference supplied | $2,728.29 per ETH |
| Total at that reference price | $0.11324172793882368 |
| User's total cap | $0.50, including gas |
| Chain simulation / funds check | Succeeded / sufficient |
| Signed / broadcast | **No / no** |

The contract address was obtained from OpenSea's authenticated Drops API for the
exact collection slug. The probe subsequently read the public stage from SeaDrop,
validated price, opening/closing time, wallet/supply limits, fee recipient,
recipient and quantity, simulated the call and estimated its gas. It queried
Nitro's `NodeInterface.gasEstimateComponents`; that node returned zero parent-data
gas for this particular estimate. The code includes the returned component in
the total rather than adding it twice. See the official
[Arbitrum gas-estimation explanation](https://docs.arbitrum.io/arbitrum-essentials/how-to-estimate-gas).

The ETH/USD value is a supplied reference from the market-price lookup, not an
on-chain dollar limit or a promise about the price at inclusion. Fees, supply,
eligibility and exchange rates must be refreshed before a user submits anything.
No transaction hash or ownership change resulted from this check.

## Why this does not pass automatic minting

The account's observed code was
`0xef010063c0c19a282a1b52b07dd5a65b58948a07dae32b`.
This has the [EIP-7702 delegation designator](https://eips.ethereum.org/EIPS/eip-7702)
format. At the time of this original check, the custody signer rejected accounts
containing code. The subsequent [signer adapter fix](robinhood-signer-adapter.md)
adds explicitly pinned direct EIP-7702 signing and Robinhood fees. A successful
`eth_call` does not prove custody signing, broadcasting, receipt reconciliation,
finality, or operation while the client is disconnected.

No private key has been imported. No custody policy for this wallet was created.
Mainnet services remain disabled; the new adapter requires a separate opt-in.
A manual OpenSea/MetaMask mint would also not
prove Mintly's unattended execution path.

## Reproduce the read-only check

From `backend`, supply a newly checked ETH/USD reference:

```powershell
python -m app.robinhood_preflight --url https://opensea.io/collection/robinhood-ape-club-449348279/ --wallet 0x5f1a65c4c3011eb22c2882c3e9ea8299f42ccf7e --max-usd 0.50 --eth-usd FRESH_ETH_USD_PRICE --output ../docs/robinhood-ape-preflight.json
```

The collection-address binding is pinned to the verified slug; this command does
not accept arbitrary unverified projects. It always checks quantity one and
explicitly reports `automatic_ready: false`, `signed: false`, `broadcast: false`.

The new quote arithmetic tests and existing custody boundary tests passed:

```text
python -m pytest tests/test_robinhood_preflight.py tests/test_custody_security.py -q --tb=short
14 passed in 4.46s
```

Changed files for this check: `backend/app/robinhood_preflight.py`,
`backend/tests/test_robinhood_preflight.py`, this note and the JSON report.
No existing execution guard or live deployment setting was changed.
