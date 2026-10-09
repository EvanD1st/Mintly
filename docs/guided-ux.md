# Guided wallet, mint and copy setup

Released on 9 October 2026. The [release evidence](guided-ux-release-2026-10-09.json) records the tested source, native installer, four OTA packages and retained production records.

Wallet setup offers an address-only view with no signing authority, or separately approved server custody. The phrase derives the selected account on the device; its private key is sent over HTTPS and stored encrypted by the custody service. Mintly software enforces the approved limits. Use a dedicated minting wallet and select only the networks to approve. An address view cannot block another account's possession-verified custody import, or bypass unresolved-signature holds when upgraded.

Automatic mint review asks for wallet, NFT quantity, WAT timing and maximum total ETH including gas. The backend derives the verified public or receiving-wallet presale method, index and expiry. Optional stage and gas controls are under Advanced. Missing signing approval disables review beside a working wallet setup action; draft quantity, time and total survive the return. Import opens the saved plan immediately, and an armed plan displays its status.

Copy has a main navigation tab. Active wallets show Copying active · Manage. The two preferences are Free mints only, which uses the maximum available public or independently eligible whitelist quantity, and Public / whitelist mints, which offers 1 NFT, Custom or Max mint. Network fees still apply. Maximum quantity respects receiving allowance, remaining supply, spending budgets and the existing 100-NFT execution ceiling. Switching back from free preserves the paid quantity choice. Existing fixed/public-only approvals keep their exact scope until fresh explicit consent. Whitelist copying never reuses a followed wallet's proof or falls back to public minting.

Activity and history share one destination with filters. Pause all appears near scheduled plans and copy management; signed transactions may still finish.

[Install Mintly 1.1.2](https://mintly.duckdns.org/downloads/Mintly-1.1.2-5.apk) over the existing app to enable remembered sign-in. The installer has the same release signing certificate. Android Keystore encrypts the session token in private files excluded from backup; startup validates it with the server and authenticated expiry clears it centrally. No password or wallet secret is stored in the session vault. Older installers receive the UI through audited Dart-only OTA and retain memory-only sessions. An online app applies a downloaded OTA on a subsequent restart.

Validation passed: 343 backend tests, 166 PostgreSQL checks, 81 Flutter tests in normal and legacy icon modes, static analysis, production startup and Android API 35 tests for encrypted storage, process restart, tamper rejection and clearing. Production ownership/approval/history fingerprints were retained. No real-wallet import, permission change or mainnet transaction was performed for testing.
