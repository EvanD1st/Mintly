#!/usr/bin/env bash
set -euo pipefail

# Deploy the supplied checkout; never pull a different revision after CI tests.
RELEASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
if [[ -f "$APP_DIR/shared/firebase-service-account.json" ]]; then
    chmod 600 "$APP_DIR/shared/firebase-service-account.json"
    export MINTLY_FIREBASE_FILE="$APP_DIR/shared/firebase-service-account.json"
    COMPOSE+=(-f "$RELEASE_DIR/backend/docker-compose.firebase.yml")
fi
if [[ -f "$APP_DIR/shared/x-cookies.json" ]]; then
    chmod 600 "$APP_DIR/shared/x-cookies.json"
    export MINTLY_X_COOKIES_FILE="$APP_DIR/shared/x-cookies.json"
    COMPOSE+=(-f "$RELEASE_DIR/backend/docker-compose.x-session.yml")
fi
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build backend
"${COMPOSE[@]}" up -d --wait --wait-timeout 180
curl --fail --silent --show-error "http://127.0.0.1:$(sed -n 's/^MINTLY_PORT=//p' "$MINTLY_ENV_FILE")/healthz"
if [[ "$RELEASE_DIR" != "$APP_DIR" ]]; then
    ln -sfn "$RELEASE_DIR" "$APP_DIR/current"
fi
"${COMPOSE[@]}" ps
echo "Mintly deployment healthy."
