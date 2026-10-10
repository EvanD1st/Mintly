# Free and paid copy settings

New mobile approvals select either **Free mints only** (zero mint price) or **Paid mints** (positive mint price up to the approved cap). Both include public, allowlist and signed stages for which the receiving wallet qualifies. Gas is separate and remains subject to the approved gas and total spending limits.

Whitelist selection uses the receiving wallet's verified stage and price, which can differ from the followed wallet's price. Proof and signature checks, network restrictions and the exclusion of unsupported mint methods remain in place. There is no fallback from an ineligible whitelist stage to an unrelated public stage.

Paid-only approval is recorded in the immutable copy snapshot and independently enforced by the signer. Check-only evaluation applies the same price filter. The API rejects contradictory free/paid flags and a zero maximum paid price. Existing immutable approvals retain their saved scope; a new approval is required to change an old mixed-price approval to paid-only. Skipped events are not revived.

The mobile change contains only Dart logic and text; the existing audited Shorebird workflow publishes it to compatible Android releases after validation.
