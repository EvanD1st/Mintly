# Existing and confirmed mints on Today

Today prioritizes the selected wallet's active automatic mint over eligibility
discovery. An armed card shows **Armed**, the approved phase, quantity and scheduled
WAT time. **View automatic mint** opens that exact task, including its existing
limits and controls. Preparing, prepared, submitting, submitted and uncertain
tasks show their current status instead of offering setup again.

The server matches authorized collection identity and network, scoped to the
authenticated owner and selected wallet. Public feed rows and private automatic
plan rows can have different IDs or names. A verified contract takes precedence;
before the feed has a contract, the exact OpenSea collection slug and network
must match. Authorization snapshots take precedence over mutable discovery rows.
The response exposes only the task ID, plan ID, wallet ID, status, approved phase,
quantity, schedule and confirmation time.

Active and successfully minted collections skip background display eligibility
requests, including older checks queued before arming or confirmation. A confirmed
mint shows **Minted**, its recorded phase, quantity and confirmation time in WAT,
with **View mint history**. This remains true after archiving the task or another
failed attempt; the latest confirmed mint takes precedence over other attempts.
Failed, expired, reverted and disarmed tasks restore normal eligibility discovery
when there is no active or confirmed mint for that collection and selected wallet.
Only real confirmed Mintly tasks establish this state; detecting external/manual
mints is outside this change. Execution-time eligibility, supply and spending
checks and the existing server duplicate-arming guard remain enforced.

Backend regression tests cover active/terminal states, missing and stale checks,
owner/wallet/network/contract isolation, public/private row matching, skipped
provider calls and resuming after disarm. Flutter tests verify that active cards
open the existing task without preparing or arming another, and restore the setup
path after disarm, and confirmed cards retain their phase and suppress checks
after returning from history. This requires a backend deployment and a Dart OTA; no database
migration, native release or new user setting is needed.

As of 2026-11-01, automatic OTA publication targets only Android `1.1.3+6` and
`1.1.4+7`, selected by `MINTLY_SHOREBIRD_PATCH_RELEASE_VERSIONS`. Builds 1 through
5 are retired from future automatic updates; their published patches remain available.

The first publication attempt stopped before upload because Shorebird 1.6.134
stores original release artifacts in its shared cache instead of the isolated
temporary folder used by the audit helper. The publisher now captures the exact
release identity reported by the dry run, obtains that release's Android AAB
metadata through authenticated CLI API calls, and downloads the original bundle
into its own scratch folder. Recorded byte length and SHA256 must match before
the existing asset/font/native-library audit runs. Download URLs are not logged.
The publisher regression suite covers release mismatch, corrupt/incomplete
downloads, duplicate artifacts and failure before publication.

Upstream reference: [Shorebird 1.6.134 artifact cache](https://github.com/shorebirdtech/shorebird/blob/v1.6.134/packages/shorebird_cli/lib/src/artifact_manager.dart).
