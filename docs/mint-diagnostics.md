# Automatic mint diagnostics

The isolated signer emits structured `mint_upstream` records for OpenSea requests made during preparation and preflight. Records include the task ID, phase, UTC time, endpoint category, HTTP status, duration and parsed Retry-After seconds. The upstream HTTP code is kept separately from the signer's HTTP response: an OpenSea 429 can therefore be retained even when the signer's existing public error mapping returns 503.

The automatic worker persists each request outcome in `mint_attempt_diagnostics`. Preparation and preflight records are separate. Each record retains start/finish time, execution attempt number when applicable, signer HTTP status, safe error category, up to 16 allowlisted upstream events, outcome and the task's next retry time. Earlier entries remain available after later failures, task-note changes, worker restarts or service redeployments. Task deletion cascades to these records; normal task/plan archiving does not remove them.

A timeout or connection failure with no received HTTP status is represented as a null upstream status and a safe transport category. Missing diagnostics are not guessed to be 429, 409 or another upstream response. HTTP-date and numeric Retry-After values are parsed and bounded; unrecognized header values are discarded. The logging change does not alter retry count, delays, approval expiry, budgets, nonce allocation or signing rules. Diagnostic-write failures are isolated from the execution transaction with a savepoint.

No response bodies, request payloads, authorization headers, API keys, JWTs, cookies, private keys, proofs, signatures, transaction bytes, full URLs, collection slugs or receiving-wallet addresses are retained in these diagnostic records. Only fixed endpoint and failure categories are accepted. The existing signer control-plane authentication protects the diagnostic metadata carried to the worker. The database remains inside the protected backend boundary; this release adds no public diagnostic API or mobile UI.

Operator query (run through authorized database access):

```sql
SELECT phase, attempt_number, started_at, finished_at, signer_http_status,
       error_category, upstream_events, outcome, next_retry_at
FROM mint_attempt_diagnostics
WHERE task_id = :task_id
ORDER BY started_at, finished_at, id;
```

Typical categories distinguish upstream rate limiting (429), stage not active (409), unavailable mint instructions (422), API access denial (401/403), provider server errors (5xx), invalid replies, timeouts and signer validation rejection. Endpoint categories distinguish drop mint preparation, drop schedules, API-key creation and contract lookup.

This starts retaining evidence after deployment. It cannot reconstruct response codes that were not recorded for earlier tasks. No historical attempt codes are backfilled from a later diagnostic response.
