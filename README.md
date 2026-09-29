# Mintly

Mintly is a Flutter client with a FastAPI backend for NFT discovery and scheduled
minting experiments. The current Ubuntu deployment is an **authenticated demo**.
Live automatic minting is not production-ready; see the [review](docs/review-2026-09-29.md).

## Hosted backend

- API: https://mintly.duckdns.org/api
- Health: https://mintly.duckdns.org/healthz
- Native app: Wallet > Connect to Mintly server, using your owner access token.
- Deployment, credentials, DNS, and operations: [Ubuntu guide](docs/deployment-ubuntu.md).

GitHub Actions runs backend tests, a clean PostgreSQL/Docker startup check, Flutter
analysis, and Flutter tests before deploying the tested revision from `main`.

## Local development

Use Python 3.12 and Flutter 3.44.8. From `backend`:

```bash
python -m venv .venv
# Activate .venv using your shell, then:
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
python -m pytest tests -v
```

Local development defaults to SQLite. Production uses PostgreSQL and requires a
random owner token with debugging disabled. The default signer is simulated.

From `mobile`:

```bash
flutter pub get
flutter analyze
flutter test
flutter run
```

The client starts in offline demo mode. Connecting to the hosted server keeps the
access token only for the app session. API errors do not silently create demo tasks.

The original requirements are in `Mintly_Antigravity_Prompt.md`; the independent
review checklist is in `Mintly_Codex_Review_Prompt.md`. Earlier handoff documents
contain implementation claims that the current review supersedes.
