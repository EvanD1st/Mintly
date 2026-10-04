# Copy mints

Settings → Copy mints opens a separate Following / Activity section. The main Discover, Queue, Activity and Wallet navigation is retained. Users add a public wallet address, name it and choose Ethereum, Base or Robinhood. Following alone never enables spending.

Copy settings select a receiving wallet policy for one network, quantity, maximum price per NFT, maximum network fee, total copy budget, free-only preference and an expiry bounded by the wallet policy. Explicit consent is required. Add or renew additional network policies from Wallet → Details. A policy on Robinhood does not authorize Ethereum or Base.

The observer scans mint events from the pinned SeaDrop contract in bounded recent block ranges. Address-scoped queries work with the production public RPC restrictions. It proves a successful, canonical direct SeaDrop public mint sent by the followed wallet, decodes its quantity and recipient, independently verifies the ERC721 mint transfers and reads its historical public-stage price and times. Presales, ordinary transfers, airdrops and arbitrary transaction replay are excluded. Recent counts cover the last seven days within scanned blocks; initial coverage and RPC delays are shown rather than filled with sample data.

Only source activity after enabling or resuming a rule can trigger an automatic copy. Recent earlier activity can be selected for a separate exact mint review. Copying rebuilds the public call for the receiving account and checks current stage, supply, wallet limits, balance and fees. Each collection's public stage can be copied once per receiving account and chain, across all followed wallets. A matching active or completed regular mint also prevents an automatic duplicate.

The isolated signer pins immutable copy approvals in its private durable journal. It independently verifies the source receipt, rule limits and both the copy budget and wallet-policy lifetime budget before accessing the encrypted key. Pending signatures retain their full liabilities. Public API database edits cannot increase a pinned rule or reset its journal charges. The observer has no keystore, vault password or signing-token mount.

Pausing or removing a followed wallet disarms unsigned copying tasks under the same execution lock used by signing and refunds their reservations. Signed transactions retain their nonce, bytes, receipt tracking and reservation. Removing a followed wallet retains observations, transactions, rule approvals and activity records. Settings → History includes Copy approvals, copied transaction origin and the original mint history.

Ethereum, Base and Robinhood use their own RPC, account-adapter pin, nonce coordination, explorer and finality checks. Base quotes include GasPriceOracle parent-data and operator fees outside L2 gas. The worker checks these again before every broadcast; inclusion receipts charge all fees, including reverted transactions. Base parent fees can change after submission: an inclusion-time overrun is recorded truthfully and disables future signing rather than silently exceeding a budget with another mint. Custody limits are enforced by software, not an on-chain spending permission.

## Operation

Enable `ENABLE_ETHEREUM_AUTOMATIC=true`, `ENABLE_BASE_AUTOMATIC=true`, `ENABLE_COPY_MINTS=true` alongside the existing explicit Robinhood opt-in and recorded automatic-worker activation. The custody Compose overlay passes these settings to the API, isolated signer, import service and automatic worker. Deployment starts a separate `copy-worker` only when both copy monitoring and automatic-worker activation are recorded. Existing policies and confirmed receipts are preserved; deployment creates no followed wallets, copying approvals or spending tasks.

Validation includes real local SeaDrop source transactions, isolated signing and copy receipts; duplicate signals; history retention; historical/manual review; pause handling before and after signing; owner isolation; independent rule pin tampering; network opt-ins and RPC-chain mismatch; and Base parent/operator quote and receipt accounting. Read-only mainnet RPC probes verified chain IDs, deployed SeaDrop code and Base oracle methods. No new funded Ethereum or Base mainnet mint was performed as part of this feature release.

The mobile change uses existing dependencies and drawn icons so installed releases can receive an audited Dart OTA without adding native plugins or image/font assets.
