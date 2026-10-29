# Collection artwork recovery, 29 October 2026

The shared artwork endpoint returned empty artwork across collection lists,
plans and copy activity. A read-only production inspection found 132 cached
collection records, including 54 saved image URLs, with no cache updates after
14 October. All saved images had passed the seven-day stale deadline by
21 October. Two sampled saved CDN URLs still returned HTTP 200 image responses.

Three detected observations were incorrectly classified as urgent minting work.
Their watches were in check-only mode with no active copy approvals. The oldest
observation dated from 14 October and its phase remained open for months. The
global artwork guard blocked refreshes for these observations, so the stale
cutoff eventually hid every saved image. This was independent of OpenSea
wallet eligibility permissions.

The backend now serves the last validated public CDN artwork while refreshing
it in the background. Refresh deadlines retain their pacing purpose but do not
hide an existing public collection image. Failed refreshes preserve the previous
URL without repeatedly extending the stored stale timestamp. Trusted CDN URL
validation and ownership checks on plan/copy references remain enforced.

The copy priority guard requires an active, unexpired matching copy rule and
signing grant, an available wallet and user, an unarchived watch, no check-only
mode, an observation after the approval block, an open phase and a retry due
within the short priority horizon. Actual urgent provider waiters and due mint
tasks still take priority. This check does not authorize or execute any mint.

Regression coverage includes expired saved artwork during urgent minting,
failed and successful refreshes, immediate cached artwork in authenticated
screen responses, and actionable versus paused, revoked, expired, check-only,
historical, deferred and pending copy observations. No app release is required.
