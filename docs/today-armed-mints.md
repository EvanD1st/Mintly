# Existing automatic mints on Today

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
quantity and schedule.

Active collections skip background display eligibility requests, including older
checks queued before arming. Disarming or a terminal task status restores normal
eligibility discovery. Execution-time eligibility, supply and spending checks and
the existing server duplicate-arming guard remain enforced.

Backend regression tests cover active/terminal states, missing and stale checks,
owner/wallet/network/contract isolation, public/private row matching, skipped
provider calls and resuming after disarm. Flutter tests verify that active cards
open the existing task without preparing or arming another, and restore the setup
path after disarm. This requires a backend deployment and a Dart OTA; no database
migration, native release or new user setting is needed.

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
