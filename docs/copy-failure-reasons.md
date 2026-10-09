# Copy failure reasons

Copy events retain the latest sanitized upstream request diagnostics, preparation attempt count, HTTP status and failure classification. HTTP logs identify the copy event and phase. Provider response bodies, wallet proofs, keys and arbitrary error text are never stored or displayed. Only explicit, recognized messages become named rejection categories; unknown messages remain unknown.

Explicit allowlist, wallet-limit, supply, native-balance or creator-payout failures stop automatic retries for that event. Native-balance failures retain the existing owner-controlled funding retry flow and all original eligibility and spending checks. Other skipped events remain terminal. Unrecognized 422 replies back off from one minute to at most fifteen minutes, bounded by the original phase and approval expiry. Rate-limit cooldowns still honor Retry-After. No skipped events are revived by deployment.

Due copy observations are processed in phase-expiry order. Advance mint API checks defer when an approved, due copy or armed execution task needs capacity. Global and endpoint permits remain shared across workers. Verified chain/contract-to-collection mappings are cached in memory for five minutes; drop metadata keeps its existing fifteen-second TTL and its network/contract checks. Proofs and transaction calls continue to be independently validated against the receiving wallet and current on-chain state.

Migration 020 adds nullable upstream diagnostics and an attempt count initialized to zero on existing events. Installed clients already display event notes, so this backend change requires no mobile OTA. A full production OpenSea key requires account provisioning; this release uses the existing protected key and does not claim an increased provider quota.
