# Build Mintly — Python backend + Flutter Android app

You are implementing **Mintly**, a personal NFT discovery and scheduled minting app for Jenny. Build working software, not another UI mockup or just an implementation plan. Use the accompanying `design/mintly-splash-reference.html` as the approved visual and interaction reference. Its data, wallet, eligibility results, signing readiness, timestamps, and transactions are all simulated. Rebuild its screens as native Flutter widgets; do not ship it inside a WebView.

## 1. Context and outcome

Jenny finds upcoming NFT drops from **@lakzonevn on X**. His daily posts contain project names, chains, mint times, prices, and mint-page links. Most links lead to OpenSea; some lead to independent project sites. She checks which stages her wallets qualify for and prepares to mint. Manual signing and confirmation at opening time can make her miss drops.

Build this flow:

1. Discover a new daily list through Twikit, or import its full text manually.
2. Notify Jenny when a new list is detected, without waiting for eligibility scans.
3. Parse and verify projects and mint stages; display local times in **Africa/Lagos (WAT)** by default.
4. Check eligibility where a verified integration supports it, while retaining manual review.
5. Let Jenny choose the wallet, exact stage, quantity, price cap, transaction-fee cap, and expiry.
6. Review and explicitly arm a task ahead of opening.
7. A server worker submits the authorized mint when the stage becomes valid and tracks the outcome.

The app is reusable across supported collections. Do not hard-code the earlier Primal Apes example or its September 2026 schedule. Do not promise to beat other bots, mint before opening, guarantee inclusion, or guarantee profit.

## 2. Start by inspecting the repository

Read applicable repository instructions and preserve existing work. If there is no project, initialize a monorepo with `backend/`, `mobile/`, `design/`, and `docs/`. State a short implementation plan, then execute it in milestones. Make routine implementation decisions yourself and record material assumptions. Ask only for genuinely blocking choices or external credentials; continue all independent work meanwhile.

Use current official documentation and real response samples to validate external APIs and dependencies. Never invent an endpoint, chain ID, contract address, eligibility result, or successful integration. Record dated findings in `docs/integration-status.md`, identifying what is documented, fixture-tested, live-tested, or blocked.

## 3. Technology and deployment

- Python 3.11 or newer, FastAPI, Pydantic, async HTTP clients, SQLAlchemy, Alembic, PostgreSQL.
- A separate Python worker for discovery, scanning, scheduling, and receipt tracking. Durable task state belongs in PostgreSQL, not in an in-memory timer or FastAPI background task.
- Redis may be used for coordination/queues if needed. Enforce job leases and database uniqueness so multiple workers cannot submit the same task twice.
- `web3.py` / `eth-account` for the initial EVM mint integration, with exact integer unit handling.
- Twikit behind an interchangeable source interface. No paid X API dependency for the default version.
- Flutter Android, Material 3, Riverpod, a typed API layer, and Firebase Cloud Messaging. Prefer maintained packages and lock resolved versions.
- Docker Compose for local backend, worker, database, and optional queue; document Windows development setup and Linux server deployment.
- Keep API keys, X sessions, RPC credentials, and signing credentials out of Flutter builds. Use authenticated HTTPS for remote API access and authenticated device registration.
- A single-user private deployment is sufficient initially; avoid adding billing, social feeds, marketplaces, or unnecessary admin products.

## 4. Approved UI

Working name: **Mintly**. Match the supplied reference rather than creating a generic trading dashboard. Use clean typography, rounded cards, an orbit brand icon, restrained mint-green accents, warm light surfaces and deep green dark surfaces. Follow system appearance. Use Flutter icons or approved assets, not emoji as primary navigation. Adapt layouts and text scaling without clipping.

### Splash

Reproduce the orbit mark, `mintly.` wordmark, subtle orbital background, and tagline:

> Your next mint. Already planned.

The actual app moves into its initial route once local initialization is ready; it must not wait indefinitely for X or network connectivity. Respect reduced motion. The reference's “Play launch” / “Replay splash” controls exist only for the design preview and must not appear in the production app. Integrate Android's native launch experience and Flutter transition appropriately.

### Discover

