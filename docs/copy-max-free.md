# Maximum free copy quantity

New Copy settings approvals use `max_free` only while **Free mints only** is on.
Paid copying retains the selected fixed quantity. The free setting hides the
fixed-quantity controls, sets the price ceiling to zero and requires consent
for a dynamic quantity, with a supported ceiling of 100 NFTs per public stage.

The observer checks the receiving wallet's on-chain mint count and chooses the
smaller of its remaining public-stage allowance, remaining collection supply
and the supported ceiling. A source mint of one NFT can therefore trigger ten,
or seven if the receiving wallet already minted three of a ten-NFT allowance.
The exact chosen quantity is recorded in the task and activity; copy approval
history displays the dynamic ceiling rather than claiming 100 NFTs were minted.

The entire chosen batch must fit the approved network-fee cap and pending gas
balance. Otherwise it is skipped without signing; the bot does not increase a
fee cap or silently submit a smaller batch. Full Base parent/operator fee quotes
are included. The isolated signer independently verifies the zero mint price,
registered mode, quantity ceiling, current wallet/supply limits, source receipt,
budget, fees and recipient before signing. Signing never reuses source calldata.

Existing pinned approvals (including free fixed-quantity rules) retain their
original behavior. To opt in, open Set up copy, enable Free mints only and approve
a new rule. Retrying an approval cannot change its pinned quantity mode. Pausing,
expiry, budgets, account isolation and once-per-public-stage protection remain.
No migration, policy extension, source-method expansion or mainnet test mint is
required to deploy this feature.
