# Real data, accounts, and MetaMask

The app lists only parsed posts from @lakzonevn on X and administrator-imported
lists or links. Twikit needs an authenticated X session to read the account;
without one, automatic discovery stays empty and the source shows a credential
warning. A post with no verifiable mint link creates no drop. Imported links do
not prove price, time, chain, or wallet eligibility.

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

The app opens only OpenSea collection links automatically. Other URLs
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

To enable Twikit on Ubuntu, provide an authenticated Twikit `cookies.json` as
`~/Mintly/shared/x-cookies.json` with mode 600 and redeploy. The deploy script
mounts it read-only into the backend and worker. Never commit or send this file
in chat: it grants access to the X account. The worker checks @lakzonevn every
five minutes, stores full post text and source IDs, and notifies devices only
when it persists new drops. Twikit uses X's unofficial web interface, so X may
change or limit it; a source error then appears instead of substitute data.
