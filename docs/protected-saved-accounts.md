# Protected Mintly accounts (Android 1.1.3+6)

Saved accounts are Mintly identities. The operator's X/Twscrape session remains
server-side and is unrelated to login switching.

Migration 026 is additive: it introduces device session families and consumed
refresh-token digests and adds a nullable family reference to bearer sessions.
Existing bearer sessions remain valid. Bearer lifetimes remain 12 hours for admins
and seven days for members. Device access expires after 90 days without use;
normal authenticated activity renews the inactivity deadline at most hourly.

Refresh rotation stores digests only. An identical refresh request can recover
the same tokens for 30 seconds. Its random request ID is saved in the encrypted
device record before network IO and retained across restart/offline failures.
Replaying a consumed token with a different request ID, older generation or after
the recovery window revokes that family and its bearer sessions. Unknown tokens
cannot revoke another family. Password changes/resets, disable/delete and
account-wide logout revoke remembered access. Owner -> family -> bearer locking
keeps refresh and revocation consistent. Short activity locks finish before
endpoints can acquire the mint execution lock.

Android stores refresh credentials, origin/account binding, username and pending
recovery IDs inside AES-256-GCM records in no-backup installation storage. The
Android Keystore key requires strong biometric or device credential authentication
with a 60-second cryptographic authorization window. A separate native gate asks
for fingerprint/phone PIN on every protected reopening or account switch. Android
30+ offers biometric/PIN authentication; earlier supported Android versions use
the system PIN, pattern or password prompt. Mintly never receives the phone PIN,
and the vault accepts no passwords, bearer credentials or wallet secrets.

Cancelled prompts do not consume refresh tokens or clear stored credentials.
Without a secure phone lock, remembering is disabled and password login remains.
Vault corruption/authentication-tag failure drops unusable records; normal login
can establish new protected records. Valid legacy encrypted bearer sessions can
be adopted after phone authentication while the original bearer lifetime remains
valid. Older APKs lack the version-2 channel and keep ordinary login behavior.

Switch/add account clears account routes, selections, eligibility caches and
approval drafts. Session generations reject late requests from earlier identities.
Push retirement finishes before registering another identity. Registration uses
atomic insert-on-conflict and an owner-locked row, including preferences and
unregister operations; another account's active token cannot be reassigned.

`REMEMBERED_LOGIN_ISSUANCE_ENABLED=false` prevents issuing new remembered sessions
without breaking ordinary password login or already issued valid families. To
revoke existing access, use the owner/account-wide logout mechanisms. Discovery
and its rollback switches are independent of remembered login.

Validation includes real database rotation/replay/expiry/revocation and PostgreSQL
independent-session races, client lost-response/offline/cancel/switch isolation,
and Android emulator system PIN authentication, cancellation, Keystore protection,
encrypted disk, restart, origin/account binding, removal and tamper recovery.
The debug instrumentation activity is excluded from the release APK.

Release only after the feed backend/OTA rollout is verified. This native vault
and authentication support requires a new signed APK; do not patch it into older
installed releases through OTA. Apply 026 and verify the backend before publishing
the signed installer. Keep the X discovery session and all signer mounts unchanged.
