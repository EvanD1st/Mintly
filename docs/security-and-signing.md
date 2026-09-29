# Mintly Security Architecture & Isolated Signer Boundary

This document outlines the cryptographic safety principles, transaction authorization model, and boundary controls governing Mintly.

---

## 1. Core Security Principle: Software Budget != Cryptographic Protection

A critical architectural distinction in Mintly:

> **A software budget check in application logic is not cryptographic protection.**
> If an attacker or software bug compromises application code, an unconstrained signing key can be commanded to sign any transaction, drain funds, or interact with malicious contracts.
> 
> True security requires an **isolated cryptographic signer boundary** where signing authority is decoupled from orchestration logic. The signing agent independently parses raw transaction parameters, validates method signatures and calldata structure, checks hard upper bounds on value and gas, and enforces chain ID constraints before any signature is produced.

---

## 2. Signer Policy Boundary

### 2.1 Boundary Validation Pipeline
Located in `backend/app/services/signer/base.py`, every transaction requested by the application or worker must pass `SignerPolicy.validate_transaction()`:

```
[ Mint Task / Worker ]
        │
        ▼ (Raw Unsigned Tx + MintAuthorization Record)
┌────────────────────────────────────────────────────────┐
│               SignerPolicy Boundary                    │
│                                                        │
│ 1. Chain ID Validation (1, 8453, 11155111, 84532)      │
│ 2. Target Address Check (must match SeaDrop singleton) │
│ 3. Exact Value Check (tx['value'] <= max_total_wei)    │
│ 4. Gas Limit Check (gas * gasPrice <= max_fee_wei)     │
│ 5. Calldata Parsing:                                   │
│    - Method Selector == 0x83e387c2 (mintPublic)        │
│    - nftContract == drop.contract_address              │
│    - minter == authorization.wallet_address            │
│    - quantity == authorization.quantity                │
└────────────────────────────────────────────────────────┘
        │ Passes all 5 criteria
        ▼
┌────────────────────────────────────────────────────────┐
│             Cryptographic Signing Engine               │
│  (LocalServerSigner / MockSigner / Remote KMS Vault)   │
└────────────────────────────────────────────────────────┘
```

If ANY check fails:
* An immediate `SignerPolicyError` is raised.
* No cryptographic signature is generated.
* An audit event `SIGNER_POLICY_VIOLATION` is recorded in the activity journal with caller and payload details.

### 2.2 Calldata Validation Specification
Mintly prevents calldata tampering or function call substitution:
1. **Selector Verification:** Confirms bytes 0..4 match SeaDrop's `mintPublic`:
   $$\text{selector} = \texttt{0x83e387c2}$$
2. **Parameter Extraction:** Decodes the 128 bytes following the selector:
   * Bytes 4..36: `nftContract` (zero-padded 20-byte address). Must equal the drop's approved ERC-721 contract.
   * Bytes 36..68: `feeRecipient` (zero-padded 20-byte address).
   * Bytes 68..100: `minterIfNotPayer` (zero-padded 20-byte address). Must equal the user's wallet address.
   * Bytes 100..132: `quantity` (uint256 big-endian). Must equal the exact integer quantity approved during task arming.

---

## 3. Key Storage & Credential Isolation

### 3.1 Key Management Hierarchy
1. **Mock Signer (`MockSigner`):**
   * Default mode for development, tests, and demo flows.
   * Generates deterministic fake signatures (`0x...mock...`) without touching private keys.
   * Never broadcasts to any network.
2. **Local Server Signer (`LocalServerSigner`):**
   * Key material is loaded strictly from environment variable `SIGNER_PRIVATE_KEY` or an encrypted keystore file (`SIGNER_KEYSTORE_PATH`).
   * Never stored in SQLite or PostgreSQL database tables.
   * Never transmitted over REST APIs to the Flutter mobile client.
   * The Flutter app only ever receives and displays the public wallet address and authorization UUIDs.
3. **Hardware / KMS Vault (Production Target):**
   * The abstract base `BaseSigner` interface allows zero-code-change drop-in of AWS KMS, Google Cloud KMS, or HashiCorp Vault transit secrets engines where private keys never leave physical HSM modules.

---

## 4. Mainnet Safety & Accidental Broadcast Prevention

Mintly enforces a multi-tier defense against accidental mainnet broadcasts:

1. **`ALLOW_LIVE_BROADCAST` Safety Flag:**
   * In `backend/app/config.py`, `ALLOW_LIVE_BROADCAST: bool = False` by default.
   * If `False`, `mint_executor.py` intercepts any transaction before broadcast, logs a simulated transaction hash, and transitions the task to `DEMO_MINTED`.
2. **RPC URL Routing:**
   * Default configuration routes to Sepolia (`https://rpc.sepolia.org`) or Base Sepolia (`https://sepolia.base.org`).
   * Mainnet RPC URLs (`ETH_RPC_URL`, `BASE_RPC_URL`) are isolated and disabled unless explicitly configured in `.env`.
3. **Explicit Mobile Mode Indicators:**
   * The Flutter mobile app explicitly tags Jenny's active wallet with a **Demo** badge.
   * The action button clearly reads **"Arm demo mint"** when in simulation/testnet mode.
   * Live mode and Demo mode are never silently substituted for one another.
