# Real data, accounts, and MetaMask

The app shows OpenSea upcoming and featured drops from the OpenSea API. It shows
source status and last refresh, and it stops showing stale OpenSea rows after
24 hours. An OpenSea key is required on the backend. The current anonymous key
is temporary and must be replaced or rotated before its expiration; a failed
refresh is shown as a source error. Admins can also import a mint link for manual
review. Imported links do not prove price, time, chain, or wallet eligibility.

Accounts are created only by the admin in **Wallet & account → Manage accounts**.
The admin receives a randomly generated temporary password once and should
share it privately. Members must set a new password of at least 12 characters
at first sign-in. Passwords use Argon2id. Login attempts are limited, sessions
are opaque and revocable, and resetting a password revokes active sessions and
device notifications. Deleting an account disables access and keeps historical
records for audit. Admin account changes require the admin password again.

To link MetaMask, the member opens **Wallet & account → Connect MetaMask** in
the phone app. On the PC with the MetaMask extension, they visit
https://mintly.duckdns.org/connect and enter the one-time code shown on the
phone. MetaMask requests account access and a readable message signature.
The server verifies that signature, binds only the public address to the signed-in
member, and consumes the code. The code expires after five minutes. No recovery
phrase, private key, token allowance, or transaction signature is requested.
Users can unlink an address if it has no task history.

The app opens only OpenSea collection links automatically. Other imported URLs
are displayed for manual verification. The feed cannot attest that a drop is
safe or that an address is eligible. Each mint is a separate transaction that
the user must inspect and approve in MetaMask. Mintly's unattended mint API
rejects all requests; live broadcasting remains disabled on Ubuntu. These
controls reduce risk but cannot guarantee that a malicious collection or a
misread MetaMask prompt will never cause loss.

Push notifications are sent only to active account devices that opted in.
Firebase accepting a message proves submission, not that the phone displayed
it. Verify foreground and background delivery on a signed Android installation
after signing in and granting notification permission.
