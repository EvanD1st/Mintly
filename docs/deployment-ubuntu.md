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
