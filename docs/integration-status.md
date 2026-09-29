# Mintly Integration Status & Technical Audit

This document records the exact integration status, real-world behavior, upstream API realities, and integration architecture for external services used by Mintly.

---

## 1. Discovery Integration: Twikit (Twitter / X)

### 1.1 Twikit Library Overview
* **Installed Version:** `twikit==2.3.3` (running on Python 3.14)
* **Target Account:** `@lakzonevn` (daily curated NFT drop calendar posts)
* **Diagnostic Script:** `backend/app/twikit_diag.py` (runnable standalone via `python -m app.twikit_diag`)

### 1.2 Upstream Realities & Known X Web Client Changes
The Twikit library interfaces with X's internal web client GraphQL/REST endpoints. These endpoints frequently shift without public changelogs:
1. **Timeline Endpoint Shifts (Issue #425, #433):**
   * X periodically rotates endpoint paths, GraphQL query hashes, and user timeline pagination tokens (`UserTweets` vs `UserTweetsAndReplies`).
   * Twikit v2.3.3 implements adaptive header rotation and updated query IDs, but is subject to upstream breaking changes if X deprecates query schemas.
2. **Rate Limits (HTTP 429):**
   * Unauthenticated or guest scraping is blocked or severely throttled by X.
   * Authenticated sessions encounter rate limits on timeline scraping (typically 50-150 requests per 15-minute window).
   * Twikit exposes `TooManyRequests` with response headers `x-rate-limit-reset`. Mintly's adapter captures this and surfaces an explicit rate limit status with reset epoch to the UI.
3. **Login & Session Invalidation (Issue #414):**
   * X aggressively flags programmatic logins, requiring 2FA or email/SMS confirmation challenge flows (HTTP 414 / Cloudflare challenge).
   * Twikit supports cookie-based session persistence (`client.load_cookies()` / `client.save_cookies()`). Mintly relies on cookie injection (`TWITTER_COOKIES_JSON` / `TWIKIT_COOKIES_PATH`) rather than raw credential login in automated loops.

### 1.3 Diagnostic Script Findings & Zero-Fabrication Guarantee
Running `python -m app.twikit_diag` in the Mintly backend produces a verified diagnostic report:
* When Twitter credentials or session cookies are not configured, the diagnostic gracefully logs the connection requirement, notes HTTP 401/403/429/414 boundaries, and verifies that the deterministic text parser functions on real sample post formats.
* **Zero Fabrication Policy:** Mintly strictly prohibits fabricating synthetic tweets under the guise of live source data. If Twitter cannot be reached or cookies expire:
  1. The UI displays the precise connection status: `offline`, `rate_limited`, or `needs_credentials`.
  2. The curated feed shows the timestamp and post ID of the last successfully fetched and stored source post (`source_posts` table).
  3. The manual import fallback screen allows pasting raw post text from @lakzonevn directly, parsing it through the same deterministic parser.

### 1.4 Structured Text Parser Specification
* **File:** `backend/app/services/parser.py`
* **Source Time Zone:** West Africa Time (`WAT`, UTC+1, Africa/Lagos). Parsed to absolute UTC `datetime`.
* **Price Parsing:** Exact conversion from string decimals (e.g., `0.005 ETH`, `Free`) to exact integer Wei:
  * `0.005 ETH` $\rightarrow$ `5000000000000000` Wei.
  * `Free` $\rightarrow$ `0` Wei.
* **Contract/URL Extraction:** Regex extraction of OpenSea URLs (`https://opensea.io/collection/...`), contract addresses (`0x[a-fA-F0-9]{40}`), supply, and allowlist vs public status.

---

## 2. EVM Minting Integration: OpenSea SeaDrop V1

### 2.1 SeaDrop Protocol Architecture
Mintly targets OpenSea's canonical SeaDrop V1 contract. SeaDrop standardizes ERC-721 drops across multiple EVM chains through a singleton drop manager.

### 2.2 Canonical Contract Addresses
* **Contract Name:** `SeaDrop` (V1.0)
* **Canonical Address:** `0x00005EA00Ac477B1030CE78506496e8C2dE24bf5`
* **Verified Chains:**
  * **Ethereum Mainnet:** Chain ID `1`
  * **Base:** Chain ID `8453`
  * **Sepolia Testnet:** Chain ID `11155111`
  * **Base Sepolia:** Chain ID `84532`

### 2.3 SeaDrop Public Mint Function Signature
* **Function:** `mintPublic(address nftContract, address feeRecipient, address minterIfNotPayer, uint256 quantity)`
* **Method ID:** `0x83e387c2`
* **Full Signature:** `0x83e387c2000000000000000000000000[nftContract 20 bytes]000000000000000000000000[feeRecipient 20 bytes]000000000000000000000000[minterIfNotPayer 20 bytes]000000000000000000000000[quantity 32 bytes uint256]`

### 2.4 Eligibility Checking Logic
Before permitting Jenny to arm a scheduled mint task, Mintly's `OpenSeaClient` (`backend/app/services/opensea_client.py`) checks on-chain/API eligibility:
1. `getPublicDrop(address nftContract)`:
   * Validates `startTime <= now <= endTime`.
   * Checks `mintPrice` matches expected authorized price.
   * Checks `maxTotalMintableByWallet` against user's minted count.
2. `getMintStats(address nftContract, address minter)`:
   * Confirms `minterNumMinted + quantity <= maxTotalMintableByWallet`.
3. Wallet Balance Check:
   * Verifies `balance >= (mintPrice * quantity) + maxFee`.
4. If eligibility fails:
   * App displays explicit rationale (e.g., "Allowlist stage active", "Exceeds max per wallet", "Drop ended").
   * Scheduled arming is disabled or marked "Needs Review".

---

## 3. SSRF & Ingress Protection

### 3.1 Protection Module
* **File:** `backend/app/services/url_validator.py`
* **Strict Checks:**
  1. Scheme validation: Only `http://` and `https://` permitted.
  2. DNS resolution check: Resolves hostname before fetching. Blocks RFC 1918 private IPs (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.1`), link-local (`169.254.169.254`), and IPv6 equivalents (`::1`, `fc00::/7`).
  3. Redirect re-verification: Every intermediate hop in HTTP redirects is re-resolved and validated against the IP filter.
  4. Response size limit: Maximum 512 KB to prevent memory exhaustion attacks.
