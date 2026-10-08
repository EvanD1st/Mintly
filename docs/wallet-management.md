# Wallet management and phrase-only setup

The Wallet screen adds accounts using their recovery phrase and an account number
(1 through 20). Derivation runs on the device; the phrase is never sent. Only the
selected account key reaches the existing isolated, authenticated HTTPS custody
importer after password confirmation and finite spending consent. Wallet creation
and encrypted-policy import share the execution lock. Retry identities are stable;
duplicate active accounts cannot rename or replace an existing wallet. Adding
network access to an existing wallet stays in its details screen.

Web pairing, its challenge/completion endpoints and the old connect page are
retired with HTTP 410. Existing wallets, policies and historical pairing records
remain intact. No existing policy is reactivated by a retry or by re-linking.

Each active wallet is a compact list row with an Unlink button. Cancel performs
no action. Okay archives the selected wallet, disables all its network policies,
revokes its copying rules, disarms unsigned tasks and releases their reservations,
and archives its plans. Other receiving wallets and public followed wallets are
retained. History and encrypted custody records remain; unlinking is not key
erasure or an on-chain revocation.

Already signed tasks keep their bytes, hashes, nonce reservations and receipt
accounting, but further Mintly broadcasts are permanently disabled. The worker
still reconciles a transaction that was already mined or sent elsewhere. Re-linking
creates a fresh, explicitly approved policy and never resumes stopped actions.

An archived wallet no longer reserves an address for its previous account. The
new account must prove possession of the selected phrase-derived key and confirm
its own password. It receives its own wallet record and fresh approvals. The
previous wallet, mint history and disabled policies keep their original owner.
An active link to another non-deleted account still blocks import, including an
attempt to reopen the previous account's archived wallet by ID.

Relinking waits for unresolved signed transactions on any network. Database
checks include legacy signed permissions. The isolated signer independently
checks its durable journal and canonical finalized receipts, including recovery
hashes, so a signature written before a failed database commit also blocks a new
owner. The authenticated internal check returns only a boolean and does not sign,
broadcast, reset spending or modify the journal. Ingress holds the execution lock
throughout ownership checks and atomic activation; the signer check must not
acquire that same lock again. Ingress receives the existing read-only control
token mount, with no signer journal mount.

New clients import a wallet once for every network advertised by ingress. Network
selection is removed from the phrase step. Users explicitly enter a finite ETH
budget for each available network, see the combined authorized amount, choose a
common expiry and consent before import. Budgets include NFT prices and fees and
remain independent; balances are separate on Ethereum, Base and Robinhood.
Import checks the account adapter on each chain before storing one encrypted key
and independently pinned policies. All grants and the wallet commit atomically.
The complete network/limit bundle is pinned in every policy, preventing a retry
from changing, adding or dropping allowances after storage or a lost DB commit.
Existing installed clients can still use the single-network request format.
Existing approvals are never expanded automatically. Existing wallets can approve
additional network access through their details screen using the same import flow.

Following a distinct public address retains a separate per-user watch. The add
button stays visible in the top bar. Editing is named Edit name / networks; it
cannot change the address. Adding clears search/activity filters, uses stable row
keys and refreshes the list independently of activity-feed failures.

Copy settings keeps wallet/network selection, quantity, price, gas, total budget,
expiry and consent. Explanatory paragraphs are replaced by one warning covering
fees, skipped out-of-limit mints and already signed transactions. Free maximum
copying, account isolation and immutable spending approvals remain unchanged.

Migration 012 adds nullable wallet archive and task broadcast-stop timestamps;
existing records start with no archive/stop flag. Tests use disposable accounts
and local EVM balances; verification never unlinks a production wallet or submits
a mainnet mint.

Copy settings selects a receiving wallet once and approves its available network
policies together. The displayed Total copy budget is one shared budget across
those networks, not a separate allowance for each. Each child rule retains its
own immutable wallet policy limits and records the complete group membership and
shared cap. Database reservations sum the whole group; the isolated signer also
sums independently pinned liabilities and finalized receipt costs across all
group members. A missing sibling pin fails closed. Registration can be retried
after interruption; no child is activated until all pins succeed. Existing
single-network approvals retain their original snapshots and allowances.

Max mint price per NFT stays visible. Gas spending limit replaces the old network
fee label and stays visible, with a short explanation. Funding is checked before
an automatic copy task is created and again before signing. Insufficient funds
produce a short network-specific note in Copy activity; they do not pause other
networks. Retry is an explicit, owner-scoped action, rechecking the stage, source,
current wallet approval, expiry, eligibility and shared remaining budget. A
previously armed funding failure reuses its unsigned task and immutable limits;
the independent journal must confirm that no signature exists before rearming.
Signed, submitted, uncertain, unlinked, paused or expired mints cannot use this
funding retry. Skips before task creation remain unsigned records in Copy activity;
funding failures after task creation also use the existing personal notification
outbox with a short reason. No request changes old spending consent automatically.