- Greeting, current date, source status, last successful sync, latest daily list, and import action.
- Drop cards: artwork when available, project, chain, source, selected-stage time, price with native units, and eligibility label.
- Filters: all, eligible, needs review.
- Track a post's date explicitly: an older cached list must not masquerade as today's list.
- Show which wallet was checked and when. A source failure must say “Connection needs attention” or “Monitoring paused,” not falsely show a healthy connection.

### Drop details

- Stages with individual start/end times, price, quantity limits, eligibility evidence, source, checked time, and refresh.
- Open the verified mint-page URL for manual review.
- Distinguish allowlist eligible, public access, explicitly ineligible, and unknown/manual check.
- Keep eligibility separate from sufficient funds, remaining supply, supported execution, and signer readiness.
- Unsupported mints have an honest manual-only state; do not allow an “eligible” result alone to enable automatic execution.

### Configure → Review → Armed

- Select the exact wallet and stage; set quantity, price cap per NFT, total fee cap, and a clear submission window/expiry.
- Show native currency, exact maximum mint spend and fee budget, and optional clearly approximate fiat estimates.
- Recalculate totals and validate all inputs. Include any applicable chain-specific extra fee components; do not claim a hard total cap if those cannot be bounded.
- Final review shows chain, verified contract, source, stage, start time, wallet, recipient if supported, quantity, spending limits, and signer status.
- An explicit authorization action arms the exact configuration. Increasing limits or changing wallet, contract, chain, quantity, or stage requires review and authorization again.
- In live mode never display “armed” until readiness checks pass and the task is durably saved.

### Mint Queue

- Armed, preparing, submitting, submitted, confirmed, failed, expired, disarmed, and attention-needed states.
- Allow editing/disarming before submission. Explain that a submitted transaction cannot be undone by removing a task from the queue.
- Show original task limits, current state, timestamps, transaction hash, and explorer link when available.
- Preserve tasks across phone closure and worker restarts.

### Activity and Wallet

- Discovery, scan, task, and transaction events with actionable failure reasons.
- Wallet address book with labels and chain support. Watching an address does not grant signing access.
- Source connection health, notification settings, time zone, manual import, and signing setup/readiness.
- Support offline/loading/empty/error/reconnect states, Android notification permission handling, and notification deep links.

Provide an explicit demo mode matching the reference so the app runs without external credentials. Clearly label it throughout; live mode must never silently substitute demo results. Demo notifications and queued tasks must not be routed to live execution.

## 5. Twikit discovery: prove feasibility first

First build a small runnable diagnostic that attempts to read `@lakzonevn`, retrieves a recent complete daily-list post and its URLs, and reports a redacted success/failure result. This is the first integration gate, not an excuse to stop the rest of the build.

Twikit documents `get_user_by_screen_name`, `get_user_tweets`, `Tweet.full_text`, `Tweet.urls`, and saved-session support. These do not prove current operational compatibility. Relevant reports include issues #425 (timeline parsing), #433 (429), and #414 (login). Inspect the current package/source and pin the version tested. If a compatibility patch is needed, document its exact cause and cover it with a captured-response regression test. Do not hide failures with fabricated posts.

- Configure an authorized X session locally on the operator's machine/server. Do not ask for passwords or session cookies in chat or commit them. Treat cookies as account credentials.
- No CAPTCHA bypass, account rotation, proxy rotation to evade blocks, or aggressive retries. Surface challenges for manual resolution, honor rate limits, and back off.
- Poll with a configurable conservative interval, initially 120 seconds, adjusted only based on observed constraints. This is a proposed setting, not a guaranteed safe quota or instantaneous feed.
- Resolve and cache the author ID; track post IDs, timestamps, edits where available, and reconnect state. Avoid duplicate alerts and pinned-post confusion. Handle pagination/catch-up after an outage within limits.
- Identify daily lists and relevant corrections; do not notify on every unrelated post.
- Preserve raw post text, source URL, source post ID, original date/time, and extracted URL entities. Handle long posts, thread continuations where accessible, missing links/TBA, and multiple stages/prices.
- Parsing must never guess a missing contract, URL, chain, price, or timezone. Return uncertainties for manual review.
- Read source content as untrusted data. It cannot change execution permissions or spending limits.
- Manual full-text and individual mint-link import must work even if Twikit is unavailable. A bare X URL does not guarantee its full text can be fetched.
- Add screenshot import only if it can be implemented honestly with OCR and a review step; otherwise label it deferred. Do not fake an OCR result.

