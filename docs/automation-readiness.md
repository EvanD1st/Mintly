Mintly automation readiness
==========================

Scheduled execution
-------------------

The automatic worker runs advance checks in a separate loop for unsigned,
non-copy tasks between 10 seconds and 3 minutes before their selected time.
Checks refresh every 30 seconds, with at most eight tasks per pass. They do not
decrypt keys, allocate nonces, sign, broadcast or add spending reservations.

The isolated signer verifies its pinned policy and account code, reconciles
previous finalized receipts and checks the reviewed stage. Receiving-wallet
whitelist proofs are prepared when the provider makes them available. Only
unsigned execution data is cached, for up to 90 seconds in signer memory.
Restarting the signer or changing the task invalidates that optimization.

At the selected time, the signer still verifies ownership, consent, immutable
limits, stage, supply, eligibility, pending nonce, current gas, balance and its
independent journal budgets. A recent successful advance reconciliation avoids
repeating receipt RPC work for at most 30 seconds; unresolved liabilities stay
fully charged. Gas-price and estimate calls run concurrently. Due unsigned and
prepared tasks get priority over receipt polling, and signing clears the extra
one-second worker delay. Chain inclusion and confirmations remain outside
Mintly's control. Waiting tasks defer from the end of their RPC response so a
blocked wallet nonce cannot continually displace other due tasks.
No change to the source confirmation policy is included.

Copy observation
----------------

Each watch/network pair has its own session and cursor. Up to four read-only RPC
scans run concurrently, processing up to 100 oldest-checked watches per pass.
A five-second pause follows the batch, rather than each wallet. Discovery is
bounded to 45 seconds per pair. Failed scans preserve the last committed block.
Archival and cursor changes are checked again under the execution lock before
observations are stored. Arming and budget reservations use the shared execution
lock and fresh state. Other network cursor updates cannot be overwritten.

Wallet readiness
----------------

GET /api/wallets/readiness returns only the active linked wallets owned by the
authenticated user. Ethereum, Robinhood and Base each show pending ETH balance,
approval status, remaining unreserved budget, approval expiry, conservative
pending-mint maximum and the next task's advance-check note. An RPC outage
returns an unavailable balance, never zero. No gas amount or eligibility is
guaranteed before the mint-time check. Public RPC reads have bounded concurrency
and a ten-second request deadline. Expiry is displayed in WAT in the app.

Account stop control
--------------------

Settings > Automation > Pause all is persistent and specific to that user.
POST /api/automatic/pause stops new custody signing, disarms unsigned scheduled
and copy tasks, releases their reservations and pauses existing copy rules.
Legacy unsigned tasks and awaiting/armed permissions are cancelled too.
Signed payloads keep their reservations and receipt tracking; the worker holds
further broadcast attempts while paused. A broadcast already published as in
flight cannot be undone. Resume does not reactivate old tasks or copy rules.
Users explicitly review plans and enable copying again; the existing resume
cursor excludes source mints that occurred while copying was paused.

Whitelist recommendation
------------------------

Prepare the receiving wallet's exact-stage proof in advance when available,
then verify it again against chain state before signing. If the provider only
releases proofs at opening, show "Checking whitelist access" and retry within
the original authorization window and bounded retry policy. Never reuse a
followed wallet's proof, silently switch to the public stage, or enlarge limits.
The existing one-time opt-in and collection-level no-mixed-stage guard remain.

OpenSea's mint API selects the first eligible active stage and can report a
not-started drop as 409, so advance proof availability cannot be guaranteed:
https://docs.opensea.io/reference/build_drop_mint_transaction

Validation uses disposable wallets and real SeaDrop contracts on an isolated
local EVM, plus PostgreSQL locking and Flutter behavior/layout checks. It does
not send mainnet test transactions or change customer approvals.
