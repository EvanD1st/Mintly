# One-time account recovery

An authenticated administrator opens Accounts, selects a member, and chooses
**One-time recovery code**. Issuance requires the administrator's current password
again. Five failed confirmations lock recovery issuance for 15 minutes.

The 192-bit random code is displayed once, expires after 10 minutes, and is stored
only as a SHA-256 digest. Share it privately with the intended account owner.
The member enters their username and pastes the code into the existing password
field. Both ordinary and remembered sign-in endpoints accept it, so redemption
also works on installed builds 6 and 7 before their OTA arrives.

Codes are bound to one active member with an established password; they cannot
recover administrator accounts or bypass required initial password changes.
A valid code can clear an existing password-attempt lockout. Invalid codes cannot.
Issuing another code revokes previous unused codes. Redemption, failure counter
cleanup, audit entries, and normal session issuance commit in one transaction.
Concurrent redemption is serialized by the same user lock used by sign-in.

Recovery does not change the member's password, role, wallet policies, or signing
permissions, and does not reassign an administrator's session. Existing sessions
remain intact. Account-wide sign-out, password change/reset, and deletion revoke
unused codes, including codes issued by an administrator whose sessions are revoked.
Redemption also checks the issuing administrator remains active and authorized.

Issuance and successful redemption appear in both accounts' activity journals.
Codes and session credentials never appear in those entries. Recovery endpoints
use the existing sensitive-response no-store policy. No recovery code is generated
by the migration or deployment; administrators issue them explicitly when needed.
