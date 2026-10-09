# Owner-authorized same-nonce recovery

The owner explicitly approved this scope on 4 October 2026:
“Authorize controlled same-nonce recovery”. Execution evidence is recorded separately
in the [mainnet proof report](automatic-mainnet-proof-2026-10-04.json).

Executed successfully: replacement hash
`0x76638de8650ea090dd6218718d89591da92f4cf2f44ccc04b253ed01ec42e31b`
minted token #316 to the same owner using nonce 7. Canonical finalized settlement
was recorded at 06:40:49 UTC. The single reservation is released; actual debit is
0.000039195327232 ETH (about USD 0.105609 at the execution quote), below USD 0.50.
Both signatures and approvals remain retained and integrity-verified.

Existing automatic task: `1c9445a9-30ed-4dbd-89aa-52752a59dd2a`.
Saved transaction: `0x47cfd09301cd4e4eba1a7b09c26426f1fa0af8a76c4ba37f53ab3aaca44f8edc`.
Chain: Robinhood 4663. Nonce: 7. Account/recipient:
`0x5f1A65c4C3011eb22c2882c3e9ea8299f42Ccf7E`.
Collection: `0xAA19274645CbFdC4De5C9C10586CBaCA409b2C72`.
Mint: one NFT, public stage, value 0.000037 ETH.
Maximum total debit: 0.00005 ETH, below the owner's USD 0.50 ceiling at the
checked ETH/USD quote; recheck price immediately before any replacement.

A replacement would preserve the same nonce, account, recipient, collection,
method, quantity and value. It would change the gas price/limit only within a new
explicitly accepted bounded authorization. Same-nonce transactions cannot both
execute. A new nonce is prohibited for this recovery.

Before execution, reconcile the saved hash, current latest/pending nonce, receipt,
on-chain mint ownership, stage, balance, policy and signer journal. If the saved
transaction confirms, finish its existing task instead. If nonce 7 was consumed
by a different transaction, stop for review. Persist both authorizations and both
hashes; never overwrite the old signature or erase its History record. Reserve
the maximum possible debit across competing same-nonce transactions, retain it
until canonical receipt finality, and reconcile both hashes. Retries must reuse
the selected saved bytes and remain finite. Cancellation and recovery must use
the same execution lock. The original expired authorization cannot authorize
new broadcasts or a gas bump.

Implemented by `app.recover_custody`, invoked manually inside the isolated signer.
It persists a separate authorization before signing and an independent fsync-backed
recovery journal before activating the worker. It allows at most two additional
broadcasts within a new window of at most 20 minutes. The original counters,
authorization, signature, reservation and journal liability remain intact.
The worker reconciles both hashes; the signer settles lifetime liability against
either canonical finalized winner. History displays both hashes and approvals.
Automatic fee replacement remains disabled; the CLI requires recorded human consent.