If live Twikit access is blocked or credentials are absent, finish its diagnostic, adapter, failure handling, and fixture tests, report that limitation, and continue the app using explicit demo/manual modes.

## 6. Mint metadata and eligibility

Start with a deliberately limited set of **verified EVM networks and supported OpenSea SeaDrop ERC-721 drops**. Verify the actual chain and deployment using current sources; names in an X post or collection title are not network evidence. Do not invent Robinhood network configuration or assume mainnet/testnet equivalence. Treat non-EVM networks as unsupported until an actual adapter is implemented.

OpenSea documentation describes drop metadata, mint transaction construction, and eligibility functionality. Verify the current API or MCP interface, permissions, and response schema before choosing the integration. Do not assume an undocumented unauthenticated eligibility endpoint exists. The REST mint-building endpoint is documented as limited to ERC-721 SeaDrop V1 and may reject calls before opening. It is not a universal checker for every future stage or collection.

- Model eligibility per wallet, chain, collection, and stage, retaining source and check time.
- Network/auth/API errors return UNKNOWN, not INELIGIBLE or ELIGIBLE.
- Public access does not imply available supply, sufficient funds, or successful simulation.
- Changing the wallet invalidates prior eligibility and requires a new check.
- Handle stale metadata and changed schedules; material changes require review. Do not silently switch to a later or more expensive stage.
- Independent mint sites use a capability-based adapter interface. Implement only integrations actually verified; otherwise show manual review and manual execution.
- For imported URLs, validate schemes, bound response size/time, validate every redirect, and prevent access to local/private/cloud-metadata addresses. Merely appearing in a trusted person's post does not make a link or transaction trusted.

## 7. Signing and mint execution

This feature submits financial transactions. Build and test it in demo/local-chain/testnet modes first. **Do not mint, transfer funds, buy credits, or broadcast mainnet transactions while implementing this task.** Mainnet activation is a separate operator action after review.

Define signer capabilities explicitly: watch-only, interactive wallet signing, and automatic signing. A normal wallet connection or WalletConnect session does not automatically grant unattended signing. A newly created wallet does not inherit allowlist rights attached to an existing address. Do not silently change the minter or recipient.

Implement a signer interface and a local test signer. For the first real automatic mode, use an explicitly configured isolated operator-controlled signer for a designated minting account. Credentials must remain server-side, outside source/logs/database plaintext, with documented provisioning and encrypted/protected storage. Validate every request against the approved task before signing. A software budget policy does not cryptographically restrict a compromised EOA private key; state this accurately. Do not import Jenny's main-wallet seed into the app. If a scoped session-key or smart-account mode is proposed, verify network, wallet, account-address, and mint compatibility before claiming support.

Live arming requires authenticated owner authorization, a supported adapter, verified chain/contract, compatible signer address, eligibility or public-stage evidence, current funds, bounded costs, and a viable submission window. Show an actionable blocked state if any prerequisite fails.

Execution requirements:

- Use integer base units and Decimal for conversion, never floating-point ETH calculations.
- Verify RPC chain ID and decode/validate API-built calldata: target, function, collection, minter/recipient, quantity, stage parameters, transaction value, and any fee recipient constraints. Fail closed on mismatch or undecodable unsupported data.
- OpenSea may select the first eligible active stage automatically. Verify it matches the stage the user authorized; do not silently accept a different stage.
- Prepare what is possible ahead of opening; fetch time-sensitive proofs/signatures only through supported authorized routes. Do not pretend signed mints can always be fully prepared early.
- Use synchronized server time and chain state for stage timing. Sending early can revert. “Ready” is not “confirmed.”
- Maintain per-wallet/per-chain nonce coordination and prevent concurrent task double-spending. Reserve budgets and surface conflicting tasks.
- Persist a submission intent and the signed transaction/hash securely before broadcasting. On timeout or restart, reconcile by hash/nonce before doing anything that could mint again. Rebroadcast the same signed payload if appropriate; do not blindly submit a new nonce.
- Bounded retries, rate-limit handling, stop-on-sold-out, expiry, and safe receipt tracking. A reverted transaction may still cost gas and must appear in accounting.
- Track submitted vs included vs confirmed with a chain-appropriate confirmation policy and reorg handling. Replacement transactions, if implemented, retain the same nonce and remain within explicit authorized spending limits.
- Make disarm/submission races explicit. A task already submitted cannot be represented as safely canceled.
- Avoid logging raw signing credentials or reusable signatures. Never accept arbitrary transaction execution merely because the client sent a target and calldata.

