# Historical source verification

Automatic metadata retries for a published X list can retire once both its list date and post date are more than 14 days old in WAT. Recently reported mint days, recent or upcoming stored stages, malformed reported dates and linked active mint tasks prevent retirement. Unpublished and manual imports remain active.

Retirement sets `source_posts.verification_retired_at` and clears the next processing time. It preserves the original processing error and incomplete hash, raw posts, revisions, collection records, mentions, wallet checks, notification records, plans, authorizations and tasks. It never marks an unverified entry as verified. Retired jobs are excluded from background processing and active source warnings; historical collection counts remain unchanged.

Rechecking an unchanged X post does not restart verification. A genuinely changed post is saved as another revision and reopens processing, so new source corrections or upcoming stages can be checked. The normal age policy applies after that revision is processed. The Retry endpoint rejects retired jobs instead of silently creating endless retries.

The discovery inbox applies retirement automatically. Operators can also call `retire_historical_verification` in a normal application session after a verified deployment. No mint tasks or approvals are changed, and no app update or new user setting is required.
