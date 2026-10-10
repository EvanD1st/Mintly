# OpenSea reliability rollout

The application uses one operator-provisioned developer credential from the existing
server-only `OPENSEA_KEY_FILE` mount. Its JSON is `{ "api_key": "<secret>",
"provisioned": true }`. Add `expires_at` only when OpenSea actually supplies an
expiration. Production never creates keys, even if `OPENSEA_ALLOW_INSTANT_KEYS`
is enabled accidentally. Revocation/access denial is actionable and does not
trigger replacement. Wallet read-only eligibility consent and mint authorization
remain separate from this credential.

Migration `021_opensea_queue` adds leased request waiters. All processes must share
the same database and enable `OPENSEA_COORDINATE_REQUESTS`. Every HTTP call obtains
a shared permit. Mint preparation takes priority over background work; a short
queue absorbs small waits, while durable task retries handle longer cooldowns.
Defaults retain conservative headroom: `OPENSEA_GLOBAL_REQUEST_SECONDS=6`,
`OPENSEA_MINT_REQUEST_SECONDS=20`, `OPENSEA_QUEUE_WAIT_SECONDS=4` and
`OPENSEA_PREPARATION_MAX_ATTEMPTS=40`. Both per-endpoint and aggregate gates apply.
Retry-After accepts seconds or HTTP dates. Capacity that exceeds the approval
deadline is reported without extending that deadline.

A read-only probe with the provisioned credential returned 200 for collection
metadata and 422 for mint preparation. Both reported a rate-limit value of 120,
but the headers did not identify the mint quota bucket. OpenSea documents
account-wide limits, while its mint endpoint does not document a phase parameter.
Do not substitute order-posting or fulfillment quotas for mint quotas. Keep the
conservative settings until OpenSea confirms the account's mint bucket.

New upcoming approvals can execute at opening instead of opening plus 15 seconds.
Existing persisted execution times and approval hashes are untouched. Preflight
prepares unsigned instructions when available. At signing, the signer rechecks
chain time, user time, phase, price, wallet allowance, supply and all spending
limits. A stale unsigned proof gets one refresh in a preparation attempt; a valid
replacement is stored independently of the immutable approval. Signed/uncertain
transactions retain the existing journal, nonce and recovery process.

Phase comparisons normalize UUIDs and supported aliases. Matching uses method,
timing and verified on-chain index when available, never label or price alone.
Ambiguous/different phases are rejected. Wallet-specific price and cumulative
allowance flow through selection, review and execution. All cached instructions
are wallet/collection/quantity specific and revalidated against the approved
chain, contract and phase before use. Collection metadata is cached for 15 seconds;
identical in-flight lookups share a request. Guided arming reuses its validated
preparation instead of repeating it.

Deployment: test the exact commit; back up PostgreSQL; build the release; stop old
key-owner processes before atomically installing the staged credential; run the
normal deployment/migration; verify health and credential metadata without printing
the secret. Confirm saved approvals, reservations and removed copy events remain
unchanged. Rollbacks must not restore automatic production key creation.

Regression coverage includes disposable local SeaDrop execution, RPC recovery,
immutable approvals, refreshed proofs, duplicate-signing protection, opening time,
phase normalization, shared queue priority and deadline capacity. CI runs SQLite
and PostgreSQL tests. Safe diagnostics contain IDs, scalar phase terms, HTTP status,
reason, duration, retry time and broadcast state; no proofs, calldata or credentials.

The Seeker Net public observations describe consecutive GTD index 2 and FCFS index
3, both free, with FCFS opening at 2026-10-09 18:00:05 UTC and final token activity
at 18:00:31 UTC. This is a timing regression scenario, not proof of a particular
user's failure or of overlapping phases. Provider instructions and remaining supply
can still prevent a mint; an API key cannot create eligibility or guarantee inclusion.

References: https://docs.opensea.io/reference/api-keys and
https://docs.opensea.io/reference/build_drop_mint_transaction.
