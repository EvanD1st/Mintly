# Automatic minting with explicit server custody

This route follows the user's October 2026 decision to store a wallet key on the
server. It preserves the imported address and its allowlist identity. It does
**not** establish a MetaMask permission or an on-chain spending limit. Local EVM
execution is demonstrated. On 4 October 2026 the owner imported the linked wallet
through the isolated service and explicitly activated Robinhood automation.
An authorized one-NFT mainnet test was signed; its initial submission has no
receipt. A separately approved same-nonce recovery preserves the USD 0.50 cap.
Current execution evidence is recorded separately when a receipt is available.

## What works and what is excluded

| Network and method | Implementation / evidence |
|---|---|
| Local EVM 31337, SeaDrop V1 ERC-721 public | Real authenticated API → separate signer → scheduler → receipt and ownership tests |
| Local EVM 31337, Merkle allowlist and signed presale | Real SeaDrop verifies proofs/signatures; test provider supplies wallet-specific calldata |
| Ethereum Sepolia 11155111, public | Explicit HTTPS RPC configuration supported; needs a verified SeaDrop collection and real testnet run |
| Ethereum Sepolia presales | Validator exists, but no live testnet presale provider is configured/proven; do not claim operational support |
| Robinhood 4663 | Explicitly activated; Nitro total fees, finalized receipt checks, pinned EIP-7702 direct signer. One-NFT mainnet proof pending receipt. |
| Ethereum mainnet, Base, Arbitrum, Optimism and other L2s | Automatic execution rejected; their adapters are unimplemented |
| Arbitrary project contracts, ERC-1155 and arbitrary smart accounts | Unsupported; no generic calldata signing route |

Existing discovery still reads @lakzonevn through Twikit and administrator imports.
The independent discovery worker cannot authorize spending. Most discovered
mainnet drops remain manual unless their chain and custody policy are explicitly supported.
Do not change a mainnet drop's chain identifier to make it appear supported.

## MetaMask evidence

The user ran the read-only `/wallet-capabilities` page on October 1, 2026 using
**MetaMask extension 13.48.0**, account
`0x5f1a65c4c3011eb22c2882c3e9ea8299f42ccf7e`, chain `0x1237` (4663).
The actual `wallet_getSupportedExecutionPermissions` response advertised native
and ERC-20 allowance/periodic/stream permissions plus token approval revocation,
including Robinhood and Sepolia. Thus the older documentation omission of
Robinhood is not evidence that this extension lacks those token permissions.

