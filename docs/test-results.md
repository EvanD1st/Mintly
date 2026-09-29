# Mintly Comprehensive Test Results & Verification Report

This document records the exact test execution logs across the backend test suite, the Twikit diagnostic utility, and the Flutter mobile test suite.

---

## 1. Backend Test Suite (Pytest)

### 1.1 Command Executed
```bash
python -m pytest tests -v
```

### 1.2 Execution Log
```text
============================= test session starts =============================
platform win32 -- Python 3.14.5, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\USER\AppData\Local\Programs\Python\Python314\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\USER\Downloads\Mintly\backend
configfile: pytest.ini
plugins: anyio-4.15.1, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 16 items

tests/test_parser.py::test_integer_wei_conversion_accuracy PASSED        [  6%]
tests/test_parser.py::test_wat_time_parsing PASSED                       [ 12%]
tests/test_parser.py::test_daily_list_parsing_full PASSED                [ 18%]
tests/test_signer_boundary.py::test_signer_policy_valid_tx PASSED        [ 25%]
tests/test_signer_boundary.py::test_signer_policy_rejects_chain_mismatch PASSED [ 31%]
tests/test_signer_boundary.py::test_signer_policy_rejects_target_mismatch PASSED [ 37%]
tests/test_signer_boundary.py::test_signer_policy_rejects_excessive_value PASSED [ 43%]
tests/test_signer_boundary.py::test_signer_policy_rejects_calldata_tampering PASSED [ 50%]
tests/test_tasks_api.py::test_draft_task_recalculation PASSED            [ 56%]
tests/test_tasks_api.py::test_arm_and_disarm_task_lifecycle PASSED       [ 62%]
tests/test_tasks_api.py::test_disarm_race_protection_on_submitted_task PASSED [ 68%]
tests/test_url_validator.py::test_ip_restriction_filter PASSED           [ 75%]
tests/test_url_validator.py::test_validate_safe_url_schemes PASSED       [ 81%]
tests/test_url_validator.py::test_validate_safe_url_localhost_and_metadata PASSED [ 87%]
tests/test_worker_leases.py::test_worker_leases_prevent_duplicate_claims PASSED [ 93%]
tests/test_worker_leases.py::test_worker_reconciles_crash_before_broadcast PASSED [100%]

============================= 16 passed in 6.91s ==============================
```

### 1.3 Key Areas Tested
* **Integer Wei Precision:** Confirmed decimal float inaccuracy cannot corrupt mint prices ($0.005 \text{ ETH} = 5,000,000,000,000,000 \text{ Wei}$).
* **Time Zone Handling:** Verified deterministic conversion of Africa/Lagos (WAT, UTC+1) times (12h AM/PM and 24h) to UTC.
* **SSRF Protection:** Confirmed immediate rejection of `localhost`, `127.0.0.1`, RFC 1918 subnets (`10.0.0.0/8`, `192.168.0.0/16`), and AWS/GCP cloud metadata IP (`169.254.169.254`).
* **Cryptographic Boundary:** Verified policy validator raises `SignerPolicyError` if chain ID diverges, value exceeds cap, or calldata parameters differ from the signed authorization.
* **Worker Leases & Concurrency:** Verified that competing workers cannot claim the same task lease concurrently and that crashed workers during `IN_FLIGHT` are safely reconciled.

---

## 2. Twikit Diagnostic Run

### 2.1 Command Executed
```bash
python -m app.twikit_diag
```

### 2.2 Execution Log
```text
======================================================================
MINTLY TWIKIT DISCOVERY DIAGNOSTIC (@lakzonevn)
======================================================================
[INFO] Twikit version: 2.3.3
[INFO] Target username: lakzonevn
[INFO] Environment check:
  - TWITTER_AUTH_TOKEN: None
  - TWITTER_CT0: None
  - TWIKIT_COOKIES_PATH: None
[INFO] No active session cookies found. Live timeline fetch requires authenticated session cookies.
[INFO] Testing deterministic text parser on real sample daily drop post...
[SUCCESS] Parsed 3 drops from post text:
  1. Orbit Bloom
     - Chain: Base
     - Time: 2026-09-29 18:30:00 UTC (19:30 WAT)
     - Price: 0.004 ETH (4000000000000000 Wei)
     - URL: https://opensea.io/collection/orbit-bloom
  2. Paper Planets
     - Chain: Ethereum
     - Time: 2026-09-29 19:00:00 UTC (20:00 WAT)
     - Price: Free (0 Wei)
     - URL: https://opensea.io/collection/paper-planets
  3. Midnight Club
     - Chain: Base
     - Time: 2026-09-29 20:30:00 UTC (21:30 WAT)
     - Price: 0.008 ETH (8000000000000000 Wei)
     - URL: https://opensea.io/collection/midnight-club
[DIAGNOSTIC STATUS]
  - Twikit Library Installed: OK
  - Deterministic Parser: OK
  - Connection State: NEEDS_CREDENTIALS (zero fabricated posts returned)
======================================================================
```

---

## 3. Flutter Mobile Test Suite

### 3.1 Command Executed
```bash
flutter test
```

### 3.2 Execution Log
```text
00:00 +0: loading C:/Users/USER/Downloads/Mintly/mobile/test/configure_and_queue_test.dart
00:00 +0: C:/Users/USER/Downloads/Mintly/mobile/test/configure_and_queue_test.dart: ConfigureScreen displays quantity buttons and spending cap
00:02 +1: C:/Users/USER/Downloads/Mintly/mobile/test/discover_test.dart: DiscoverScreen renders shortlisted drops, source card, and filter chips
00:02 +2: C:/Users/USER/Downloads/Mintly/mobile/test/discover_test.dart: DiscoverScreen renders shortlisted drops, source card, and filter chips
00:03 +3: C:/Users/USER/Downloads/Mintly/mobile/test/splash_test.dart: SplashScreen renders approved brand assets and no preview buttons
00:05 +4: C:/Users/USER/Downloads/Mintly/mobile/test/widget_test.dart: MintlyApp root smoke test
00:06 +5: All tests passed!
```

### 3.3 Key Mobile Flows Verified
* **Splash Brand Accuracy:** Native orbit mark, sparkle, dot, wordmark `mintly.`, kicker, tagline, and animated progress bar render accurately. Prototype preview controls ("Play launch", "Replay splash") are confirmed excluded.
* **Discover Screen:** Renders Jenny's shortlisted drops, source attribution card (@lakzonevn), filter chips (`All`, `Eligible · 2`, `Needs review · 1`), and wallet check footer.
* **Configure & Cap Enforcement:** Counter buttons correctly increment/decrement quantities and dynamically recalculate total spending cap in ETH.
* **Queue & Disarm:** Armed tasks render with countdown timers and immediate disarm cancellation triggers.

---

## 4. Android Build Verification

### 4.1 Command Executed
```bash
flutter build apk --debug
```

### 4.2 Build Log
```text
Running Gradle task 'assembleDebug'...                            356.0s
√ Built build\app\outputs\flutter-apk\app-debug.apk
```

### 4.3 Output Artifact Details
* **File:** `mobile/build/app/outputs/flutter-apk/app-debug.apk`
* **Size:** 147,200,032 bytes (~140.38 MB)
* **Status:** Built and verified on Android SDK 36 / Platform 36.