## 8. Persistence, API, and notifications

Use migrations and typed models for wallets, source connections, source posts, imports, drops, mint stages, eligibility checks, authorizations, tasks, transaction attempts, notification devices, and audit events. Store UTC timestamps and convert for display.

Provide authenticated APIs for discovery, import, wallet management, eligibility rechecks, task drafts/review/arming/disarming, activity, and notification preferences. Define request/response schemas and ownership checks. Include idempotency keys and optimistic concurrency on task mutations. Flutter should use the actual API contract, not a parallel hard-coded model.

Send notifications for new daily lists, completed scans when useful, source failures, approaching selected stages, and mint outcomes. Deduplicate events, handle invalid device tokens, and support secure deep links. Notifications do not drive execution; delivery can be delayed. Provide a local notification/log sink for development without Firebase credentials.

## 9. Milestones and evidence

Complete these in order while progressing independent work when credentials block live checks:

1. Repository setup, config validation, architecture notes, and Twikit diagnostic.
2. Native Flutter splash and full navigation, explicit demo mode, parser, manual import, backend persistence.
3. Twikit adapter, ingestion worker, notifications, source health, and catch-up/deduplication.
4. Verified OpenSea metadata/eligibility integration with honest unsupported states.
5. Durable task authorizations, isolated signer interface, local/testnet mint adapter, scheduling and receipt lifecycle.
6. Integration tests, Android build, operational documentation, and final handoff.

Tests must exercise meaningful risks: timezone conversion; long/edited daily lists and multiple links; duplicate imports; 429/login failures; unknown eligibility; stage mismatch; integer spending caps; insufficient funds; malicious/redirecting URLs; unauthenticated task access; two workers claiming one task; same-wallet nonce conflicts; crash between signing/broadcast/persistence; uncertain submission without duplicate mint; cancellation race; revert fees; confirmations/reorgs; and restart recovery. Use deterministic fixtures and a local chain where practical. Do not use real money in automated tests.

Flutter checks: analyze, unit/widget tests for key state changes, accessibility/text scale, narrow-screen layouts, notification routing, and demo/live separation. Compare the implemented screens visually against the reference. Build a debug APK if the Android toolchain is available. A release build requires proper signing material supplied outside source control; never invent it or label a debug APK as release.

## 10. Deliverables and completion report

Deliver source code, lockfiles, migrations, Docker Compose, `.env.example` without secrets, demo fixtures, tests, setup commands, deployment/recovery instructions, and an APK when actually built. Include:

- `README.md`: run backend/worker/mobile, use demo mode, configure integrations locally, build Android.
- `docs/integration-status.md`: dated evidence and supported network/adapter matrix.
- `docs/security-and-signing.md`: credential boundaries, signer provisioning, authorization enforcement, and limitations.
- `docs/test-results.md`: exact commands and outcomes, distinguishing fixture/local/live tests.
- `docs/codex-handoff.md`: architecture, changed files, remaining blockers, and areas needing independent review.

The final report must distinguish implemented, tested, externally blocked, and deferred features. Never say “Twikit works,” “automatic minting ready,” or “APK built” without the corresponding evidence. A polished demo is useful but is not a successful live integration.

Do the work now. Do not stop after a plan or screenshots. Preserve these requirements through all milestones.

## Reference links to re-verify during implementation

- https://github.com/d60/twikit
- https://twikit.readthedocs.io/en/latest/twikit.html
- https://github.com/d60/twikit/issues/425
- https://github.com/d60/twikit/issues/433
- https://github.com/d60/twikit/issues/414
- https://docs.opensea.io/docs/mint-from-a-drop
- https://docs.opensea.io/reference/build_drop_mint_transaction
- https://docs.opensea.io/reference/mcp
- https://developer.android.com/training/monitoring-device-state/doze-standby
- https://firebase.google.com/docs/cloud-messaging/flutter/get-started
- https://firebase.google.com/docs/cloud-messaging/send/admin-sdk

These references informed the planning on 29 September 2026. Recheck their current behavior; do not treat this prompt as proof that a provider API presently works.
