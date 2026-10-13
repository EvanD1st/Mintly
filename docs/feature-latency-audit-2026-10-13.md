# Mintly feature and latency audit — 13 October 2026

The mixed workload completed without a failed copy or automatic signature in the disposable environment. One real device-registration race was reproduced. Wallet balance/readiness checks and cold HTTPS connections were the largest measured production read delays. This audit does not establish real-phone frame rate, live mint-builder latency, or mainnet confirmation speed.

Production/main inspected: `a238a7252e63c78ebf3696af2ae9804229d51ad5`. Tested audit code: `7e4c1f9de14f84910f7fd39f4007add1e6c32efb`. [CI evidence](https://github.com/EvanD1st/Mintly/actions/runs/38343236947); conclusion: **success**. Production application code, queue defaults, observation/retry behavior, approvals, spending limits and the execution lock were unchanged. No migration, production deployment or OTA was performed for this audit.

## Tests and route tracing

| Environment | Outcomes | Traced HTTP requests | Documented method/routes exercised |
|---|---|---:|---:|
| sqlite | {'passed': 547, 'skipped': 2} | 2279 | 86/86 |
| postgres | {'passed': 548, 'xfail': 1} | 2283 | 86/86 |

Route coverage means an HTTP request exercised a documented method/path; it is not branch coverage. Negative tests, retired feature responses and deliberately injected failures are included. Response payloads, credentials, account IDs and private keys were not retained in the traces. The registration defect remains an explicit strict expected failure; it is not counted as a pass.

The full suites cover login/account isolation, password/session handling, wallet setup/import/unlink, Today/source ingestion, mint plans and phase selection, immutable automatic approvals, budgets/reservations, copy watches and Free/Paid modes, public/allowlist/signed minting, permissions/revocation, nonce and journal recovery, all six advertised networks, activity/history, notifications, artwork and migrations. The formerly omitted routes were additionally checked through authenticated HTTP, including logout revocation, administrative deletion of a disposable account, source toggles, manual import, eligibility consent and the signer stage broker. Incompatible mutations (logout, account deletion, pause) run separately from signing so the workload has a meaningful authorized outcome. Flutter analysis and all 98 mobile tests passed, as did the browser capability probe, Android secure-session instrumentation and clean production-style startup on the disposable CI runner.

## Concurrent workload

Three users' copy approvals and one administrator's automatic task used four distinct authorized wallets. All four preparations were released together with 57 screen reads, logins and notification preference operations. The scenario produced 102 traced requests including setup and final reads, with a peak of 63 overlapping requests. All scenario responses were HTTP 200 on SQLite and PostgreSQL.

The normal observation/approval/signer paths produced four signatures, four nonce reservations and four successful SeaDrop receipts on the disposable local EVM. Each wallet used nonce 0; the journal recorded four signed tasks and three signed copies. Approval deadlines were unchanged. These assertions reuse the existing real execution-lock regression. Provider metadata and other-network balance responses were controlled; disposable keystores used cheaper test KDF settings. This is correctness and host latency evidence, not four-user production mint performance.

| Environment | Mixed workload route | Requests | Median ms | Maximum ms |
|---|---|---:|---:|---:|
| sqlite | /api/wallets/readiness | 4 | 259.74 | 278.69 |
| sqlite | /api/tasks/queue | 4 | 264.29 | 275.47 |
| sqlite | /api/copy-mints/activity | 4 | 369.23 | 393.52 |
| sqlite | /api/artwork | 4 | 404.73 | 406.94 |
| sqlite | /tasks/{task_id}/prepare | 4 | 716.46 | 905.15 |
| postgres | /api/wallets/readiness | 4 | 530.10 | 568.67 |
| postgres | /api/tasks/queue | 4 | 567.72 | 572.27 |
| postgres | /api/copy-mints/activity | 4 | 641.04 | 648.67 |
| postgres | /api/artwork | 4 | 686.42 | 703.42 |
| postgres | /tasks/{task_id}/prepare | 4 | 1032.49 | 1160.48 |

Cached artwork returned the same valid collection URL during preparation and subsequent reads; exactly one instrumented metadata request populated it. The mobile cache regression also verified one download shared across screens and reuse after reopening storage. The six-authorized-wallet tests exercised actual cached-instruction preparation, scope validation, at-most-once signing, journal/nonces, bounded misses/retries and unchanged deadlines.

The production metadata cache contained 16 image URLs across 21 entries. The other five entries lacked URLs; this does not establish whether their collections supply images or whether every screen record has artwork. Three direct public-CDN reads returned 200 in 5.97–156.85 ms from the server, with 15–74 KB responses, using no OpenSea mint-builder requests. One response was AVIF and two were WebP.

The exact three downloaded fixtures were then passed through the actual `ThumbnailCache` decode, resize-to-256px, PNG conversion and disk write on the Windows Flutter host. All decoded successfully, with one download each. Cold host times were 117.79–1880.59 ms; subsequent memory reuse plus reference metadata writes took 21.48–28.36 ms. The first sample includes cold decoder/storage initialization, so this does not isolate an AVIF format penalty. These elapsed times are not evidence of UI-thread blocking. [Flutter's codec documentation](https://api.flutter.dev/flutter/dart-ui/instantiateImageCodec.html) makes additional format support platform-dependent; Android handset compatibility remains unmeasured.

Fresh-builder capacity is a separate controlled-clock permit simulation: the retained 20-second mint gate allows four uncached mint requests at 0/20/40/60 seconds, or six at 0/20/40/60/80/100 seconds. The 2-second aggregate gap does not remove that endpoint gate. Neither simulation measures real provider responses. Expected waits and approval expiry must not be reported as app glitches.

## Production read latency

Five samples per feature, four concurrent database sessions, existing administrator-owned records, PostgreSQL transactions explicitly READ ONLY. Times below cover handler execution after owner lookup and exclude HTTP/authentication, client decoding and rendering. Every one of these 65 reads succeeded. Small sample sizes support median/maximum observations, not a production percentile SLA.

| Feature | Samples | Median ms | Maximum ms |
|---|---:|---:|---:|
| wallets | 5 | 8.95 | 107.80 |
| mint plans | 5 | 9.42 | 20.59 |
| daily budget | 5 | 7.82 | 15.49 |
| policies | 5 | 5.01 | 14.29 |
| mint queue | 5 | 7.74 | 17.56 |
| copy following | 5 | 29.39 | 151.04 |
| check-only | 5 | 16.40 | 25.92 |
| copy activity | 5 | 32.80 | 146.15 |
| activity | 5 | 10.47 | 19.21 |
| copy history | 5 | 18.93 | 30.18 |
| permissions | 5 | 6.46 | 17.74 |
| mint history | 5 | 70.79 | 97.82 |
| wallet readiness | 5 | 1359.09 | 1483.76 |

The desktop network probe separately measured fresh health/protected-route connections at median 1,211 ms (20 requests, maximum 3,366 ms). Four persistent connections had cold health requests at median 2,221 ms and subsequent protected-route requests at median 160 ms (16 requests, maximum 175 ms). Protected requests correctly returned 401, so these are transport/auth-boundary measurements, not authenticated feature response times. They cannot simply be added to the handler table to claim end-to-end screen latency.

## UI checks

The Flutter suite checks the dark screens at 360×800 and text scales 1.0/1.4, navigation, budget menu/exact amounts, activity details, thumbnails and widget exceptions/overflow. Instrumented tap-to-settle host times ranged from 22.7 to 230.4 ms across 16 transitions. Mock API responses and Flutter's test clock were used; settle pump counts are not dropped frames. Android emulator instrumentation separately verifies encrypted session persistence through process restart, tamper detection and clearing.

The initial extended UI trace left artwork retry timers alive at test teardown. Explicit provider-container disposal corrected that harness failure; no application timer code changed. Expanding the full PostgreSQL run also exposed two pre-existing worker fixtures with missing authorization/wallet/drop/stage foreign keys. The fixtures now create valid references; foreign-key enforcement remains enabled.

## Confirmed defect and priorities

1. **Device registration race:** two independent PostgreSQL sessions both read an absent token, then insert it. One succeeds and the second violates `ix_notification_devices_device_token`, returning HTTP 500. The deterministic regression records HTTP 200/500; production's six-hour diagnostic log sample contained one HTTP 5xx and matching uniqueness errors. Counts of stack-trace/error strings are not separate incidents. This can disrupt notification registration. The copy/automatic signer does not use this endpoint. Recommended fix: atomic insert/upsert plus owner-aware conflict handling, preserving cross-account token protection and preferences. Keep the audit regression failing until the implementation genuinely handles the race.
2. **Readiness speed:** wallet balance checks consistently took about 1.36 seconds, versus mostly tens of milliseconds for stored screen data. Consider a short-lived display cache and show the last checked time while refreshing. Signing must retain fresh balance, approval and cost checks.
3. **Transport startup:** fresh connections cost noticeably more than reused connections. Verify connection reuse on actual devices before changing networking or queue limits.

All eight production containers were running in the diagnostic snapshot, with about 6.10 GB free disk. API CPU was 0.14% and copy-worker CPU 16.18% in that single sample; this does not establish sustained load capacity. No provider-429 strings appeared in those sampled logs; that does not prove no provider rate limits ever occur.

## Unavailable live checks

Actual users' Android frame times, low-memory-device behavior, live MetaMask prompts, push delivery to phones, an authenticated live X feed, sustained production OpenSea mint-builder load, mainnet transaction inclusion/reorg speed and an end-to-end customer signing stress test were not measured. Real transactions in this audit were confined to disposable local chains. Production probes were read-only and customer approvals/funds were not used. Raw sanitized metrics are in `audit/summary.json`, the two CI trace JSON files, `audit/production-handlers-repeated.json`, network probe JSON files and `audit/ci/mobile-widget-latency.jsonl`.
