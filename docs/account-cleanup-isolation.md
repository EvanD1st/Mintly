# Account cleanup and isolation

Wallet linking, imported policies, history, copy watches, approvals and activity
are owned by the authenticated account. Two-account API checks cover list reads,
foreign identifiers and mutations, including following the same public address
from separate accounts. Pausing one account does not pause another.

Mint-status alerts require an explicit owner; an unscoped call is refused. Both
legacy and automatic workers provide the receiving wallet owner. FCM delivery
selects that owner's active, opted-in devices and includes the owner ID in its
data. Source-health alerts are administrator-only. New-drop announcements use
the shared public feed, with separate saved preferences for each account/device.
The administrator-only delivery log is an operational tool.

On account changes the mobile client clears cached drops, selected stages, plans,
tasks, permissions and activity. Responses started under an earlier session are
rejected before they can populate the new account. Push disconnect clears local
state even if unregistering fails and retires the FCM token; foreground alerts
for another owner or ownerless mint-status messages are rejected.

Account Settings now groups personal activity, notification controls, app
information and administrator tools. Source diagnostics are absent for members.
The splash keeps the existing logo and colors, animates its entrance and an
orbit marker, removes the wordmark, and respects reduced-motion preferences.
Copy mints removes its top wordmark and retains copying status and navigation.

Validation uses disposable local accounts and mocked delivery, without new
production wallet connections, approvals, copy tasks, mint transactions or push
messages. Real phone foreground/background delivery and OTA activation are not
observed by these checks.
