# Mintly Codex Review Handoff & Architecture Map

This document is prepared for the independent Codex reviewer. It provides a file-by-file map matching every requirement in `Mintly_Codex_Review_Prompt.md`, documents verified behaviors and tests, and highlights areas for live verification.

---

## 1. Architectural Overview & Component Map

| Layer | Path | Core Responsibilities |
| :--- | :--- | :--- |
| **Mobile Client** | `mobile/lib/` | Pure native Flutter Android client (Material 3 tokens, Riverpod state, zero WebView, zero seed collection). |
| **Backend API** | `backend/app/api/` | REST endpoints for drops, import, task arming/disarming, wallet query, activity log. |
| **Data Models & DB**| `backend/app/models/` | Async SQLAlchemy models for wallets, posts, drops, authorizations, tasks, activity journal. |
| **Signer Boundary**| `backend/app/services/signer/` | Cryptographic policy validator: enforces calldata, contract, recipient, integer Wei spending caps, chain IDs before signing. |
| **Mint Executor** | `backend/app/services/mint_executor.py` | Two-phase transaction submission, calldata encoding/decoding, crash reconciliation. |
| **Background Worker**| `backend/app/worker.py` | Lease-locked task execution (`worker_id`, `lease_expires_at`), stage timing triggers, auto-recovery. |
| **Discovery Adapter**| `backend/app/twikit_diag.py` & `backend/app/services/parser.py` | Twikit integration diagnostic and deterministic WAT-aware text parser. |
| **SSRF Security** | `backend/app/services/url_validator.py` | DNS-resolved IP filtering blocking loopback, RFC 1918, link-local metadata across redirects. |

---

## 2. Checklist Against Codex Review Requirements

### Area 1: Product Fidelity
* **Files:** `mobile/lib/screens/`
  * `splash_screen.dart`: Native orbit logo (rotated container), sparkle, dot, wordmark `mintly.`, kicker, tagline, progress bar. **No prototype preview controls** ("Play launch" or "Replay splash" are completely absent).
  * `discover_screen.dart`: Shortlist card, source attribution card (`@lakzonevn`), filter chips (`All`, `Eligible · 2`, `Needs review · 1`), wallet check footer.
  * `drop_detail_screen.dart`: Hero artwork, stage schedule, wallet eligibility, "Set up mint" / "Automatic mint unavailable", "View mint page ↗".
  * `configure_screen.dart`: Quantity counter, wallet selection, fee input, dynamic total cap recalculation.
  * `review_screen.dart`: Limits breakdown table, explicit consent checkbox, "Arm demo mint" button.
  * `queue_screen.dart` & `activity_screen.dart`: Armed task list with disarm buttons, and immutable activity journal.
  * `wallet_screen.dart`: Jenny's wallet card with explicit **Demo** badge.
* **Separation of Modes:** Demo mode is prominently badged throughout the UI and on the action buttons. Demo results are never silently substituted for live transactions.

