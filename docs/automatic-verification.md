# Automatic execution verification — 2 October 2026

## Update — 4 October 2026

Production Robinhood automation is explicitly activated. Mint plans now arm
reviewed exact-stage tasks; Remove archives records and safely cancels unsigned
work; Settings → History paginates all versions, approvals and receipts.
The final full backend suite passed **178 tests in 204.97 seconds**, with real local
EVM execution enabled and no skips. Flutter passed **23 tests** and analysis;
the OTA guard passed **10 tests**. The final suite includes
**10 recovery tests**, covering reverted receipts and expired
original submission windows. The local consent clock follows the deliberately
advanced test chain; production retains real wall-time and chain expiry checks.

The real owner-approved Robinhood test minted NFT #316 using nonce 7, for
0.000039195327232 ETH including gas. The separately approved recovery preserved
the same NFT call, recipient, value and finite debit ceiling. Both signatures
remain in the protected journal and app history. [Live receipt evidence](automatic-mainnet-proof-2026-10-04.json)
records receipt status, token ownership, finality and single-reservation accounting.

The sections below record the earlier 2 October verification and its limits.

## Outcome

The explicitly provisioned **custodial** route performs unattended SeaDrop public,
Merkle allowlist and signed-presale mints from the imported EOA on a real local EVM.
The authenticated API arms a future task; after opening the scheduler signs,
broadcasts and confirms without further client input. Receipts, sender, token
ownership, total supply, exact debit and reserved/spent budget are asserted.
A separate Uvicorn signer process is exercised, not just an injected mock signer.

The real MetaMask extension probe did **not** establish an NFT-call permission.
Custody was an explicit subsequent user choice. These tests are not a substitute
for a wallet grant proof or live testnet run. No user key, production deployment,
mainnet transaction or real funding was involved.

## Commands and measured results

The subsequent [wallet import feature](wallet-key-import.md) passed the full
backend suite (157 tests), then 14 focused wallet/import checks after final guards.
Flutter's full 13-test suite and final three import tests passed; analysis was clean.

After the Robinhood/EIP-7702 signer fix, the full backend suite was rerun with
`MINTLY_TEST_RPC=http://127.0.0.1:18545`: **148 passed in 190.95s, no skips**.
The focused adapter/execution suite passed **39 tests in 100.00s**. See
[adapter evidence and live limitations](robinhood-signer-adapter.md).
The earlier PostgreSQL and Flutter results below predate that backend-only fix.

Executed on Windows with Python 3.14, Flutter 3.44.8, Hardhat 3.1.8 and a temporary
local PostgreSQL 17.11 instance. CI remains pinned to Python 3.12 and PostgreSQL
16; the updated CI workflow has not been run remotely in this session.

| Working directory | Command | Result |
|---|---|---|
| `backend` | `$env:MINTLY_TEST_RPC='http://127.0.0.1:18545'; python -m pytest tests -q --tb=short` | **128 passed**, 171.28s; no skips |
| `backend` | `python -m pytest tests/test_automatic_evm.py -q -x --tb=short` with that RPC and `MINTLY_TEST_DATABASE_URL` pointing to the local PostgreSQL test database | **25 passed**, 97.78s, including checked EVM snapshot restoration |
| `backend` | `node --test tests/wallet-capabilities.browser.cjs` | **1 passed** |
| `backend` | `python -m pytest tests/test_custody_security.py -q --tb=short` after final secret-file hardening | **8 passed**, 3.11s |
| `mobile` | `flutter test --no-pub` | **11 passed** |
| `mobile` | `flutter test --no-pub test/automatic_review_test.dart test/queue_test.dart` after final review-hash assertion/copy change | **2 passed** |
| `mobile` | `flutter analyze --no-pub` | **No issues found**, 5.8s |
| repository | `git diff --check` | Passed after documentation whitespace cleanup |
| repository | PyYAML parse of base Compose, custody overlay and CI workflow | Parsed successfully; this is not a Docker runtime test |

The full backend run includes fresh and upgrade Alembic migration tests,
existing account/auth/discovery/permission regressions, eight custody boundary
checks and 25 new automatic execution cases. PostgreSQL tests use separate API,
signer and worker sessions; the signer subprocess opens another connection.
The PostgreSQL run initially exposed an insert-order issue hidden by SQLite's
foreign-key defaults; authorization is now flushed before inserting its task.
The final log review also caught Hardhat 3 rejecting an unchecked legacy reset
call. Automatic fixtures now check `evm_snapshot`/`evm_revert` responses. A separate
regression check ensures container provisioning treats `/app` as the code root,
rather than incorrectly rejecting every external vault path beneath `/`.

## Behaviors exercised

- Future authenticated arming, no early signing, real public/allowlist/signed
  mint, exact sender/recipient and no second mint after confirmation.
- Owner isolation, duplicate taps/retries, changed idempotency requests,
  concurrent budget reservations and distinct-task nonce coordination.
- Cancellation against signing under the same transaction lock, policy disable,
  expiry, insufficient funds, gas-cap rejection, invalidated Merkle root,
  changed upstream/on-chain stage and wrong keystore address.
- Independent policy rejection after DB contract, chain or budget tampering.
  Mainnet and all unimplemented L2 chain IDs fail closed.
- Crash/restart after signing; journal recovery when the app DB loses the signed
  record; accepted-then-timeout broadcast with identical hash/bytes/nonce.
