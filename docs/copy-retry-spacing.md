# Copy retry spacing

Transient copy preparation failures retry after 60, 120, 240 and then 300 seconds, plus a deterministic per-event offset of 0–15 seconds. Provider cooldowns remain a minimum; unknown mint preconditions retain their existing longer backoff. Retries never extend the observed phase or the approval expiry. Existing attempt counts are preserved, so long-running events immediately use the capped interval. Queue pacing (global 6 seconds, mint 20 seconds) and execution locking are unchanged.

Discovery accepts uint256 stage prices so an expensive unselected stage cannot block free whitelist discovery. Selected transaction values retain their signed 64-bit limit and all immutable approvals, wallet-specific proof checks, daily/lifetime budgets and signer checks. No source-wallet proof is reused.
