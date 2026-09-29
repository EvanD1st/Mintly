# Mintly — Personal NFT Discovery & Scheduled Minting App

Mintly is a personal NFT discovery and scheduled minting application designed for Jenny, featuring an elegant native Flutter mobile application, an asynchronous Python (FastAPI) orchestration backend, and a lease-locked execution worker with an isolated cryptographic signer boundary.

---

## 🌟 Key Features

1. **Native Flutter Android Client:**
   - Faithfully implements the approved design tokens and layout (`design/mintly-splash-reference.html`).
   - Pure native widgets — zero WebViews for core flows.
   - 4-tab shell: **Today** (curated drop shortlist & source attribution), **Queue** (armed tasks & disarm controls), **Activity** (event audit log), and **Wallet** (wallet details, time zones, notification preferences).
   - Dedicated Drop Details, Configure Mint, and Review Authorization screens with dynamic spending cap recalculation.
   - Clean separation of **Demo** vs. **Live** modes.
   - Production splash screen without prototype preview controls.

2. **Deterministic Discovery & Parsing:**
   - Twikit diagnostic adapter for daily drop calendars (targeting `@lakzonevn`).
   - Time zone awareness: converts Africa/Lagos (WAT, UTC+1) drop times to UTC.
   - Exact integer arithmetic: converts decimal ETH prices to integer Wei (`10^18` Wei = 1 ETH) to eliminate floating point inaccuracies.
   - Zero-fabrication guarantee: when unauthenticated or rate-limited, no synthetic tweets are generated.

3. **Isolated Cryptographic Signer Boundary:**
   - Signing authority is decoupled from application logic.
   - Policy validator enforces chain IDs, target contract (`0x00005EA00Ac477B1030CE78506496e8C2dE24bf5`), recipient, value caps, and calldata before any signature is produced.
   - Safe defaults: `ALLOW_LIVE_BROADCAST=False` actively prevents accidental mainnet transactions or fund loss.
   - Zero private keys or seeds stored in mobile code or databases.

4. **Durable Worker & Execution Reliability:**
   - Database lease locks (`worker_id`, `lease_expires_at`) prevent duplicate task claims.
   - Atomic disarm protection prevents cancelling tasks that are already in-flight.
   - Post-crash reconciliation validates on-chain state before retrying transactions.

5. **SSRF-Protected Ingress:**
   - Pre-fetch DNS IP resolution blocks loopback (`127.0.0.1`), RFC 1918 private subnets (`10.0.0.0/8`, `192.168.0.0/16`), and cloud metadata services (`169.254.169.254`) across all redirect hops.

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- **Python:** 3.11+ (tested on Python 3.14)
- **Flutter SDK:** 3.24+ (tested on Flutter 3.44.8 / Dart 3.12.2)
- **Android SDK:** Platform 34+ / Build-Tools 36.0.0
- **Optional:** Docker & Docker Compose

---

### 2. Backend Setup & Local Run

Navigate to the `backend` directory:
```bash
cd backend
```

Create and activate a virtual environment (if not already done):
```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

Initialize the database and run migrations:
```bash
alembic upgrade head
```

Run the FastAPI development server:
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Run the background execution worker in a separate terminal:
```bash
python -m app.worker
```

Run the Twikit discovery diagnostic tool:
```bash
python -m app.twikit_diag
```

---

### 3. Docker Compose Deployment

To run the entire backend stack (FastAPI backend, background worker, PostgreSQL, Redis) with a single command:

```bash
cd backend
docker-compose up --build -d
```

Check service logs:
```bash
docker-compose logs -f backend worker
```

---

### 4. Running Tests

#### Backend Test Suite (Pytest)
```bash
cd backend
python -m pytest tests -v
```
*Executes 16 unit and integration tests covering parser accuracy, signer policy boundary, URL validator SSRF checks, task API lifecycle, and worker lease concurrency.*

#### Mobile Test Suite (Flutter)
```bash
cd mobile
flutter test
```
*Executes widget tests verifying the splash screen, discover shortlist, configure modal, queue, and application smoke tests.*

---

### 5. Building & Running the Mobile App

Navigate to the `mobile` directory:
```bash
cd mobile
```

To run in debug mode on an Android device or emulator:
```bash
flutter run
```

To build a standalone debug APK:
```bash
flutter build apk --debug
```
*The resulting APK is located at: `mobile/build/app/outputs/flutter-apk/app-debug.apk`.*

---

## 📁 Repository Structure

```text
Mintly/
├── .env.example                     # Sample environment configuration
├── README.md                        # Project documentation & setup guide
├── Mintly_Antigravity_Prompt.md     # Primary specification
├── Mintly_Codex_Review_Prompt.md    # Independent review guide
├── backend/                         # Backend Python services
│   ├── alembic/                     # Database migrations
│   ├── app/
│   │   ├── api/                     # REST API endpoints
│   │   ├── models/                  # SQLAlchemy ORM models
│   │   ├── schemas/                 # Pydantic validation schemas
│   │   ├── services/
│   │   │   ├── mint_executor.py     # Calldata encoder & execution
│   │   │   ├── notifier.py          # Push notification client
│   │   │   ├── opensea_client.py    # SeaDrop V1 integration
│   │   │   ├── parser.py            # WAT & Wei deterministic parser
│   │   │   ├── seed.py              # Initial reference drop seed
│   │   │   ├── url_validator.py     # SSRF DNS IP filter
│   │   │   └── signer/              # Isolated cryptographic boundary
│   │   ├── twikit_diag.py           # Twikit discovery diagnostic
│   │   ├── worker.py                # Lease-locked background worker
│   │   ├── config.py                # Environment configuration
│   │   ├── database.py              # Async database engine
│   │   └── main.py                  # FastAPI application entrypoint
│   ├── tests/                       # Pytest test suite (16 tests)
│   ├── Dockerfile                   # Container definition
│   └── docker-compose.yml           # Multi-service composition
├── design/                          # Design assets & HTML references
│   └── mintly-splash-reference.html # Approved UI layout & tokens
├── docs/                            # In-depth architectural documentation
│   ├── codex-handoff.md             # Reviewer guide & architecture map
│   ├── integration-status.md        # Twikit & SeaDrop technical status
│   ├── security-and-signing.md      # Signer boundary & safety models
│   └── test-results.md              # Test execution transcripts
└── mobile/                          # Flutter Android mobile client
    ├── lib/
    │   ├── models/                  # Dart data models
    │   ├── screens/                 # Native UI screens (all flows)
    │   ├── services/                # API client & demo fallback
    │   ├── state/                   # Riverpod state management
    │   └── theme/                   # Material 3 colors & theme
    └── test/                        # Flutter widget tests (5 tests)
```

---

## 🛡️ Security Guarantees & Operational Readiness

| Capability | Status | Implementation Details |
| :--- | :--- | :--- |
| **Demo Minting** | ✅ `READY` | Full mobile flow, simulated execution, zero real funds spent. |
| **Discovery & Parsing** | ⚠️ `CONDITIONAL` | Deterministic WAT/Wei parsing verified; live automated Twitter fetching requires session cookies. |
| **Eligibility Checking**| ✅ `READY` | OpenSea SeaDrop V1 checks and wallet balance validation implemented. |
| **Live Mainnet Minting**| 🛑 `BLOCKED BY INTENT`| Safe default `ALLOW_LIVE_BROADCAST=False` actively prevents fund spending. Testnet ready for Sepolia / Base Sepolia. |
