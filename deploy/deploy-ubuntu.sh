#!/usr/bin/env bash
set -euo pipefail

# Deploy the supplied checkout; never pull a different revision after CI tests.
RELEASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
APP_DIR="${APP_DIR:-$HOME/Mintly}"
mkdir -p "$APP_DIR/shared"
chmod 700 "$APP_DIR/shared"
exec 9>"$APP_DIR/deploy.lock"
flock -w 600 9

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    sudo -n apt-get update
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2
    sudo -n systemctl enable --now docker
fi
DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then DOCKER=(sudo -n --preserve-env=MINTLY_ENV_FILE,MINTLY_RELEASE,MINTLY_FIREBASE_FILE,MINTLY_X_COOKIES_FILE,MINTLY_OPENSEA_DIR docker); fi

export MINTLY_ENV_FILE="$APP_DIR/shared/.env"
export MINTLY_RELEASE="${MINTLY_RELEASE:-local}"
if [[ ! -f "$MINTLY_ENV_FILE" ]]; then
    umask 077
    python3 - "$MINTLY_ENV_FILE" <<'PY'
import secrets, sys
from pathlib import Path
Path(sys.argv[1]).write_text(
    'APP_ENV=production\nDEBUG=false\nSIGNER_MODE=disabled\nALLOW_LIVE_BROADCAST=false\n'
    'MINTLY_PORT=8095\nTIMEZONE=Africa/Lagos\n'
    f'APP_SECRET_KEY={secrets.token_hex(32)}\n'
    f'POSTGRES_PASSWORD={secrets.token_hex(32)}\n'
)
PY
fi
chmod 600 "$MINTLY_ENV_FILE"
COMPOSE=("${DOCKER[@]}" compose --env-file "$MINTLY_ENV_FILE" -f "$RELEASE_DIR/backend/docker-compose.yml")
export MINTLY_OPENSEA_DIR="$APP_DIR/shared/opensea"
mkdir -p "$MINTLY_OPENSEA_DIR"
chmod 700 "$MINTLY_OPENSEA_DIR"
COMPOSE+=(-f "$RELEASE_DIR/backend/docker-compose.opensea.yml")
if [[ -f "$APP_DIR/shared/custody.env" ]]; then
    # Import/signing services are deployed separately; never start the spending
    # scheduler implicitly during a normal release.
    COMPOSE+=(--env-file "$APP_DIR/shared/custody.env" -f "$RELEASE_DIR/backend/docker-compose.custody.yml")
fi
if [[ -f "$APP_DIR/shared/firebase-service-account.json" ]]; then
    chmod 600 "$APP_DIR/shared/firebase-service-account.json"
    export MINTLY_FIREBASE_FILE="$APP_DIR/shared/firebase-service-account.json"
    COMPOSE+=(-f "$RELEASE_DIR/backend/docker-compose.firebase.yml")
    if [[ -f "$APP_DIR/shared/custody.env" ]] && grep -qx 'CUSTODY_AUTOMATIC_WORKER=true' "$APP_DIR/shared/custody.env"; then
        # Independent delivery service has its own protected credential copy.
        sudo -n install -d -o 10001 -g 10001 -m 700 /srv/mintly-custody/notifications
        sudo -n install -o 10001 -g 10001 -m 600 "$MINTLY_FIREBASE_FILE" /srv/mintly-custody/notifications/firebase-service-account.json
        COMPOSE+=(-f "$RELEASE_DIR/backend/docker-compose.automatic-firebase.yml")
    fi
fi
if [[ -f "$APP_DIR/shared/x-cookies.json" ]]; then
    chmod 600 "$APP_DIR/shared/x-cookies.json"
    export MINTLY_X_COOKIES_FILE="$APP_DIR/shared/x-cookies.json"
    COMPOSE+=(-f "$RELEASE_DIR/backend/docker-compose.x-session.yml")
fi
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build backend
"${DOCKER[@]}" run --rm --read-only --user 10001:10001 --entrypoint python \
    "mintly-backend:$MINTLY_RELEASE" -c 'from app.services.automatic_signer import app; from app.models import MintRecovery'
"${COMPOSE[@]}" up -d --wait --wait-timeout 180
if [[ -f "$APP_DIR/shared/custody.env" ]]; then
    "${COMPOSE[@]}" up -d --wait --wait-timeout 180 automatic-signer custody-import
    if grep -qx 'CUSTODY_AUTOMATIC_WORKER=true' "$APP_DIR/shared/custody.env"; then
        "${COMPOSE[@]}" up -d --wait --wait-timeout 180 automatic-worker automatic-notifications
        if grep -qx 'ENABLE_COPY_MINTS=true' "$APP_DIR/shared/custody.env"; then
            "${COMPOSE[@]}" up -d --wait --wait-timeout 180 copy-worker
        fi
    fi
fi
curl --fail --silent --show-error "http://127.0.0.1:$(sed -n 's/^MINTLY_PORT=//p' "$MINTLY_ENV_FILE")/healthz"
if [[ "$RELEASE_DIR" != "$APP_DIR" ]]; then
    ln -sfn "$RELEASE_DIR" "$APP_DIR/current"
fi
"${COMPOSE[@]}" ps
echo "Mintly deployment healthy."
