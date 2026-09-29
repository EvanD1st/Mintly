# Independent Codex review of Mintly

Review the Mintly repository against `Mintly_Antigravity_Prompt.md` and the approved UI reference. Treat implementation claims as unverified until you inspect the code and run appropriate checks. Begin with findings, ranked by severity, with precise file locations, reproduction steps, consequences, and proposed fixes. Distinguish confirmed defects from missing live-integration evidence.

Do not broadcast mainnet transactions, spend money, transmit messages to real users, or expose credentials during this review. Use fixtures, local chains, testnet configuration where authorized, and explicit demo mode. Never ask for private keys or cookies in chat.

Review these areas:

1. **Product fidelity:** native Flutter screens reproduce the approved splash, discovery, per-stage eligibility, configuration/review, queue, activity, and wallet flows. Preview-only controls are absent from production. Demo/live modes cannot be confused.
2. **Twikit evidence:** actual diagnostic exists; package version is pinned; supported calls, complete text, mint URLs, pagination, deduplication, edits, missed posts, rate-limit backoff, and login failures are handled. Check whether a real @lakzonevn read was demonstrated. Do not infer live compatibility from mocked success.
3. **Metadata and eligibility:** chain IDs and contracts are verified; explicit allowlist membership is not guessed; unknown errors stay unknown; stale results and wallet changes invalidate readiness. OpenSea's stage choice cannot override the user's selection.
4. **Untrusted links and content:** URL fetching blocks local/private/metadata destinations across redirects and DNS resolution, limits sizes/timeouts, and never turns post content into execution authority. Imported data cannot inject arbitrary signing requests.
5. **Signing and permissions:** wallet connection is not mislabeled as automatic signing; minter, recipient, chain, contract, calldata, quantities, stage, limits, and expiry are enforced at the signer boundary. No seed collection in Flutter, secrets in builds/logs/repo, or unrestricted client-driven transaction signing. An EOA software budget is not represented as a cryptographic cap.
6. **Financial correctness:** integer arithmetic; all applicable fee components; budget reservations; ownership/idempotency; immutable authorizations; reauthorization after material changes; safe defaults; no silent stage fallback or amount escalation.
7. **Execution reliability:** worker leases, concurrent claims, nonce coordination, crash recovery, ambiguous broadcast reconciliation, same-payload retries, expiry, disarm races, sold-out handling, reverted fees, receipt finality, and reorg recovery. Check the exact crash window after broadcast and prove no duplicate mint.
8. **Mobile/backend security:** authenticated APIs/device registration, ownership enforcement, TLS configuration, token storage, input validation, no provider secrets in APKs. Background phone behavior must not control server mint timing.
9. **Build quality:** migrations and clean setup work, tests cover failure cases rather than just mocks mirroring code, dependencies are pinned, Flutter analyze/test pass, and a claimed APK actually exists and installs if a device/emulator is available.
10. **Operational truth:** unsupported adapters, missing credentials, failed checks, deferred features, and deployment requirements are clearly documented. No fixture values appear as live balances or readiness.

Run the documented checks where available. If a toolchain or credential is missing, say exactly what could not be verified and continue other review work. Do not substitute a guessed result.

After reporting findings, implement clear reversible fixes and add targeted regression coverage if authorized in this session. Keep a record of remaining decisions or live validation that require the owner. Conclude with separate readiness decisions for **demo**, **discovery/notifications**, **eligibility**, and **live automatic minting**, supported by evidence. Do not certify the whole app based only on its UI.
