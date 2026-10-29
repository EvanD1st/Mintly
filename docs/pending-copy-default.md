# Earlier copies by default

Active copy approvals now react to publicly visible pending SeaDrop mint
transactions. There is no additional user setting. Following without a spending
approval, check-only mode, paused copying, expiry, wallet revocation and account
pause still block automatic signing. Existing approval hashes, source addresses,
mint methods, phase scope, quantities, prices, budgets and gas limits are retained.

The observer subscribes to full pending transactions, filters to actively copied
wallets and supported direct SeaDrop methods, and retrieves the transaction through
the configured chain RPC. Both observer and isolated signer reconstruct its signed
envelope, verify its hash, recover the sender and enforce the replay-protected
chain. Supported envelope types are legacy, access-list, dynamic-fee and EIP-7702.
They validate the live source nonce, stage, value, source proof where applicable
and simulation. The receiving wallet independently obtains its own instructions;
the source's proof or signature is never replayed for the receiver.

Only executable source nonces are accepted. The private journal records the source
chain/sender/nonce and receiving account atomically with signing, preventing another
copy from a replacement or replay under that source nonce. Historical confirmed
transactions cannot bypass the pinned approval block by being relabelled pending.
If the source becomes included during preparation, its actual successful canonical
receipt and mint transfers are verified and its actual block is compared against
the independently pinned approval. Pending observations do not count as completed
source mints; later confirmation upgrades the same event ID.

The receiving mint can be submitted before the source is included. It can succeed
even if the followed transaction is later cancelled, replaced or fails. Ordering,
same-block inclusion and supply are not guaranteed. A source invalidated before
signing is rejected. Source/provider visibility can change between checks; a
transaction already signed or submitted retains its original liability and tracking.

A per-chain live collector runs independently of historical catch-up. It queries a
small recent range for all watched addresses, persists observations before updating
the separate live watermark, and wakes the existing execution path. Historical
cursors remain intact. A failing or distant historical cursor no longer holds
recent source detection behind its backlog. Overlap, canonical checks, common event
IDs and private duplicate guards make re-reads safe. Each chain has its own loops,
bounded queue and provider-failure backoff. WebSocket reconnects use a capped backoff;
the confirmed collector covers subscription gaps.

Ethereum and Base have default full-transaction WebSocket endpoints. Other networks
can use operator-provided `RPC_<NETWORK>_WS` endpoints. A subscription must verify
the correct chain and return full transactions; hash-only feeds are not expanded
into unbounded RPC lookups. Private/sequencer-only transactions may not be visible
before inclusion. Such activity uses confirmed detection with two confirmations
(including the source block), rather than the former thirteen. Ethereum's operator
override remains bounded to at least two. Receiving-transaction finality and receipt
accounting are unchanged. `ENABLE_PENDING_COPY=false` is an operator stop control
enforced by both discovery and the signer; it does not disable approved confirmed
copying.

Read-only production probes verified Ethereum full-transaction subscriptions and
signature reconstruction of a real type-2 envelope without using any customer key
or signing/broadcasting a transaction. Base accepted the subscription and chain
identity but emitted no pending sample during the short probe. The existing
Robinhood HTTP host rejected the WebSocket handshake. These are capability probes,
not an end-to-end latency guarantee for every network.

Base's rate-limited default HTTP endpoint is replaced with the verified PublicNode
endpoint. Recent filtered log reads were verified with the application's Web3
client; a public endpoint still provides no dedicated production availability
guarantee. HyperEVM's existing provider accepted the small recent range used by
the live collector, while larger historical ranges continue to retry separately.

## Expired OpenSea eligibility access

Whitelist stage discovery requires the wallet owner's separate, finite read-only
OpenSea consent. An expired connection now explicitly says it expired, points to
Wallet > Details > OpenSea eligibility access, and explains that unverified
eligibility does not mean the wallet is ineligible. Public phases remain available.
No expired consent is extended or used to sign in on the owner's behalf.

Tests use isolated keys and a local EVM with automining disabled to prove that the
copy is signed and submitted while the followed transaction is still pending.
They also cover paused/watch-only accounts, source cancellation before signing,
forged identities, transaction envelope types, historical replay, source-nonce
reuse, subscription identity/filtering, live capture beside a failed history cursor,
event deduplication and expired read-only consent. Full SQLite/PostgreSQL, Flutter,
Android security and clean production startup checks gate rollout. No mobile OTA
or new native dependency is required.

References: [Geth subscriptions](https://geth.ethereum.org/docs/interacting-with-geth/rpc/pubsub),
[Ethereum PublicNode](https://ethereum.publicnode.com/),
[OpenSea wallet eligibility](https://docs.opensea.io/reference/get_drop_eligibility).
