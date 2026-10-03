# Mintly on Ubuntu and DuckDNS

The backend is hosted at **https://mintly.duckdns.org** on Ubuntu `18.175.211.11`.
The Flutter app is a native client; this address serves the API, not a Flutter website.

## Runtime

- Caddy terminates HTTPS and proxies to `127.0.0.1:8095`. Existing Caddy sites are preserved.
- Docker Compose runs PostgreSQL, a one-shot Alembic migration, FastAPI, and one worker.
- The database has no published host port. Redis was removed because the application does not use it.
- The production configuration forces `DEBUG=false`, `SIGNER_MODE=disabled`, and `ALLOW_LIVE_BROADCAST=false`.
- A random application secret and database password are generated on first deployment at `~/Mintly/shared/.env` (mode 600). They are excluded from images and source control.
- Admin-created user accounts use revocable bearer sessions. `/api/auth/login` and the short-lived wallet-link endpoints are public; member data routes require a valid account session.
- Releases live under `~/Mintly/releases/`; `~/Mintly/current` points to the latest successful deployment. Database data persists in the `mintly_postgres_data` Docker volume.

## GitHub Actions

Pushes to `main` and manual runs test the backend and Flutter client before deployment. Pull requests only test.
The backend job also builds the Docker image, runs migrations against a clean PostgreSQL database, and checks production startup and authentication.
Deployment uploads the exact tested Git revision over SSH; it never pulls a moving branch. A concurrency group and host file lock serialize deployments.
Missing secrets, migration failures, container startup failures, and failed HTTPS checks fail the workflow.

Configured repository secrets:

- `UBUNTU_HOST`
- `UBUNTU_USER`
- `UBUNTU_SSH_KEY` (dedicated Mintly Actions key)
- `UBUNTU_KNOWN_HOSTS` (verified server host keys)

Repository variable: `MINTLY_PUBLIC_URL=https://mintly.duckdns.org`.

## Connect the mobile app

Create the first admin with `python -m app.admin_cli admin` inside the backend
container after migration, piping a strong initial password through stdin. The
admin changes that password at first sign-in, then creates member accounts in
the app. The app keeps the bearer session in memory until logout or restart.
There is no offline sample feed. The default API address is
`https://mintly.duckdns.org/api`; a different HTTPS endpoint can be configured
with `--dart-define=MINTLY_API_URL=https://host/api`. See the
[account and wallet guide](real-data-accounts-wallet.md) for MetaMask linking.

## DNS and HTTPS

The owner manually set the DuckDNS IPv4 record to `18.175.211.11`. No DuckDNS
account token was supplied or installed, so automatic DNS updates are not enabled.
If the EC2 public IP changes, update DuckDNS and the `UBUNTU_HOST` secret, and verify
SSH host keys again. Caddy handles certificate renewal while DNS and ports 80/443
continue to point at this server.

For a new server with Caddy already installed:

```bash
bash deploy/deploy-ubuntu.sh
bash deploy/setup-caddy.sh mintly.duckdns.org
```

The setup script installs Ubuntu's Docker packages if needed and validates the
Caddy configuration before reloading. Caddyfile backups are retained in `/etc/caddy/`.
See the [DuckDNS API](https://www.duckdns.org/spec.jsp) for future dynamic-IP updates
and [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https) for certificate requirements.

## Operations

```bash
sudo docker ps --filter name=mintly
sudo docker logs --tail 100 mintly-backend-1
sudo docker logs --tail 100 mintly-worker-1
curl --fail https://mintly.duckdns.org/healthz
```

To deploy an existing release again, run its `deploy/deploy-ubuntu.sh` with
`MINTLY_RELEASE` set to the desired image tag. Take a database backup before schema
changes; switching application releases does not undo database migrations.
Automated backups, retention of old images/releases, and schema rollback are not configured.

See [the review](review-2026-09-29.md) before considering real automatic minting.
## Custody import deployment

On 3 October 2026 the backend was deployed from the local release snapshot
`custody-5b27aadf42ab`, with migration `007_automatic_execution`. The signer and
separate import service run as UID 10001; Caddy routes only the two exact import
paths to the host-loopback listener on port 18768. The signer has no host port.

`~/Mintly/shared/custody.env` selects Robinhood 4663 and protected paths under
`/srv/mintly-custody`. Normal deployments preserve these services when this
configuration exists. They do not start the automatic spending worker.
`CUSTODY_TASK_ARMING` defaults to false, so the API rejects new automatic tasks
while the service is staged. Importing a key does not itself enable minting.

A PostgreSQL custom-format backup was taken before migration at
`~/Mintly/shared/pre-custody-import.dump` (mode 600). The previous application
release remains available. Caddy retained its previous site configuration backup.
See [wallet import setup](wallet-key-import.md) for custody boundaries.

The subsequent `main` deployment from commit
`410a8e1ffa596049f7e083094897ae826471abee` preserved this configuration.
Production health returned 200, unauthenticated import config returned 401 with
`Cache-Control: no-store`, and public signer readiness returned 404. The API
confirmed task arming is disabled; the automatic spending worker is absent.
The exact release and Android patch evidence are recorded in
[custody deployment evidence](custody-deployment-2026-10-03.json).

Android patch 9 was published to the stable channel for release `1.1.0+3`
on 3 October 2026 at 13:21 UTC. Hosted analysis and all 14 mobile tests passed.
Shorebird verified asset/native compatibility without overrides. New dropdowns
reuse an installed icon glyph. Open the installed app online to download the
patch, then fully close and reopen it to activate the update. Device activation
has not been observed from the deployment host.

## Simplified wallet setup deployment

Release `wallets-560dbea` deploys the simplified import API and independently
validated task-selected collection scope. The live importer advertises
`automatic_collection_selection: true` on Robinhood 4663. Health returned 200;
unauthenticated import configuration returned 401/no-store; signer readiness is
not publicly routed (404). Task arming is still disabled and the automatic spending
worker is absent. No real key import or mint occurred during verification.

Android 1.1.1+4 requires a new signed installer: recovery-phrase libraries add
license notice assets, and the new screen also changes the icon subset. The
attempted 1.1.0+3 patch was rejected without overrides. Recovery phrases are
processed on the device; only the matching linked account key reaches the
protected importer. The release evidence is tracked in
[wallet deployment evidence](wallet-deployment-2026-10-03.json).

The Android release build succeeded on workflow run `37156828708`, attempt 2.
The installer was checked with Android apksigner and matched the existing Mintly
release key; package `com.mintly.mintly`, version name `1.1.1`, version code `4`.
The verified APK is available at
[Mintly 1.1.1](https://mintly.duckdns.org/downloads/Mintly-1.1.1-4.apk).
Caddy serves `/downloads/` only from `/var/www/mintly/downloads`; custody files
remain under their protected separate root. HEAD returned 200 and the exact byte
length; range download returned 206 with the APK ZIP header. Missing `.env` and
traversal requests returned 404. The existing authenticated import route and
backend health checks remained correct after Caddy reload.

Publish a verified future installer with `deploy/publish-android-installer.sh`
and its independently checked SHA256, then run `deploy/setup-custody-caddy.sh`.
The script refuses changed bytes under an existing immutable installer name.
Future automatic Dart patches now target `1.1.1+4`; users on `1.1.0+3` must install
this signed update first. No real wallet import or mainnet spending was performed.
