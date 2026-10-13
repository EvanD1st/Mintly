# Daily discovery and wallet cards

Twscrape 0.20.1 reads the operator's authenticated X session only in the discovery
worker. The encrypted or cookie-based X identity is never an app login. Provision
`~/Mintly/shared/x-session/accounts.db` from the tested account database, with
directory mode 0700 and database mode 0600, owned by UID/GID 10001. The deployment
script mounts that writable directory only into discovery-worker. Do not commit it.

Discovery polls every 300 seconds and bounds each authenticated fetch to 45
seconds. Twscrape's persisted endpoint reset locks prevent requests during provider
backoff. There is no guest/RSS production fallback. `X_DISCOVERY_ENABLED=false`
pauses polling; existing source records and manual imports remain available.

Migration 025 adds explicit WAT list dates, parser versions, stable per-post entry
keys, posted price/time fields, per-account wallet selection and wallet-check rows.
Old unparsed source posts are reprocessed in bounded batches. Expanded X metadata
is preferred; short-link redirects use the existing pinned-DNS URL protections.
Raw original text retains unsupported entries, mixed prices and auction terms.
Today requests `daily_only=true`; ordinary older clients keep the existing feed
API. Supported-network flags and usable OpenSea collection links filter Today.

The feed returns stored cards without provider IO. A maximum of 20 visible card
IDs can enqueue checks for an owned wallet. Cache lifetime is 60 seconds;
concurrent requests deduplicate by account, wallet and drop. A durable 90-second
lease recovers abandoned checks. Stage verification is bounded to 60 seconds and
provider failures use at least 60 seconds of backoff, respecting longer retry
instructions. Three display-check attempts are permitted per queued refresh.
The UI polls stored cards every ten seconds only while Today is visible and the
app is resumed. Cache expiry does not erase the last successful check: cards label
it "Last checked" while refreshing, with setup disabled until fresh verification.
Failures invalidate freshness but retain that history and its original check time.
Polling cannot bypass a pending retry or reset the three-attempt backoff. The
60-second TTL and request pacing are unchanged; no early refresh is introduced.
`FEED_WALLET_CHECKS_ENABLED=false` pauses this queue without affecting approvals.

Eligibility is wallet-specific, never stored in shared stage eligibility fields.
Discovery uses a validated read-only RPC factory while transaction execution is
disabled in that service. Network opt-ins, HTTPS and chain-ID checks still apply;
the preparation and signer paths retain their existing execution checks.
Verified open stages precede verified future stages. Rejected whitelist stages
remain visible. Known exhausted allowances disable setup. Stale checks and
provider failures show Not verified. Setup rechecks the selected stage and opens
an owned personal plan; existing plans are opened without changing their phase,
quantity or approvals. Arming still uses the existing explicit review flow.

Discovery uses background OpenSea priority and the existing shared cooldowns.
Aggregate spacing remains 2 seconds, mint spacing 20 seconds, queue wait 8 seconds
and preparation attempts 40. Discovery does not acquire the mint execution lock
for metadata or display checks. OpenSea identity renewal retains its existing
short custody lock around fixed-purpose login signatures. There are no execution,
copy-observation, budget, approval, nonce or journal protocol changes.

Captured real source fixtures cover the 13 October eight-entry list, 12 October
checker labels and 10 October mixed prices. The concurrent disposable SeaDrop
regression performs three copy preparations and one automatic preparation with
feed verification; it asserts deadlines, four nonces and four signed journals.
This establishes correctness under a controlled local workload, not production
throughput. Full CI also runs SQLite, PostgreSQL, Android instrumentation and
production-style startup. Release results are recorded separately after CI.

Release this additive backend migration and compatible Dart cards before the
saved-account/native-vault release. Dart-only changes can use OTA; protected
account switching requires a newly signed Android APK.

Display eligibility uses OpenSea collection/eligibility reads, not mint-builder
requests. Reads still consume the shared aggregate gate and provider cooldowns,
so they have bounded background priority rather than a promise of zero impact.
Display verification reuses its just-fetched collection response; the ordinary
plan/arming stage path still fetches and validates its own response.
