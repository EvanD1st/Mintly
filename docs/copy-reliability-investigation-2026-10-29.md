# Copy reliability investigation — 29 October 2026

Production was running revision `1ad230beebec1ec12365183e9228fc501d337c33`.
The API, copy worker and isolated signer reported healthy, but this does not
establish successful copies. Production database/journal inspection and RPC
checks were read-only. No customer transaction was signed, retried or broadcast
by the investigation, and no approvals, wallet code or spending counters were changed.

## Findings

- Since 8 October, 53 observations carried the per-rule budget message and eight
  carried the shared-budget message. These counts are observations, including
  multiple follows of a source; they are not 61 independent eligible mint failures.
  Active free-copy rules reproduced the full-ceiling problem: a small settled gas
  charge left nearly all the budget available, but another entire original gas
  ceiling would no longer fit. This condition rejects before eligibility/gas
  estimation and cannot establish whether every blocked wallet was eligible.
- The affected recent Bot Watchers copy was observed on 25 October and its
  unsigned task was rejected by the signer. Digital humans had the same generic
  rejection on 27 October. Both failures have HTTP 409 diagnostics, no transaction
  hash, and no corresponding signature in the private journal.
- The affected wallet currently contains a valid-length EIP-7702 delegation
  marker while its independently pinned policy expects an ordinary EOA. The
  existing fail-closed check rejects that mismatch. Approval hashes, shared
  membership and the examined task caps match their independent pins. Historical
  account-code RPC reads were unavailable; the retained generic errors do not
  prove which rejection branch fired at those past timestamps. Renewing the
  wallet approval is required for its current state; silently repinning it is
  not an appropriate repair.
- Ethereum's scanner deliberately lagged 12 blocks. Across 32 recorded Ethereum
  observations since 8 October, median detection delay was about 154.9 seconds
  and p95 about 168.9 seconds. These are observation delays, not the latency of
  successfully eligible copies. The signer independently requires at least two
  confirmations and verifies the canonical source receipt/block.
- Sixty-seven observations had no task, no note and no preparation attempt.
  They belong to watches/networks without an active copying approval. Following
  alone is observation, not spending authorization; the UI needs to say so.
- Base/HyperEVM cursor snapshots reported unavailable providers. Base's configured
  public endpoint returned HTTP 429 for filtered historical and recent log reads.
  HyperEVM's configured endpoint rejected the cursor's 300-, 200- and 100-block
  historical log ranges, while a single historical block and recent filtered
  reads succeeded. Neither cursor was advanced manually. A read-only Base
  PublicNode probe returned the correct chain ID and accepted historical and
  recent log reads; this is an interim candidate, not an availability guarantee.
  Probes using Python urllib received HTTP 403 from both PublicNode endpoints;
  the application's actual Web3 client accepted both chain identities and Base's
  historical/recent filtered reads. Hyperliquid PublicNode accepted a 10-block
  historical range and a recent 300-block range, but rejected the historical
  300-block request. Provider selection must be validated with the application
  client and the cursor's actual range. Provider recovery remains separate from
  the confirmed wallet/budget repairs.
- Server disk had about 1.4 GB free (96% used); no disk-full failure was established
  by this snapshot.

## Repairs

Free-only tasks can narrow their gas and total ceilings to the remaining rule,
shared, wallet-policy and daily budgets. The original pinned approval is unchanged.
The isolated signer accepts only positive narrower free-task ceilings, continues
to verify zero mint price and approved quantity/source, and independently charges
settled costs or full unresolved liabilities. Paid/fixed-price scope checks remain
unchanged. A reset of mutable API spending records must still be rejected by the
private journal.

Changed account code/delegation remains unsigned and produces an actionable
wallet-approval message plus an allowlisted `wallet_approval_changed` diagnostic.
Unsigned failed-copy notifications show that explanation instead of a task UUID.
Older generic records receive a plain explanation without inventing a historical
cause. Unapproved watches retain observation status and explicitly say watching
only; approving later does not authorize the old backlog.

`COPY_ETHEREUM_SOURCE_CONFIRMATIONS` counts the source block and requires at least
two confirmations. Its default is 13, preserving the former 12-block lag. Receipt
finality settings and the independent canonical-source checks are unchanged.
Changing the operator preference to two confirmations reduces observation delay
while accepting a smaller source reorg margin; it does not change mint budgets.

## Validation

Local isolated-EVM runs passed 88 copy/adaptor/phase tests and 57 additional
reliability, quantity, price-mode and retry tests. A diagnostics category regression
was corrected and all 13 diagnostics tests then passed. The checks exercise real
local SeaDrop transactions, shared reservations, confirmed spending, altered wallet
code, notifications and refusal to sign when mutable API spending is reset or a
task exceeds its independently pinned gas ceiling. No customer tasks were replayed.
Full SQLite/PostgreSQL and production startup verification is required in CI.