- External wallet nonce consumption; concurrent workers do not mint twice.
- Reorg of an unconfirmed receipt and recovery with the same signed bytes.
- Real reverted transaction and free mint: actual gas is charged and maximum
  budget reservation released only after canonical confirmation.
- Review hash blocks changed stage metadata between preview and arm.
- Notification failure retains pending delivery, concurrent status changes are
  not acknowledged accidentally, and delivery targets the owning user.
- Flutter shows exact address/stage/limits, suppresses success on HTTP failure,
  blocks a duplicate tap and preserves the same request/idempotency key for retry.
- Browser capability script sends explicit empty JSON-RPC parameters and never
  requests spending permission.

The EVM fixtures deploy real compiled SeaDrop and a test NFT, place SeaDrop at its
expected local address and use ephemeral keys/test balances. Local-only Hardhat
state controls open stages and create reorgs. The OpenSea presale **data provider**
is replaced with valid fixture proofs/signatures; the signer, EVM execution,
receipt, gas accounting and NFT state are real. This proves the execution path,
not availability or latency of the live OpenSea provider.

## Reproduce locally

Use a disposable local chain: the automatic fixture snapshots and restores EVM
state for each test and checks both RPC responses. Do not run
two test suites against that node concurrently. All network-bearing execution
tests require a loopback RPC that reports chain ID 31337.

Terminal 1, from `backend/tests/evm`:

```powershell
npm ci --ignore-scripts --no-audit --no-fund
node node_modules/hardhat/dist/src/cli.js node --hostname 127.0.0.1 --port 18545
```

Terminal 2, from `backend`:

```powershell
python -m pip install -r requirements.txt
$env:MINTLY_TEST_RPC='http://127.0.0.1:18545'
python -m pytest tests -q --tb=short
node --test tests/wallet-capabilities.browser.cjs
```

For PostgreSQL, create a disposable loopback database named `mintly_test` and
provide its connection URL through `MINTLY_TEST_DATABASE_URL`. The fixture drops
and recreates its schema. It rejects nonlocal PostgreSQL hosts and database names
without the `mintly_test` prefix. Do not point it at application data.

```powershell
# TEST_DATABASE_URL is supplied locally; do not print production credentials.
$env:MINTLY_TEST_DATABASE_URL=$env:TEST_DATABASE_URL
python -m pytest tests/test_automatic_evm.py -q --tb=short
Remove-Item Env:MINTLY_TEST_DATABASE_URL
```

The CI workflow provides an isolated PostgreSQL service on port 15432 and repeats
all automatic cases after the full SQLite run. From `mobile` run:

```powershell
flutter pub get
flutter analyze --no-pub
flutter test --no-pub
```

## Changes by area

| Area | Files |
|---|---|
| API and immutable intent | `backend/app/api/tasks.py`, `api/automatic.py`, `api/__init__.py`, `schemas/task.py`, `services/automatic.py` |
| Isolated custody and provisioning | `backend/app/services/custody.py`, `services/automatic_signer.py`, `app/provision_custody.py` |
| Independent execution and notifications | `backend/app/automatic_worker.py`, `automatic_notifications.py`, legacy exclusions in `worker.py` and `services/mint_executor.py` |
| Durable storage | `backend/app/models/automatic.py`, `models/task.py`, `models/__init__.py`, `backend/alembic/versions/007_automatic_execution.py` |
| Deployment and guards | `backend/app/config.py`, `backend/docker-compose.yml`, `docker-compose.custody.yml`, `.env.custody.example`, `.dockerignore`, `.github/workflows/ci-cd.yml`, `.gitignore` |
| Actual-wallet probe | `backend/app/main.py`, `app/web/wallet-capabilities.html`, `wallet-capabilities.js`, browser regression test |
| Flutter | `automatic_review_screen.dart`, `wallet_screen.dart`, `drop_detail_screen.dart`, `queue_screen.dart`, `main_shell.dart`, `models/drop_model.dart`, `services/api_service.dart` |
| Verification | `backend/tests/test_automatic_evm.py`, `test_custody_security.py`, `conftest.py`; Flutter review and queue tests |
| Documentation | `README.md`, this report, `automatic-custody.md`, `security-and-signing.md`, current wallet/permissions/deployment guides |

## Remaining external setup and limits

No production or Sepolia deployment was executed. Docker is unavailable in this
workspace, so container isolation/healthchecks are configuration and code review,
not a running container penetration test. Linux file ownership/symlink enforcement
is implemented and covered conditionally in CI, but this local run was Windows.
The portable PostgreSQL server and Hardhat node are local test helpers only.

A real Sepolia demonstration still needs explicit key provisioning, verified
test collection/stage data, gas funding already supplied by the user, and
configuration of the isolated services. Sepolia public execution is supported in
code; live provider-backed testnet presales are unproven. Mainnet/L2 execution,
arbitrary contract adapters, mobile MetaMask grants and hardware-backed key
custody are unsupported. Firebase device delivery and real X/OpenSea service
credentials require external setup. See [the setup guide](automatic-custody.md)
for exact boundaries, limits, backup/renewal procedures and uncertainty handling.

The implementation gives the signer full wallet key authority protected by
software and host controls. It is neither risk-free custody nor an on-chain
mint-only permission, and has not received an independent security audit.
