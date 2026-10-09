# Wallet-screen private-key import

The wallet screen shows each linked wallet with one setup action. Account settings,
notifications and source status live on a separate settings page; detailed policy
information and disabling live in wallet details.

Import has two steps: verify the wallet secret locally, then choose a total ETH
budget, expiry and confirm the current Mintly password and custody consent. A
per-mint ceiling is optional under access details; blank uses the total budget.
Collections are selected automatically from the exact NFT mint the user reviews.
No contract address is entered in the import form.

A recovery phrase is accepted only on the device. A short-lived compute isolate
validates the English BIP-39 checksum and derives MetaMask Ethereum accounts at
`m/44'/60'/0'/0/index` for indices 0–19, returning only the key matching the
already-linked address. Imported MetaMask accounts from unrelated keys/phrases
need their own private key. This does not import every account or store a seed.
The phrase is never included in an HTTP request, preferences or a file. Public
Hardhat vectors are cross-checked against Python eth-account derivation.

Secret fields are masked, excluded from autofill/suggestions and cleared before
derivation/submission and on backgrounding. Seed and private-key byte buffers are
cleared when possible. String/BigInt copies and runtime memory cannot be guaranteed
to be zeroized; clipboard/keyboard/OS capture remain outside these controls.
Backgrounding invalidates a derivation already in progress and discards its result.
Importing does not arm or submit a mint; exact mint review and consent still apply.

New imports explicitly select `collection_scope: reviewed_mints`, with an empty
contract list. This mode permits collection selection through existing authenticated
mint review. The signer still decodes only pinned SeaDrop methods, checks the exact
collection, chain, recipient, quantity, price, expiry and independently enforces
budget/nonce limits. It is not a general transaction-signing API. Legacy imports
with a fixed contract remain fixed; empty lists without the explicit mode and
unknown modes fail closed. Retrying cannot switch scope or renew an allowance.

## Trusted import boundary

The app uses its existing HTTPS origin and authenticated session. Two exact paths
are routed by the TLS proxy directly to the dedicated `app.custody_import` service:

- `GET /api/automatic/import/config`: exposes the configured chain only when ready
  for imports. If unavailable, the screen never presents a key-entry field.
- `POST /api/automatic/import`: bounded 4 KiB body, no secret-bearing validation
  errors, password reauthentication, five attempts per user per 15 minutes,
  ownership/key-address verification and explicit limits. Legacy fixed-contract
  imports also check deployed collection code; task-selected collections are
  validated by the mint preparation and signer.

The ordinary API and worker receive no key. The TLS terminator and import process
do receive plaintext transiently and are trusted key-handling infrastructure.
The import process has a writable vault and the independent password mount; the
signer retains a read-only vault and sole access to its durable signing journal.
V3 keystores use scrypt N=262144 and exclusive mode-0600 writes. Policies pin
existing EIP-7702 delegation code when applicable. No key is returned to the app.

The import request UUID is reused during retries. Existing matching requests
return the original policy without resetting its budget or re-enabling it. Changed
limits under that UUID are rejected. Durable key/policy files survive DB/response
failures for retry reconciliation; partial orphan files require protected operator
cleanup if abandoned. An interrupted user should refresh policy status before
starting a new import, which would intentionally create a separate allowance.

## Deployment required

The backend import service is deployed as of 3 October 2026. No real wallet key
was imported during verification. Task arming and the spending worker remain
disabled. Keep the regular API without vault mounts. Deployment requirements:

1. Use the custody overlay's separate `custody-import` profile. Its listener is
   bound to host loopback port 18768, not a public interface. It runs nonroot with
   read-only root filesystem, no extra capabilities, no core dumps, one concurrent
   import, and a writable protected vault mount. Provision the vault directory and
   password as documented in [custody setup](automatic-custody.md).
2. The live host uses Caddy: `deploy/setup-custody-caddy.sh` installs the two exact
   import routes while preserving other sites. For Nginx hosts, include
   `backend/custody-import.nginx.conf` inside the existing HTTPS server
   block. It routes only the two exact paths, disables import body buffering,
   caching and access logging, limits request size, and sets forwarded HTTPS.
   The import process rejects non-HTTPS production requests. Forwarded headers
   are trusted only because access is restricted to the host proxy/private network;
   never expose that listener publicly or bridge an untrusted network to it.
3. Do not enable request-body logging, APM payload capture, proxy disk buffering
   or exception-local capture anywhere on the import route. TLS termination must
   be on the trusted host; remote hops require authenticated encrypted transport.
4. Configure the same chain/RPC on API, signer, worker and import service.
   Robinhood requires its additional explicit opt-in. Verify the authenticated
   config route, encrypted-file permissions and signer readiness before use.

The server and its administrators possess full key authority. Encryption and
software limits do not protect a compromised running key-handling process or
constrain a stolen key on other chains. Disabling a policy stops future Mintly
signing; it neither deletes custody nor retracts an already signed transaction.
No production security audit or real mainnet execution is claimed.

## Verification on 2026-10-02

- Full backend suite: 157 passed in 250.57 seconds with real local EVM enabled.
- After final ingress and unlink guards: 14 selected wallet/import tests passed
  in 38.29 seconds, including import → encrypted storage → unattended SeaDrop mint.
- Full Flutter suite: 13 passed. Final import-focused suite: 3 passed, including
  rejecting an unverified success response and clearing secrets on failure.
- Flutter analysis and final targeted Dart analysis: no issues. Compose YAML
  isolation assertions and diff whitespace checks passed. Docker/Nginx runtime
  deployment was not exercised in that local test run. Subsequent live deployment
  and staging state are recorded in [deployment notes](deployment-ubuntu.md).

## Simplified import verification on 2026-10-03

- 51 custody/security and real local EVM tests passed in 186.83 seconds, including
  import → encrypted keystore → reviewed-collection mint and legacy fixed scope.
- All 19 Flutter tests passed. Coverage includes independent phrase/account
  vectors, server request containing only the matched account key, stale
  derivation discard after backgrounding, and a phone-width setup flow.
- Flutter analysis passed with no issues. Backend import configuration advertises
  `automatic_collection_selection`; an old/unavailable ingress never presents a
  secret entry field in the new app.
