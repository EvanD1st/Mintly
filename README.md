# Mintly

Mintly is a Flutter app and FastAPI service for reviewing mint lists from
@lakzonevn on X and lists imported by an admin. The
production API runs at https://mintly.duckdns.org/api. The [account and wallet
guide](docs/real-data-accounts-wallet.md) explains sign-in, MetaMask linking,
security limits, and the live feed.

An admin creates accounts. Members must change their temporary passwords before
using the app. A MetaMask address is linked through a short-lived, one-use message
signature in a browser with the extension installed. Mintly never imports wallet
secrets or signs mint transactions. Users approve any mint directly in MetaMask
on the official mint page. Wallet-specific eligibility is unverified in the feed.

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
