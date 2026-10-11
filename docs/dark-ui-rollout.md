# Dark interface follow-up

The approved dark concepts are implemented using the existing forest/mint palette. Main screens use only their screen title: Today, Mint plans, Copy, Activity, Wallet. The application now selects dark mode regardless of the device theme.

- Mint plans separates saved plans from automatic tasks, provides labelled phase/time/quantity/cost rows, and opens plan review controls on a details page. The read-only task response now includes its existing `plan_id`, so an active task does not also appear as a saved plan needing approval. The Armed / active filter excludes completed tasks.
- Copy retains its approval, pause, retry, check-only and management actions. Its Following/Activity tabs are compact, and cards show the existing free/paid setting.
- Activity has transaction, copy-event and account-update filters, compact status/cost cards, and a detail page retaining all approval, recovery, address and transaction records. Actual spend is displayed only when the API supplies it. An approved cap is never labelled as actual spend or as a measured reservation.
- Copy and Wallet show an allowance selector grouped by network. Amounts use exact integer wei, include each active unexpired grant once, and come from the existing signing-policy API. This is an approved signing allowance, not a wallet balance or a newly pooled budget. Individual copy rules, shared copy approval limits, daily limits and wallet funds still apply. Refresh, returning to these tabs, and resuming the app reload the values.

## Collection images

`GET /api/artwork?reference=plan:<id>|drop:<id>|copy:<id>` returns an optional collection image URL. Private plans and copy observations are checked against the signed-in account; drops must be public or belong to an owned task. The client never receives the OpenSea key. Images are representative collection artwork, not a promise of the eventual revealed token.

Artwork uses the existing server-only OpenSea client and its shared pacing, cooldown and background read priority. Fresh requests yield while urgent waiters or due mint/copy preparation exist; cached images remain available. An incoming mint can still arrive after an artwork permit, so this does not claim a separate provider quota or zero request contention. No mint-builder call is made for artwork.

Successful URLs are cached for 24 hours per API process; absent artwork for 10 minutes; transient failures for 1 minute. The cache is bounded to 512 entries and concurrent identical fetches share one request. The mobile request cache is bounded to 128 references, expires after two minutes and resets with the account session. Flutter also caches decoded images. Only HTTPS OpenSea CDN URLs are displayed; unavailable, unsupported, unrevealed or failed images use an icon without blocking navigation or preparation.

No signer, observer, copy worker, retry schedule, global execution lock, OpenSea gate implementation, quota default, immutable approval or spending enforcement is changed. The only existing task API change is adding the optional display linkage `plan_id` to responses.

## Validation and release

Run `flutter analyze` and `flutter test` in `mobile`. The redesign tests exercise a 360px phone at 1.0 and 1.4 text scale, allowance switching/refresh, inactive/expired grants, session cache isolation, plan/task linkage, copy skips, and retained transaction details. On Windows with the preview font installed they save actual Flutter screenshots under `mobile/build/dark-redesign` (sample account data, fallback artwork).

Run `flutter test --dart-define=MINTLY_TEST_DEFAULT_FONT=true test/dark_redesign_test.dart` to exercise the same wide fallback font used by Linux CI on Windows as well. Navigation items and section headings have bounded widths; the Activity record selector expands within the available width. Tests scroll to controls before tapping at enlarged text sizes.

Run the full backend suite with a disposable local Hardhat EVM on port 18545. `tests/test_artwork.py` covers account access, CDN validation, contract/collection binding, concurrent cache use, optional failures and yielding to urgent waiters. CI also runs it with the existing PostgreSQL regression suite.

No database migration or new credential is required. Deploy the backend response additions and mobile build together for complete artwork and plan linkage; older backends show fallback artwork and continue to support existing actions. No production deployment is included in this implementation. HyperEVM, ApeChain and Ink activation remains a separate network-support change; this UI does not advertise unsupported networks as available.
