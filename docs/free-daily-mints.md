# Free daily-list automation and phase opening tracking

Today offers **Auto-mint eligible free drops**. Each user chooses an existing signing wallet/network, quantity and maximum gas per collection, then gives one finite standing approval (at most 60 days and never beyond the existing signing policy). Saved settings appear when this screen is reopened. Changing limits requires turning off the existing approval and giving new consent. Existing users start with this feature off; copy approvals are separate.

The worker uses the canonical daily collection groups from @lakzonevn and @Cassio_Sch and the same eligibility cache as Today. It does not wait for both lists. A wallet must have verified eligibility, a zero native NFT price and sufficient known remaining allowance. Eligible open phases take priority; otherwise an upcoming eligible whitelist or public phase is armed. OpenSea eligibility access is required for restricted phases. Gas, signing-policy budgets, daily limits, wallet ownership and paused-account controls still apply. Supply and eligibility are checked again before signing, so FCFS is an attempt rather than a guarantee.

The signer independently pins standing consent in its private journal and verifies list provenance, collection contract, network, wallet, quantity, free-only price, caps and expiry. The API database cannot widen or revive that pin. Normal automatic mint execution handles signing, durable transaction storage, broadcasting and receipts. Existing copy/manual/external mints block a second collection mint. Feed refreshes do not silently recreate an already handled opportunity under the same approval.

## Opening changes

New reviews using **Use stage opening time** approve following the same uniquely identified OpenSea phase. Both earlier and later openings are checked periodically, including phases outside the preflight window, and rechecked immediately before signing. Changed timing invalidates cached calldata/proofs. Queue and Activity show the updated opening in WAT.

Only timing can change. Collection, network, canonical phase identity, method, published price and wallet allowance must match. A phase removed, ended or moved beyond the originally approved submission deadline stops with a review message. No approval expiry or spending cap is extended. A custom selected time stays fixed. Existing fixed task approvals retain their original behavior; the release does not rewrite customer authorizations.

The original authorization snapshot and hash remain immutable. The runtime schedule is separate. Once any signed transaction exists, including one recovered from the private journal after a lost database commit, its bytes, hash, nonce and liability remain intact. Turning standing automation off cancels proven unsigned tasks and disables further broadcasts of signed tasks while retaining receipt reconciliation and reservations.

## Operations

Migration `033_feed_automation` adds an approval table and two nullable schedule-observation fields. It does not alter existing approvals, keys, balances or budgets. Back up PostgreSQL before deployment. Deploy signer, API and workers from the same verified revision. The automatic worker needs the shared **read-only OpenSea API key** mount for list preparation; it receives no custody vault or wallet password mount.

Tests use disposable keys and real SeaDrop contracts on an isolated local EVM. Coverage includes public and allowlist/signed restricted mints, earlier/later opening changes, immutable approval snapshots, changed terms, paid/unverified exclusions, source forgery, duplicate prevention and cancellation before/after signing. Mobile tests cover explicit standing consent, unchanged request retries, displayed saved limits and opening/custom-time behavior. Release gates also run the existing full SQLite/PostgreSQL, Flutter, Android session and production startup suites before deployment and OTA publication for builds 6 and 7.

## Auto-Arming opening prompt

Today shows a short animated dialog: **Turn on Auto-Arming** — “Mintly can automatically arm free mints you qualify for from Today’s list. You still pay gas.” **Turn on** opens the existing approval page; **Not now**, tapping outside, or leaving setup only dismisses the current opening. The reminder returns on a later app opening/foreground session, deferred until Today is visible and the account is unlocked. It does not repeat for ordinary tab visits, stack with another popup, or carry a previous account’s response across account switching.

Only successful signer confirmation and activation record the durable account flag `free_list_enabled_once_v1` in the existing user notice JSON. That flag is not removed on disable or expiry and applies across devices/reinstalls. Existing successful activation history or an active standing approval also establishes the flag, so prior adopters are not prompted again. Pending, failed or cancelled registration does not count. Existing copy-notice flags are preserved. This requires no schema migration and does not change mint permissions or spending limits.
