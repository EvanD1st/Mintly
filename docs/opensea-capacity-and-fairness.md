# OpenSea capacity and account fairness

Mintly retains one operator-provisioned server-side OpenSea key. The shared
request gate defaults to six seconds between requests globally, 20 seconds
between mint-builder requests, an eight-second short queue, and at most 40
durable preparation attempts. A 503 response with an explicit `Retry-After`
holds the affected endpoint across processes; a response indicating an
exhausted account bucket can hold all endpoints until reset.

When equally urgent mint-builder requests are waiting, the gate gives the
next permit to a different account from the last one served. Copy preparation
and armed-task preparation have the same priority. Background reads remain
lower priority. A single account cannot consume every queued mint permit
while another account has a waiting request. This is fair scheduling of a
shared rate budget, not separate provider capacity for each account.

Six wallets that each need fresh mint-builder instructions require permits
at approximately 0, 20, 40, 60, 80 and 100 seconds in an otherwise empty
queue. Only the first two fit inside a 26-second mint window. Valid cached
preflight instructions avoid those six mint-builder requests, but each
instruction must still pass the signer’s current eligibility, terms, gas,
approval and nonce checks. Neither simulation promises chain inclusion.
Approval deadlines are unchanged; an instruction that cannot be prepared
before expiry is reported as insufficient time, without extending consent.

The current execution transaction lock still serializes copy arming,
cancellation and signer preparation across accounts. It protects approval,
reservation and signing consistency, but can delay an account before it
reaches the OpenSea queue. Removing that contention requires a separately
reviewed owner-scoped execution lock with cancellation and signer concurrency
tests. The present change does not weaken those safety checks.
