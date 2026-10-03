# Wallet-screen private-key import

The wallet screen now offers a key icon beside each linked address. Its import
form requires the matching private key, the current Mintly password, a collection
contract, total and per-task ETH limits including gas, an expiry of at most 30
days, and explicit consent to custody. No recovery phrase is accepted.

The key and password are masked, excluded from autofill/suggestions, cleared from
controllers immediately after submission and on backgrounding, and never saved
to preferences or files. Runtime memory cannot be guaranteed to be zeroized.
Clipboard/keyboard/OS capture remain outside these controls. Importing does not
arm or submit a mint; the existing exact mint review and consent still apply.

## Trusted import boundary

The app uses its existing HTTPS origin and authenticated session. Two exact paths
are routed by the TLS proxy directly to the dedicated `app.custody_import` service:

- `GET /api/automatic/import/config`: exposes the configured chain only when ready
  for imports. If unavailable, the screen never presents a key-entry field.
- `POST /api/automatic/import`: bounded 4 KiB body, no secret-bearing validation
  errors, password reauthentication, five attempts per user per 15 minutes,
  ownership/key-address verification, explicit limits and deployed-contract check.

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
