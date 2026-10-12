# OpenSea capacity and account fairness

Mintly retains one operator-provisioned server-side OpenSea key. The shared
request gate defaults to two seconds between requests globally, 20 seconds
between mint-builder requests, an eight-second short queue, and at most 40
durable preparation attempts. A 503 response with an explicit `Retry-After`
holds the affected endpoint across processes; a response indicating an
exhausted account bucket can hold all endpoints until reset.

All endpoints arbitrate the same leased waiter queue using the same last
mint-owner state. Gate creation and row locking use alphabetical order; all
acquirers lock the aggregate and mint gates, plus their own endpoint gate.
Only the aggregate and requesting endpoint affect pacing and cooldowns or
have their permit times advanced. Reading the fairness state does not consume
a mint permit or apply a mint-only cooldown to metadata.

The highest-priority waiters are considered first. Within that priority, the
oldest owned mint request from an account other than the last mint owner wins
when present; otherwise the oldest waiter wins (creation time, then ID).
Copy preparation and armed-task preparation have equal priority, including
their supporting metadata requests. Mint preflight is lower priority and
background metadata is lowest. Expired leases are removed before selection.
This alternates waiting mint owners when possible; it is not strict round
robin across every account and does not guarantee a maximum wait under a
continuous higher-priority backlog. All accounts still share provider capacity.

Six wallets that each need fresh mint-builder instructions require permits
at approximately 0, 20, 40, 60, 80 and 100 seconds in an otherwise empty
queue. Only the first two fit inside a 26-second mint window. This is a
controlled permit-capacity simulation, not six concurrent signer executions.
Valid cached preflight instructions avoid fresh mint-builder requests, but
each instruction still passes the signer's current eligibility, terms, gas,
approval and nonce checks.
Approval deadlines are unchanged; an instruction that cannot be prepared
before expiry is reported as insufficient time, without extending consent.

`test_opensea_multiwallet.py` separately exercises six authorized tasks across
six distinct custodial wallets and two accounts on a disposable local SeaDrop
chain. Real preflight checks populate encrypted instructions, then signer
memory is cleared. Concurrent preparation and duplicate requests use separate
database sessions and the unchanged execution lock. Assertions cover zero
fresh builder calls for valid cached data, one signature and nonce reservation
per task, matching private journal entries, approved calldata and spending
caps, successful local receipts, and reuse of the saved hash on replay.
Fault cases reject another wallet, collection, quantity or stage index; missing
and expired cache entries fetch and validate instructions. Real signer failures
feed the scheduler to test the 40-attempt boundary, cooldown deferral, expiry
and released reservations without changing approval snapshots or deadlines.
The existing on-chain allowlist-change regression also verifies one bounded
refresh and rejection when the provider still returns a stale proof.

These tests replace the upstream OpenSea builder with instrumented local test
instructions. They demonstrate correctness, not provider quota, production
latency, six-user throughput or public-chain inclusion. Mixed-endpoint caller
orders (including simultaneous requests), owner alternation, priority and
expired-waiter regressions use separate sessions. CI runs these and the local
EVM signer tests on both SQLite and disposable PostgreSQL.

The current execution transaction lock still serializes copy arming,
cancellation and signer preparation across accounts. It protects approval,
reservation and signing consistency, but can delay an account before it
reaches the OpenSea queue. Removing that contention requires a separately
reviewed owner-scoped execution lock with cancellation and signer concurrency
tests. The present change does not weaken those safety checks.

No new migration or configuration change is required by this follow-up.
Existing installations must already have migration `022` (the gate/waiter
owner fields) from the completed rollout. Defaults remain 6/20/8 seconds and
40 preparation attempts; copy observation/retry behavior and server-only
credential provisioning are unchanged. Production deployment is separate.