### Area 2: Twikit Evidence & Upstream X Handling
* **Files:** `backend/app/twikit_diag.py`, `backend/app/services/parser.py`
* **Version:** Pinned to `twikit==2.3.3`.
* **Diagnostic Execution:** Standalone diagnostic (`python -m app.twikit_diag`) validates environment tokens, cookie loading paths, and handles missing sessions with an explicit `NEEDS_CREDENTIALS` state.
* **Upstream Issues Documented:** Explicitly accounts for timeline endpoint changes (issue #425, #433), rate limits (HTTP 429), and login challenges (issue #414).
* **Zero Fabrication Policy:** When unauthenticated or rate limited, Mintly never fabricates fake tweets. The UI clearly displays `needs_credentials` or `rate_limited`, and provides the manual post text import fallback screen (`import_screen.dart`).

### Area 3: Metadata and Eligibility
* **Files:** `backend/app/services/opensea_client.py`
* **Verified Chains:** Ethereum Mainnet (`1`), Base (`8453`), Sepolia (`11155111`), Base Sepolia (`84532`).
* **Canonical SeaDrop:** `0x00005EA00Ac477B1030CE78506496e8C2dE24bf5`.
* **Eligibility Logic:**
  * Checks public drop stage parameters (`startTime`, `endTime`, `mintPrice`, `maxTotalMintableByWallet`).
  * Compares user minted count against per-wallet maximums.
  * Evaluates wallet balance against `mintPrice * quantity + maxFee`.
  * Explicitly flags Allowlist stages as "Needs Review" / "Manual Mint Required" rather than guessing merkle proofs or private keys.

### Area 4: Untrusted Links & SSRF Protection
* **Files:** `backend/app/services/url_validator.py`, `backend/tests/test_url_validator.py`
* **Pre-Fetch Verification:** Hostnames are resolved to IP addresses via DNS *prior* to connection.
* **Blocked IP Ranges:**
  * Loopback (`127.0.0.0/8`, `::1`)
  * RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`)
  * Link-local / Cloud Metadata (`169.254.169.254`, `fe80::/10`)
* **Redirect & Size Limits:** Every redirect hop is re-validated against the IP blocklist; response payload is capped at 512 KB.

### Area 5: Signing and Permissions
* **Files:** `backend/app/services/signer/base.py`, `backend/app/services/signer/local_signer.py`
* **Policy Enforcement Before Signing:**
  * Verifies `chain_id` matches authorization.
  * Verifies `to` address matches canonical SeaDrop address.
  * Verifies `tx['value'] <= authorization.max_total_wei`.
  * Verifies `gas * gas_price <= authorization.max_fee_wei`.
  * Unpacks calldata: validates method selector (`0x83e387c2`), verifies `nftContract`, `minterIfNotPayer`, and `quantity` match authorization records exactly.
* **Isolation Guarantee:** Mobile client never handles, transmits, or stores private keys or seeds. Keys reside only on the backend (or KMS vault) behind the policy validator.

### Area 6: Financial Correctness
* **Files:** `backend/app/services/parser.py`, `backend/app/services/mint_executor.py`, `backend/tests/test_parser.py`
* **Exact Integer Arithmetic:**
  * Zero floating point storage or arithmetic for cryptocurrency amounts.
  * All prices and caps are stored and manipulated as integer Wei (`10^18` Wei = 1 ETH).
  * Example: `0.004 ETH` parsed strictly as `4000000000000000` Wei.
* **Immutable Authorization:**
  * Once armed, the `mint_authorizations` record is immutable.
  * Any user modification to quantity, wallet, or max fee requires disarming and re-authorizing with a new authorization record.

### Area 7: Execution Reliability & Worker Leases
* **Files:** `backend/app/worker.py`, `backend/app/services/mint_executor.py`, `backend/tests/test_worker_leases.py`
* **Lease Locking:** Workers acquire tasks using database lease locks (`worker_id`, `lease_expires_at`). Competing workers cannot claim the same task concurrently.
* **Disarm Race Protection:** Disarming is atomic. If a task is already `IN_FLIGHT` or `SUBMITTED`, disarming is rejected with an HTTP 409 conflict to prevent double-spend or orphaned on-chain state.
* **Crash Recovery:** Tasks in `IN_FLIGHT` with expired leases are inspected by the recovery supervisor. If no transaction hash was recorded, the task safely transitions to `FAILED_EXPIRED`. If a transaction hash was broadcast, the worker queries on-chain receipts before retrying.

### Area 8: Mobile/Backend Security
* **Files:** `mobile/lib/services/api_service.dart`, `backend/app/main.py`
* **CORS & Headers:** Backend restricts CORS headers.
* **No Provider Secrets:** Zero RPC secret keys or signer private keys bundled in Flutter Dart code or Android Gradle scripts.
* **Server Authority:** The background worker runs server-side on its own clock; mobile device sleep or background throttling cannot disrupt or miss mint execution windows.

### Area 9: Build Quality & Test Coverage
* **Backend Tests:** 16 tests passing in `pytest` (`test_parser.py`, `test_signer_boundary.py`, `test_tasks_api.py`, `test_url_validator.py`, `test_worker_leases.py`).
* **Mobile Tests:** 5 widget tests passing in `flutter test` (`configure_and_queue_test.dart`, `discover_test.dart`, `splash_test.dart`, `widget_test.dart`).
* **Database Migrations:** Clean Alembic migration `backend/alembic/versions/001_initial_schema.py`.
* **Containerization:** Production Dockerfile and `docker-compose.yml` for PostgreSQL, Redis, backend, and worker.

### Area 10: Operational Truth & Certification
* **Readiness Decisions:**
  1. **Demo Mode:** `READY` (full UI flow, simulated execution, zero real funds required).
  2. **Discovery & Notifications:** `CONDITIONAL` (deterministic parser verified; live automated Twitter fetching requires injecting active user session cookies).
  3. **Eligibility Checking:** `READY` (contract logic, public drop checks, and balance validations implemented for SeaDrop V1).
  4. **Live Automatic Minting:** `BLOCKED BY INTENT` (safe default `ALLOW_LIVE_BROADCAST=False` actively prevents mainnet fund loss; testnet verification ready for Sepolia / Base Sepolia).
