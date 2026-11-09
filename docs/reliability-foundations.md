# Reliability foundations

Execution authority stays in the existing MintTask, immutable authorization, isolated signer and DailyDebit ledger. The shared lifecycle service is a read model, not another state machine. Queue, History and the updated Today screen use the same execution status and headline. Today keeps terminal records visible instead of presenting another setup button. Confirmed mints take precedence over later failures, active tasks over terminal attempts, and matching remains scoped to owner, wallet, network and collection. Archived terminal failures no longer dominate the public card. Existing review, disarming and eligibility-check behavior is retained.

Updated mobile clients request `execution_states=true` on Today. Older installed clients retain their previous set of supported Today statuses during rollout. New fields are additive. The migration adds an observation table and does not alter approvals, keys, budgets, reservations, task statuses or signed transaction records. The former retry rules are expressed in one reason-aware helper; copy cooldown/deadline behavior is unchanged. Arming and measurements share the same free-phase eligibility selector, so monitoring does not invent a second eligibility policy.

## Measurements

Verified fresh eligible Auto-Arming observations are recorded once per owner, wallet, network and collection. Repeat polls, source duplicates and additional phases do not inflate this denominator. Stale/incomplete checks are excluded. A failed observation transaction is logged and execution continues. Observation and arming-result records never call the signer, decrypt keys, fetch providers, reserve funds or create mint tasks.

Eligibility coverage starts with observed evidence after this release. Historical opportunities are not backfilled. Only openings in the requested interval count as due opportunities; linked tracked task timing overrides old display timing after postponement. Unarmed closed opportunities are marked for review, not asserted to be preventable misses. Later user cancellation, changing eligibility and external wallet activity can affect the outcome.

Task outcomes distinguish confirmed, already minted, pending, disarmed, reverted, sold out, wallet/stage constraints, service failures needing review, and unknown failures needing review. The last recorded diagnostic is evidence of that check, not a guaranteed root-cause explanation. Older ambiguous records remain ambiguous.

Automatic/scheduled submission timing uses the durable scheduled opening and submission acknowledgement. Copy cohorts and latency start with the persisted CopyEvent detection time, not the source's stage opening. Missing or reversed timestamps are excluded rather than reported as zero. Median and p95 include sample counts and do not imply a guaranteed latency. Copy events observed are not described as verified eligible copies.

## Operator visibility

`GET /api/admin/reliability?hours=24` is admin-only and read-only, with a bounded 1–168 hour window. It returns aggregate counts, timing, failure categories and bounded account/collection examples to help operators investigate. It does not return addresses, keys, proofs, raw transactions or authorization payloads. The admin Today notice and Settings → Administration → Mint reliability refresh every minute. Providers are keyed to account/session revision and discard responses from a changed session. Members do not fetch or see this report. There are no new end-user settings or push messages.

Warnings group three distinct affected tasks/opportunities on one network and reason within 30 minutes. An explicit API access/key or signing-approval problem can raise an immediate operator warning. Multiple retries of one task are one affected task. Successful later checks, confirmed mints, submitted transactions and deliberate cancellations do not keep producing task warnings. Preflight warnings cover future openings independently from due-task metrics; pre-arming failures cover verified opportunities that did not produce a task. Expected budget waits remain separate from incidents. Current eligibility-check states and active Auto-Arming waits provide context without pretending that every queued check is an incident.

This is in-app operator visibility, not an unattended external paging service. No automatic remediation, replay, permission renewal or change to signed liabilities is triggered by these measurements.
