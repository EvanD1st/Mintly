# Ten-account disposable simulation

Run `tests/test_ten_user_simulation.py` with a disposable loopback Hardhat SeaDrop chain and a disposable test database. No production users, credentials, RPCs or budgets are involved. The isolated GitHub workflow runs SQLite and PostgreSQL independently and never deploys. It also reruns the existing queue and six-wallet signer/cache regressions because their shared fixture gained an optional ten-account variant.

The mixed workload compares four distinct accounts/wallets (three copies and one automatic task) with ten (nine copies and one automatic task). Accounts approve via authenticated APIs. A real source mint is observed concurrently for every follower, using the current observer and global execution lock. Concurrent signer requests run alongside account-scoped screen reads, stored artwork reuse and actual wallet-specific background eligibility checks. Signatures, nonce reservations, immutable approvals/deadlines, spending caps, recipients and local receipts are asserted. Replay requests must reuse the saved hash.

A separate ten-account signed whitelist workload preflights validated encrypted instructions, clears signer memory and submits twenty concurrent preparation requests (two per task). It requires ten signatures, ten matching journal entries, zero fresh builder calls, wallet-correct mint quantities and successful local receipts. Ten expired instruction caches under a controlled provider failure must not sign, extend consent or leak reservations; durable scheduler retries stop at the original deadlines.

The independent permit-capacity test uses a controlled clock and real database gate: ten fresh builder permits at the current 20-second mint gap span 180 seconds. This is permit arithmetic, not ten actual provider calls or production throughput. Public SeaDrop tasks use their existing supported on-chain path and do not demonstrate whitelist builder quota.

Reports include scan completion, preparation response latency, execution-lock wait, background API latency, feed-check count and artwork provider count. Four- and ten-account cohorts each represent a single simultaneous burst; sample percentiles are descriptive, not a production service-level claim.

Set `MINTLY_SCALE_REPORT` to append credential-free JSONL reports. The normal fixture uses scrypt N=1024 for disposable keys. `MINTLY_SCALE_PRODUCTION_KDF=1` re-encrypts all benchmark wallets with production N=262144 before the measured phase, so signing timings include the larger decryption cost. Provisioning/encryption itself is excluded. Both modes preserve the current global execution lock and 2/20/8-second request settings with a 40-attempt preparation limit.

These in-process ASGI and local-EVM runs exclude WAN latency, real OpenSea calls/quota/cooldowns, public-chain congestion/finality and phone rendering. Production KDF cost is measured on the runner hardware, not the production server. The current four real accounts are untouched. The simulation evaluates the existing architecture; it does not implement account-scoped execution locks or authorize a production scaling rollout.

## Cold full-list workload

`test_full_daily_list_simulation.py` adds a smoke cohort and ten accounts each
opening the current WAT day's eight supported, distinct local SeaDrop collections.
Duplicate API submissions must create exactly 80 wallet-check records. Five
followers copy a real public source mint while five other accounts prepare fresh
signed whitelist instructions and run through the real automatic scheduler,
signer, broadcast, receipt tracking and reservation settlement.

The provider transport is controlled; successful replies take 350ms for shared
metadata/artwork, 600ms for wallet eligibility, 2.4s for mint builders, with
periodic 2.2s read responses. These assumptions represent a plausible latency
range, not measured OpenSea guarantees. SDK parsing, in-process caches, shared
database arbitration, 2s aggregate pacing, 20s mint pacing, 8s queue waits and
durable retries run unchanged in real wall-clock time. All cohort keys use
production scrypt cost in CI. Only the disposable EVM's scheduler clock is aligned
with its deliberately advanced stage time; rate-gate time is not accelerated.

The actual display-check worker processes one item at a time with its existing
one-second cadence. Wallet eligibility responses use controlled warm identity
consent, with mixed whitelist outcomes to test account isolation. Real login/PAT
refresh traffic is excluded. Background requests that cannot get capacity must
remain unverified rather than invent eligibility. Reports distinguish processed
checks from verified whitelist results, cache freshness at queue completion,
provider requests, queue deferrals, Today API timing and mint completion.

The test creates a stored daily list and exercises Today/card API reads; it does
not log in to X or fetch live posts. Artwork metadata goes through the existing
cache; phone image downloading/decoding is excluded. This is a cold burst without
continuous requeueing of already-expired cards, so it is not a steady-state load
test or certification of production capacity.

The fresh-builder workload requires PostgreSQL, which production uses. SQLite's
execution writer locks the entire database while the signer calls the independent
rate-gate session, so that second writer cannot progress. The full EVM workload is
explicitly skipped on SQLite; a bounded database regression reproduces the lock
and verifies that the gate proceeds after the execution transaction releases it.
Earlier cached/on-chain-only SQLite cohorts do not exercise this coordination
edge. This simulation documents the limitation without changing runtime locks.
