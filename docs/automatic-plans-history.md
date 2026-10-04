# Automatic mint plans and retained history

Mint plans → Set up automatic mint refreshes the selected OpenSea stage, carries
its wallet and quantity into the existing bounded review, and arms only after
explicit acceptance of the displayed exact limits. One active automatic task per
plan is enforced under the execution lock. Retries with the same idempotency key
return the original task. Importing a collection alone never arms spending.

Remove archives a plan and its linked tasks. Unsigned armed/preparing tasks are
canceled under the same cross-process lock used by the signer and release their
reserved budget once. Prepared/submitted/uncertain transactions retain their
bytes, nonce, status and reservation; the scheduler still reconciles them after
removal. The response and app explain that tracking continues in History.

Settings → History provides paginated, authenticated records for automatic mints,
plan versions, account activity and legacy wallet permissions. Removed items stay
readable. Automatic records retain the immutable authorization and receipt costs;
private keys, raw signed bytes and proof calldata are never returned. Reimporting
a collection restores the plan while retaining earlier quantity/removal snapshots.
Migration 008 retains all existing plans as initial history snapshots.

The production spending service is activated explicitly using
`MINTLY_RELEASE=<verified revision> bash deploy/activate-automatic.sh`.
It verifies signer/keystore readiness and refuses a first activation with old
pending authorizations needing review. It creates no tasks. The protected
`custody.env` records `CUSTODY_TASK_ARMING=true` and
`CUSTODY_AUTOMATIC_WORKER=true`; later deployments preserve that activation and
update the separate scheduler and notification service. Firebase uses a separate
protected copy readable by the notification service, with no wallet-key mount.

Validation covers exact plan-stage/wallet/quantity transfer, idempotent arming and
removal, cross-account access, history pagination and migration backfill. Real
local SeaDrop tests prove unsigned removal prevents execution and prepared removal
still reaches one canonical receipt with the original nonce and exact accounting.
