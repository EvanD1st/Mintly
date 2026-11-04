# Operator expiry maintenance

`python -m app.extend_custody_permissions` runs only inside custody-import,
under explicit operator authorization. It is not exposed through an API.
Use an absolute ISO UTC `--until`, UUID `--operation-id`, and a human-readable
`--reference`. Without `--apply`, it only validates the proposed changes.

Before applying, take and verify a protected PostgreSQL backup. Run the dry run
against the existing signer journal, review affected counts, and record budget,
spending, reservation, status, key-file and approval-ledger fingerprints. Then
apply the same operation and verify those fingerprints and all independent pins.
Never call signer readiness endpoints merely for verification: they decrypt keys.

Only enabled, unexpired policies, active unexpired copy rules, and active
unexpired OpenSea consents are extended. Revoked, paused and historical expired
records are not reactivated. Existing longer expiries are not shortened. Budgets,
spent/reserved balances, key material, consent timestamps, task snapshots and
duplicate-mint ledgers are preserved. OpenSea's external token lifetime remains
provider-controlled; stored read-only consent permits renewal within its expiry.

The operation saves original policy files, the signer journal and a protected
manifest under `vault/maintenance/<operation-id>`. A repeat operation ID fails.
PostgreSQL, policy files and SQLite cannot commit atomically together. A handled
failure before the database commit restores policy files and rolls back both
databases. A failure after that commit marks `recovery_required`; mismatched pins
fail closed. A process or host crash may leave the manifest at `prepared`.

For either interrupted state, inspect the manifest, database expiry/hash values,
policy files and journal before restarting maintenance. Reconcile only the
affected expiry/configuration rows using the protected originals or the intended
new values, under the execution lock. Preserve newer spending, nonce, daily-debit
and duplicate-mint entries. Never restore an entire old database or journal over
live activity. Verify every affected policy and pin before declaring recovery.
