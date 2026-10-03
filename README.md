# Mintly

Mintly is a Flutter app and FastAPI service for reviewing mint lists from
@lakzonevn on X and lists imported by an admin. The
production API runs at https://mintly.duckdns.org/api. The [account and wallet
guide](docs/real-data-accounts-wallet.md) explains sign-in, MetaMask linking,
security limits, and the live feed.

Users can prepare private [OpenSea mint plans](docs/opensea-mint-plans.md) or arm
an exact mint through the explicitly provisioned [custodial automatic path](docs/automatic-custody.md).
Local EVM tests demonstrate unattended public, Merkle allowlist and signed-presale
SeaDrop minting. Ethereum Sepolia is configuration-gated and has not been
demonstrated with a real imported wallet. Robinhood chain 4663 has an explicit opt-in
adapter for Nitro fees and finalized receipts, including pinned EIP-7702 accounts;
see [verification and deployment limits](docs/robinhood-signer-adapter.md). Other mainnets remain blocked.

An admin creates accounts. Members must change their temporary passwords before
using the app. A MetaMask address is linked through a short-lived, one-use message
signature in a browser with the extension installed. Connection alone grants no
spending authority. Following the user's explicit custody choice, an operator can
provision an encrypted key for that same linked address on the isolated signer
host, or a user can use the [wallet import screen](docs/wallet-key-import.md) when
the dedicated HTTPS import service is deployed. Flutter handles the key transiently;
the ordinary API and worker never receive it. This gives the signer
full wallet authority; its finite policy limits are software-enforced, not
on-chain permissions. Unprovisioned wallets continue through manual MetaMask
approval. Wallet-specific eligibility is unverified in the feed.

The worker reads @lakzonevn through Twikit when an authenticated X session is
configured. Without one, the source reports that it needs attention and admin
imports remain available. The app does not invent drop prices, times,
eligibility, or activity when the live source is unavailable. CI tests the
backend and Flutter app before deploying `main` to Ubuntu. Android builds use
Shorebird; a new signed installer is needed whenever native plugins change.

The operator can set up the single shared X reader with the [X session guide](docs/x-session-setup.md);
Mintly users do not need X accounts.

See [Ubuntu operations](docs/deployment-ubuntu.md) and [Android updates and
notifications](docs/shorebird-firebase.md). The [29 September review](docs/review-2026-09-29.md)
records the earlier demo release and is historical context.

## Local development

Read [custody setup, execution and recovery](docs/automatic-custody.md),
[security boundaries](docs/security-and-signing.md), and the
[verification report](docs/automatic-verification.md).
The older [one-use permissions experiment](docs/mint-permissions.md) remains
blocked; the real MetaMask extension probe did not establish NFT-call authority.

Use Python 3.12 and Flutter 3.44.8. From `backend`:

```bash
pip install -r requirements.txt
alembic upgrade head
python -m app.admin_cli admin  # reads initial password from stdin
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
python -m pytest tests -q
```

From `mobile`:

```bash
flutter pub get
flutter analyze
flutter test
flutter run
```
