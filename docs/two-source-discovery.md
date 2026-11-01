# Two-source daily discovery

Approved X sources are @lakzonevn and @Cassio_Sch. Each has an independent producer,
database polling lease, endpoint-aware backoff, last successful check and resumable
pagination position. Fresh pages are checked before resuming older history.
Source revisions commit before pagination advances. Original text and expanded
links are retained even if processing, OpenSea, or later pagination fails.
A separate inbox consumer leases work and retries it without holding X sessions.
Provider metadata waits return the database connection and have a per-post budget.

Today merges source mentions into one stable collection card. Name equality only
finds candidates. Exact canonical OpenSea links and compatible networks, or
matching verified network/contract identity, establish a merge. Conflicting
verified identities block that merge. Private plans, authorization snapshots,
signer policies and armed tasks are never changed by source posts. Aliases retain
old drop IDs and dismissed state. Only the selected wallet's real task can supply
Armed/Minted. Old queued alias eligibility checks are retired.

Both sets of source claims remain available in Source details. Times with an
explicit UTC/WAT zone convert to WAT; ambiguous times remain unverified. Each
source's price and phase claims are discovery information. Wallet eligibility
and transaction terms still require independent verification. Entries without a
supported automatic integration remain visible as informational cards.

Daily alerts use one durable row per post/account/device, rather than per day.
Publication is serialized using a discovery-only row lock, independent of mint
execution locks. The first list says "Today's mint list is ready"; the second
says "Second list just dropped". Later distinct list posts use "Another mint
list just dropped". A revision or repeated fetch of a post does not create
another alert. Duplicate-only second lists still announce the list, without
claiming new collections. Old lists expire at WAT midnight. Earlier pending
notices block later ones for the same account/device until delivered or failed.
FCM acceptance is not proof of phone presentation; stable Android tags limit
duplicates after ambiguous delivery.

New/updated badges are per account and survive refresh/login. "Mark additions
as seen" acknowledges only the hashes from that displayed response. An old
acknowledgment cannot hide a later revision. Notification taps validate account
ownership and open Today. No new user setting or native installer is needed.
The admin Sources screen shows both source states and retries saved posts.
The existing admin paste/import flow also uses the durable daily-list inbox.

Discovery enqueues source/backup health alerts without Firebase credentials.
The independent notification worker delivers only to eligible admin devices,
with finite retries. Source archives contain public X post revisions only,
excluding manual text, sessions, wallets, bearer tokens and signer state.
Hourly gzip snapshots cover the preceding 14 days, retain at most 48 snapshots
and use a 128 MiB total cap (the newest snapshot is retained). The protected host
directory is shared/source-archive, mode 0700, with archive files mode 0600.
These archives survive container replacements and complement the primary DB;
they are on the same host and do not provide off-server disaster recovery.

Migration 029 preserves original IDs, dismissals, account data and sent notices.
Existing records form the seen/notification baseline, so upgrading does not
reannounce historical lists. Single collection imports do not consume daily-list
sequence numbers. The schema downgrade is deliberately blocked because collapsing
per-post delivery history into one row per day would discard records. Use a
reviewed forward repair. Never restore spending/accounting DB state independently
of the signer journal as a source-feed rollback.

Deployment: take and verify a protected database backup before migration. Pause
only the notification delivery container while replacing its outbox constraint;
mint execution services continue running. Deploy after complete SQLite/PostgreSQL,
real-EVM, mobile and startup CI. Migration creates Cassio's source paused. Publish
and verify the audited OTA for Android 1.1.3+6 and 1.1.4+7, then enable that source.
Check source identity, persisted revisions, merged Today cards, finite retry
state, delivery records and archive output. Do not manually arm or retry customer
mints for this verification.

Migration 030 adds nullable public receipt evidence for unsigned tasks whose wallet
already consumed its selected phase allowance in another transaction. Reconciliation
runs after a specific mint rejection; it verifies chain, wallet, collection, phase,
canonical receipt/finality and exhausted allowance. A matching finalized mint gets
`already_minted`, stops retries and personal-plan polling, and releases the unused
reservation at zero task cost. The separate receipt is linked in Today/history;
the task never inherits another transaction's signature, nonce or spend. Ownership,
another phase, an unfinalized/reverted receipt or unavailable RPC history cannot
establish this outcome. Recent-history scans are bounded to twelve network-sized
log pages and eight seconds; older/unavailable evidence retains bounded checks
and the specific provider reason. No customer task is rearmed during deployment.

The captured November 1 list fixture was read from the authenticated X reader:
https://x.com/Cassio_Sch/status/2116814511298519048 .
The pagination adapter uses the pinned twscrape 0.20.1 raw timeline API:
https://github.com/vladkens/twscrape/blob/v0.20.1/twscrape/api.py .
