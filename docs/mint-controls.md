Mintly mint controls
====================

Progress
--------

Queue and Copy activity display checking, preparing, sending, inclusion and
confirmation from durable task state and canonical receipt evidence. Inclusion
is provisional until the existing confirmation/finalization policy passes. A
missing or noncanonical receipt clears provisional inclusion after a reorg.
An uncertain send is labelled as checking transaction status, never confirmed.

Daily spending
--------------

Settings > Automation > Daily spending limit adds an optional ETH ceiling for
one account, across both bots, all receiving wallets and all execution networks.
It covers NFT value and gas. Existing policy, rule and per-mint ceilings remain.
The period is the calendar day in WAT (UTC+1), not a rolling 24-hour period.

Unsigned tasks reserve their reviewed maximum on their planned day. Unsettled
older reservations carry forward; signatures with an uncertain outcome keep
their full liability until canonical receipts establish actual debit. Reverts
charge gas but not refunded NFT value. Canonical block time assigns the actual
debit to its WAT day. Removing a plan or unlinking a wallet preserves history.
Turning off or changing the cap never resets costs or signatures.

The signer independently pins limit revisions and maintains daily identity and
day records in the same fsync-backed transaction as its signed payload journal.
Historical signature ownership is recovered from immutable private policy files,
and settlement dates from canonical receipts, rather than mutable API history.
Deleting API reservations, restarting workers or changing an unregistered limit
cannot bypass the signer ceiling. Configuration confirmation failures block new
signing until retried. A reduced ceiling cannot undo a signature already issued.

Check-only copying
------------------

Copy settings has a separate check-only mode. It can evaluate an owned linked
receiving address without a signing policy. It verifies confirmed source mints,
the exact stage, the receiving wallet's eligibility, quantity, limits and current
funding, then estimates gas and performs a read-only pending call.

Check configurations and results have separate tables. They cannot create mint
authorizations, mint tasks, nonce assignments, spending reservations or signatures.
Entering this mode pauses existing copy rules and disarms their unsigned tasks;
previously signed payloads remain tracked and may finish. Leaving check-only does
not resume paused rules. An explicit new copy approval is required. Manual copy
review is also blocked while this watch's check-only mode remains active.

Results say Would copy, Would skip or Not verified and always identify that no
transaction was sent. These are point-in-time evaluations, not mint guarantees
or an expanding authorization. Only activity after the check configuration's
verified block boundary is eligible. Earlier observations are reported as history.
Whitelist data belongs to the receiving wallet; public-stage fallback is rejected.

Alerts
------

The notification worker checks active owned wallets separately from mint
execution. It emits funding alerts for upcoming reviewed maxima or zero gas
balance on active copy networks, and alerts for relevant approvals ending within
24 hours or expired. RPC outages do not become zero balances.

Durable owner/wallet/network/type state deduplicates repeated checks. A funding
alert is emitted again only after recovery and another shortage; renewed approvals
clear old expiry alerts. Versioned acknowledgement preserves a newer alert if
state changes during delivery. Unlinked/inactive wallets and accounts are excluded.
Delivery failures retry with a five-minute backoff; FCM acceptance followed by a
process crash can still cause a duplicate, as with the existing task outbox.

Settings > Notifications > Gas and approval alerts controls this category.
Old preferences follow the existing mint-status preference until explicitly set.
No account-specific alert can be sent without its owner; the app rejects messages
for another signed-in account. Device opt-out does not remove personal history.

Validation and rollout
----------------------

Regression tests use disposable keys and real local SeaDrop contracts, including
multiple wallet keys, shared network accounting, concurrent arming, midnight WAT,
journal/database commit loss, deleted reservations, legacy signature backfill,
funding retries, inclusion/reorg tracking, check-only no-spend boundaries, alert
deduplication, renewal, opt-out, unlinking and user isolation. The same execution
checks run against PostgreSQL. Flutter checks cover small phone layouts, both
themes, confirmation flows, check-only without an approval and push ownership.
Production deployment and OTA publication follow passing isolated tests and
native/asset compatibility audits. No mainnet test transactions are sent.
