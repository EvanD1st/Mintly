# Dark screen layout alignment

This follow-up aligns the app with the approved dark Mint plans, Copy and Activity references. Screen headers contain only the screen title. The forest surfaces, green selection pills, compact collection cards and grouped detail panels use live account data.

## Presentation

- Mint plans uses All / Needs approval / Armed filters. Cards place collection artwork, network, status, scheduled time and mint facts together. The existing Review & arm flow remains separate from viewing a saved plan. Editing actions remain available under Edit plan.
- Copy keeps followed-wallet management, check-only state, free/paid preferences, network status and activity actions. Its smaller budget card places the amount and network together, with available allowance, spent and reserved totals below. The dropdown aligns network names and amounts in rows.
- Activity opens a combined feed of mint transactions, copy events and account updates. Each stream retains its own pagination cursor. A copy event linked to a mint task is displayed once using the task's transaction record; its followed-wallet label is retained. Individual feeds and the existing approval/recovery records remain available.
- Detail pages retain bottom navigation. Spend and timeline rows appear only when the API supplies the corresponding receipt values and timestamps. An approved cap is labelled as a cap, rather than as an actual reservation.
- Artwork remains optional. Existing authenticated artwork requests and image failure fallbacks are preserved. Task cards and history prefer their saved plan reference when one exists. Preview fixtures use fallback artwork and sample account data; they are not production mint results.

## Budget meaning

The card still sums distinct enabled, unexpired signing grants per network. It is not a wallet balance or a pooled budget. Individual mint, copy and daily limits remain applicable. Available, spent and reserved values are calculated in exact integer wei. Long display amounts are shortened to eight fractional digits with an ellipsis; a long press reveals the full value. Positive values below that precision are shown as less than 0.00000001 ETH, never as zero.

Only networks with real active grants appear. This change does not enable HyperEVM, ApeChain or Ink, create new signing grants or change spending permissions.

## Validation and rollout

Widget checks exercise a 360 × 800 phone at normal and 1.4 text scale, plus a wide test font. They cover network selection/refresh, exact budget precision, compact card height with the real font, review routing, recovery disclosure and navigation from details. Activity regressions exercise independent cursors and copy-task deduplication across pages. The existing mint approval, copy management, funding retry, account isolation and wallet tests remain in the full suite.

CI saves rendered screen previews as `dark-screen-previews`. The mobile suite also runs with both installed icon compatibility modes before any OTA release. New navigation and fact icons use canvas drawing to avoid extending installed font subsets.

No database migration, Android native change, asset change or dependency change is required. Backend signing, execution locking, OpenSea scheduling, copy observation/retries, immutable approvals and recovery behavior are unchanged. Publishing a new OTA remains a separate rollout step using the existing audited pipeline.