The native allowance [implementation](https://github.com/MetaMask/smart-accounts-kit/blob/main/packages/7715-permission-types/src/permissions/caveats/nativeTokenAllowance.ts)
adds `ExactCalldataEnforcer` with empty calldata. That does not authorize a SeaDrop
mint call. The report's atomic account capability is also not unattended signing
authority. No spending permission was requested and no backend NFT redemption was
proven. The custom delegation/account-domain experiments remain blocked.
MetaMask mobile was not tested; extension results do not establish mobile support.

References checked during investigation: [permission types](https://docs.metamask.io/smart-accounts-kit/get-started/supported-advanced-permissions/),
[networks](https://docs.metamask.io/smart-accounts-kit/get-started/supported-networks/),
[capability discovery](https://docs.metamask.io/smart-accounts-kit/guides/advanced-permissions/get-supported-permissions/),
[native token permissions](https://docs.metamask.io/smart-accounts-kit/guides/advanced-permissions/use-permissions/native-token/),
and [signature validation](https://github.com/MetaMask/core/blob/main/packages/signature-controller/src/utils/validation.ts).
The probe includes `params: []`; its browser regression test catches the initial
missing-parameter error. A connected OpenSea tab still needs MetaMask signatures
and cannot provide unattended authority by itself.

## Trust and secret boundaries

Read [security-and-signing.md](security-and-signing.md) before provisioning.
The signer receives full authority over the imported key on every compatible
chain; a software chain allowlist cannot limit a stolen private key. Encryption
protects stored keystore files, not a running compromised signer that has the
decryption secret. This implementation is not HSM-backed or externally audited.

- The ordinary API and worker receive only addresses, policy metadata and task IDs.
  The [wallet import screen](wallet-key-import.md) handles keys transiently and sends
  them over HTTPS to a separate trusted import service. No seed phrase or local
  key persistence is used.
- The operator uses a masked interactive terminal on the signer host. Provisioning
  checks the key against an already linked, authenticated user's exact address.
  It requires an address acknowledgment, finite budget, per-task cap, allowed
  contracts/methods and explicit expiry. It never silently creates another wallet.
- Ethereum V3 keystores use scrypt with `N=262144`. Password and service token are
  separate random secret files. Linux files are exclusively created with mode
  0600; reads reject symlinks, nonregular files, other owners and broad permissions.
- The signer mounts the keystores, password and durable signing journal. The
  dedicated import service also mounts the vault (writable) and password, but
  never the signing journal.
  Signer policy files are independently provisioned and their hashes are bound
  to database metadata. The journal tracks maximum liabilities independently of
  mutable application budget counters.
- The worker has only a scoped service token. Its signing request is a saved task
  ID; the signer independently loads and validates authorization and calldata.
  Signed transactions are broadcastable, so the application database and its
  backups still require protection even though they contain no private keys.

## Linux testnet service setup

These are operator instructions, **not actions performed by this change**. Use a
dedicated testnet key first. The default deploy workflow does not load the custody
overlay and forces `ENABLE_CUSTODIAL_AUTOMATIC=false`.

1. Prepare the normal authenticated Mintly deployment and migrate to revision
   `007_automatic_execution` (`alembic upgrade head`). Keep `DEBUG=false`.
2. Reserve service UID/GID 10001 for the signer. Create separate directories,
   owned by that UID/GID and mode 0700, outside the repository:
   `/srv/mintly-custody/{vault,password,token,journal}`. The journal must be on
   persistent local storage, not tmpfs or an ephemeral container layer.
3. Generate independent secrets directly into files without printing them. Run
   this as UID 10001 on the signer host, after creating those directories:

   ```python
   import os, secrets
   from pathlib import Path
   for name, filename in [('password', 'password'), ('token', 'token')]:
       path = Path('/srv/mintly-custody') / name / filename
       fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
       with os.fdopen(fd, 'w') as f:
           f.write(secrets.token_urlsafe(48))
           f.flush()
           os.fsync(f.fileno())
   ```

4. Add the non-key settings in `backend/.env.custody.example` to the protected
   operator environment. Set a verified HTTPS **Ethereum Sepolia** RPC and the
   four directory paths. Keep the existing strong app and PostgreSQL secrets.
   `MINTLY_ENV_FILE` identifies the app env file, also passed to Compose's
   `--env-file` for variable interpolation. Never place a wallet key or the
   keystore password value in that environment file.
5. From `backend`, build the image and start PostgreSQL/migrations/backend with
   the explicit overlay. Review the rendered Compose configuration locally;
   do not paste its output because it contains application/DB secrets.

   ```bash
   docker compose --env-file "$MINTLY_ENV_FILE" -f docker-compose.yml -f docker-compose.custody.yml --profile custody build backend
   docker compose --env-file "$MINTLY_ENV_FILE" -f docker-compose.yml -f docker-compose.custody.yml --profile custody up -d postgres migrate backend
   ```

6. Sign into Mintly and link the test wallet using the existing one-use wallet
   challenge. Obtain the linked `user_id` and `wallet_id` from authenticated data.
   Verify the test collection, exact contract, SeaDrop deployment, chain and stage
   metadata. The production OpenSea discovery adapter does not currently supply a
   proven Sepolia feed; testnet fixture/data provisioning must be explicit.
7. Provision custody interactively. Substitute the IDs, verified collection,
   deliberately small caps and a future ISO UTC expiry. For example, the command
   below grants **only public minting** to one collection. Add `--mint-kind
   allowlist` or `--mint-kind signed` only for a separately verified adapter.

   ```bash
   docker compose --env-file "$MINTLY_ENV_FILE" -f docker-compose.yml -f docker-compose.custody.yml --profile custody run --rm --no-deps \
     -v "$CUSTODY_VAULT_HOST_DIR:/run/custody-vault:rw" automatic-signer \
     python -m app.provision_custody --user-id USER_UUID --wallet-id WALLET_UUID \
     --contract VERIFIED_TEST_COLLECTION --mint-kind public \
     --budget-eth 0.01 --max-task-eth 0.002 --expires FUTURE_ISO_UTC_TIME
   ```

   The normal signer mount is read-only; this one-time provisioning process needs
   write access. The private key is entered **only at the hidden terminal prompt**,
   never in the command, chat, clipboard history, CI, screenshots or logs.
   Provisioning refuses redirected stdin. It sends no transaction.
8. Start the isolated signer, scheduler and notification consumer:

   ```bash
   docker compose --env-file "$MINTLY_ENV_FILE" -f docker-compose.yml -f docker-compose.custody.yml --profile custody up -d automatic-signer automatic-worker automatic-notifications
   ```

The signer has no published port. Its control network is internal and shared only
with API, scheduler and PostgreSQL; a separate network supplies RPC/provider
egress. Container settings include nonroot UID, read-only filesystem, dropped
capabilities, no new privileges, disabled core dumps and a restricted temporary
filesystem. Do not expose the bearer-token endpoint to the internet. A separate
remote host requires authenticated encrypted transport/firewall setup that is not
supplied by this same-host Compose file. Host root/Docker administrators remain
trusted and can bypass container boundaries.

The signer healthcheck verifies authenticated access, secret/journal availability
and RPC chain ID. `/policies/{id}/ready` additionally checks the independent policy
and decrypts the keystore to verify its address; preview and arm require it.
The scheduler healthcheck uses a heartbeat updated after successful iterations.
Monitor container health and `automatic_tick duration_ms` logs. These checks do
not guarantee enough funds or successful inclusion; final gas/funds checks happen
at signing. Configure Firebase credentials and a registered opted-in device for
push delivery. Notifications use a separate consumer and cannot stall signing.

## User flow and API lifecycle

1. Connect wallet. Wallet & account separately explains **Enable automatic
   minting**, custody, secure wallet import, budgets and expiry.
2. Refresh provisioned policies. Review the drop's exact stage, executing address
   and recipient, method, quantity, price ceiling, gas budget, total ceiling and
   submission expiry. Amounts use integer wei; each amount must fit signed int64.
3. `POST /api/tasks/draft` checks ownership, policy, chain and stage, verifies
   readiness, prepares calldata/proofs and returns a review hash. It reserves
   nothing and signs nothing. Presale stage indices are pinned. Conditional
   presales require an explicit stage index and allow deferred provider data;
   invalid proofs or mismatched stages do not become verified eligibility.
4. Flutter sends that hash, a stable random idempotency key and explicit consent
   to `POST /api/tasks/arm`. Changed reviews are rejected. The API reserves the
   full total cap atomically and stores an immutable authorization snapshot.
   Retries return the same task; reuse for a different intent returns 409.
5. The scheduler runs independently of X polling and FCM. It prepares and signs
   only after chain time reaches the selected start, then broadcasts and tracks
   the saved hash. The phone may be closed. Queue and app-resume refresh show
   status, failures, transaction hash and Sepolia explorer link.
6. `POST /api/tasks/{id}/disarm` cancels before signing under the same DB lock.
   After signing, it returns 409: a signed payload may already be broadcastable.
   `POST /api/automatic/policies/{id}/disable` stops future signing and cancels
   unsigned tasks. It does not erase custody or revoke an on-chain permission.

The automatic lifecycle is `armed → prepared → submitted/uncertain →
confirmed/reverted`; unsigned tasks can become `failed`, `expired` or `disarmed`.
`preparing` is also accepted for recovery. Legacy manual plans and experimental
permission history remain readable but are not processed as custody tasks.

## Budgets, retries, finality and recovery

Both API and signer enforce user/wallet binding, chain, collection, decoded
SeaDrop selector, fee recipient, exact stage/timing, recipient, quantity and caps.
The key must derive the linked address. Ordinary contracts are rejected. Existing
EIP-7702 accounts require explicit `--account-mode eip7702-direct` provisioning,
which pins the delegation and implementation hash. See [Robinhood adapter](robinhood-signer-adapter.md).
The signer checks the active user, cancellation, policy expiry and chain state,
estimates gas with 20% padding, checks balance including gas, simulates and
rechecks expiry. Free mints still need ETH for gas. Robinhood uses Nitro's total
gas estimate including parent-data fees once, and 20% gas-price headroom within
the approved fee ceiling. Legacy `gasPrice` fixes the signed maximum. Automatic
fee replacement remains disabled.

The PostgreSQL lock serializes arming, signing and cancellation, including across
processes. Durable nonce records and the signer journal are combined with the
RPC's pending nonce. RPC failure is not nonce zero. A gap behind an uncertain
signed transaction blocks more signing for that wallet; external wallet sends
can still conflict and must not be assumed coordinated with Mintly.

The signer fsyncs its journal before committing signed bytes/hash/nonce to the
application DB. The worker commits submission intent before the network call.
After an accepted-then-timeout response or restart, only the exact saved bytes
may be retried. Six preparation failures or the deadline stop unsigned work;
provider retries wait at least 15 seconds. Broadcast retries stop at four sends
or expiry and retain an `uncertain` reservation. No fresh nonce is used to retry
an uncertain mint. There is no automatic cancellation transaction or gas bump.

After fresh explicit owner consent, `python -m app.recover_custody` inside the
isolated signer can prepare one same-nonce replacement with exactly the original
mint calldata and value. The CLI requires task, owner, a consent reference, a
submission expiry of at most 20 minutes, and `--confirm-exact-recovery`. Original
price, quantity, fee and total caps remain binding. Migration 009 and the
independent signer journal preserve both signatures and approvals. No counters
are reset and no extra lifetime liability is charged; at most two additional
broadcasts reuse the replacement bytes. Both hashes remain tracked and either
finalized winner settles the single reservation. See [approved recovery scope](automatic-recovery-proposal.md).

Receipts must match the canonical block and meet at least two confirmations.
The Sepolia and Robinhood overlays additionally require 12 confirmations **and** the RPC's
`finalized` block to cover the receipt. An unconfirmed reorg keeps funds reserved
and reconciles/rebroadcasts the same payload. A finalized receipt releases the
maximum reservation and charges actual value plus gas (gas only for reverts).
Catastrophic reorgs beyond finalized state are not automatically unwound. A
submission expiry stops Mintly's further broadcasts; it cannot expire a signed
Ethereum transaction. Inclusion after that time may still succeed if the contract
stage remains open. On-chain stage expiry is enforced by SeaDrop.

An uncertain transaction retains its liability indefinitely until a canonical
receipt is available. Operators must investigate hash/nonce/chain state; do not
clear journal entries, reset budgets or create a fresh task as a recovery shortcut.
The scheduler is deadline-aware but globally serialized and includes bounded RPC
latency. It offers no first-block or successful-mint guarantee. Presale data only
available at opening adds an upstream latency dependency.

Notifications are acknowledged after FCM accepts delivery. Crashes may duplicate
a notification, and intermediate status changes may coalesce; failures remain
pending for retry. FCM acceptance is not proof of delivery to the phone.

## Renewal, backups and custody removal

A policy expires permanently; it is not an automatically replenishing allowance.
Renewal is a new explicit operator provisioning operation with the user's chosen
scope. Its budget is additional authority, so account for any other enabled or
uncertain policies. Disable the old policy and reconcile signed transactions
before replacing it. No endpoint enlarges an existing signer policy.

Protect and back up encrypted keystores, independent policy files, the signer
journal and application DB consistently. Keep password recovery material separate
from encrypted backups. Do not roll back only the journal or DB to reset spending
or nonce history. Restores must reconcile saved hashes/nonces against the chain
before the scheduler starts. Losing the password makes the encrypted key
unrecoverable; losing the journal requires manual reconciliation, not a blank
replacement. Restrict host access, disable swap or use encrypted swap, avoid core
dumps/APM body capture, and apply host/OS security updates.

To stop custody, disable policies, stop the signer, reconcile signed liabilities
and remove the encrypted key and its recovery copies under the operator's secure
retention procedure. Database disable/disconnect alone cannot revoke knowledge
of a private key. If compromise is suspected, the original address cannot have
its private key rotated; asset migration to a new wallet changes its address and
may lose existing allowlist eligibility. No removal or asset movement is automated
by this implementation.
