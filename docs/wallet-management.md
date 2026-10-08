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
