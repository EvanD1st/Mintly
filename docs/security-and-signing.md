# Signing and custody security boundaries

The current automatic implementation is `custodial_v1`, following the user's
explicit choice to hold the existing wallet key on the server. See
[setup and recovery](automatic-custody.md) and [verification](automatic-verification.md).
It is tested locally, disabled by default, and supports local EVM,
Ethereum Sepolia and explicitly opted-in Robinhood 4663. It is not a production custody certification.

## What protects the key

The isolated signer uses an Ethereum V3 encrypted keystore with scrypt
`N=262144`. A separate runtime secret decrypts it only within the signer process.
Keys can be provisioned through the masked operator CLI or the dedicated
[HTTPS wallet import service](wallet-key-import.md). The key must derive the
already linked user's address. The import screen handles it transiently; no
private key environment variable, mobile persistence or seed phrase is used.
Python memory cannot be reliably zeroized; decrypted key material can remain
in process memory until reclaimed. The `del` statements do not guarantee erasure.

Production instructions require Linux service ownership, mode 0700 directories
and 0600 files outside Git. File reads validate the opened descriptor, ownership
and permissions and reject symlinks. The keystore, password and journal are
mounted only in trusted custody services: the signer reads the vault, the import
service writes it, and only the signer mounts the journal. Containers run nonroot with read-only filesystems,
no added capabilities, no new privileges and disabled core dumps. The signer
has no published port and authenticates every endpoint with a random service token.
The internal control network separates it from the discovery/notification services.

Encryption at rest does not protect against a compromised running signer or host
administrator who can read its password and memory. The underlying private key
has full authority across compatible chains. Software budget checks do not
become cryptographic restrictions because the service is isolated. There is no
KMS/HSM integration, independent security audit or formal security proof here.
Use testnet keys until the deployment and its controls have been reviewed.

## What protects authorization and funds

The API uses existing authenticated users and wallet-link challenges. An explicit
custody provisioning operation binds the user, wallet, key-derived address, chain,
collection allowlist, SeaDrop methods, finite lifetime budget, task cap and expiry.
Policy files reside in the signer vault and their digest must match the database.
A database edit cannot enlarge that independently provisioned scope or reset the
journal's lifetime spending. A compromised API can still attempt calls within an
existing signer policy, which is why policy scope and deployment trust matter.

Flutter shows an exact review before explicit arming. The API validates a review
hash, uses owner-scoped idempotency, stores immutable task snapshots and reserves
the full task ceiling in a transaction. The signer independently checks active
ownership, key/address binding, policy scope, task caps/cancellation/expiry,
RPC chain, contract calldata, recipient, price, stage and proof/signature. Public
wallet/supply limits and allowed fee recipients are read from the chain. Signing
requires gas estimation, funds for value plus gas and successful simulation.
EIP-7702 accounts require an independently pinned direct-owner adapter; ordinary
contracts and unprovisioned or changed delegations are rejected. No delegation is
created or removed by the signer. Pins do not audit delegate code or its storage.

The API, signer and scheduler share a database transaction lock for cancellation,
budget and nonce coordination. Durable nonce reservations include pending chain
state. The signer journal records signed bytes and liabilities before the app DB
commit. The worker stores broadcast intent before submission, and retries only
identical bytes/hash/nonce after timeout. Reservations remain held while outcomes
are uncertain. Confirmed reverts charge gas. Sepolia and Robinhood require canonical receipts,
configured confirmations and finalized block coverage before releasing liability.
Signed Ethereum transactions have no Mintly-enforced on-chain expiry; stopping
rebroadcast at the task deadline cannot retract an already signed transaction.

## Operational limits

- The same-host Compose overlay is a deployment template with a Sepolia default, not tested live
  infrastructure. Remote signer hosts need authenticated encrypted transport and
  firewall rules. Never publish its HTTP port or put its bearer token in a URL.
- Host root, Docker administrators, the provisioning operator and signer runtime
  remain trusted. Store backups and decrypting secrets separately; protect the DB
  because signed raw transactions are independently broadcastable.
- A software disable stops future signing but does not erase custody or cancel
  signed transactions. Private key knowledge cannot be revoked on-chain. Removing
  all copies and/or migrating assets is an operator/user procedure, not a claim
  made by Mintly's disconnect button.
- Renewals require explicit provisioning. A new policy grants an additional budget;
  old uncertain transactions still count against their original policy. Restore
  policy files, journal and DB consistently and reconcile chain state first.
- No automatic fee bump, fresh-nonce recovery, replacement transaction or release
  of uncertain liabilities is implemented. A consumed/conflicting external nonce
  can require manual investigation. Do not delete records to unblock spending.
- No first-block inclusion, successful mint, malicious-collection protection,
  Firebase phone delivery or post-finality catastrophic-reorg guarantee is made.
- MetaMask permission experiments remain blocked. Native token allowances with
  empty calldata cannot authorize an NFT mint; local owner-key tests do not prove
  browser grants or MetaMask mobile support.

The historical signer classes under `app/services/signer/` are not the live
custodial signer. In particular, selecting a legacy environment signer no longer
instantiates `LocalServerSigner` in the discovery worker. Default deployment
explicitly disables automatic custody. Robinhood additionally requires
ENABLE_ROBINHOOD_AUTOMATIC=true; all other mainnet chain IDs remain rejected.
