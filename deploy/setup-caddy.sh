#!/usr/bin/env bash
set -euo pipefail
DOMAIN="${1:?Usage: bash deploy/setup-caddy.sh mintly.duckdns.org}"
[[ "$DOMAIN" =~ ^[a-z0-9][a-z0-9-]*\.duckdns\.org$ ]] || { echo 'Invalid DuckDNS hostname'; exit 1; }
command -v caddy >/dev/null || { echo 'Install Caddy before configuring HTTPS'; exit 1; }
BACKUP="/etc/caddy/Caddyfile.mintly-backup-$(date +%s)"
sudo -n cp /etc/caddy/Caddyfile "$BACKUP"
if sudo -n test -f /etc/caddy/mintly.caddy; then
    sudo -n cp /etc/caddy/mintly.caddy "${BACKUP}.site"
fi
printf '%s {\n    encode gzip\n    reverse_proxy 127.0.0.1:8095\n}\n' "$DOMAIN" | sudo -n tee /etc/caddy/mintly.caddy >/dev/null
if ! sudo -n grep -q '^import /etc/caddy/mintly.caddy$' /etc/caddy/Caddyfile; then
    printf '\nimport /etc/caddy/mintly.caddy\n' | sudo -n tee -a /etc/caddy/Caddyfile >/dev/null
fi
if sudo -n caddy validate --config /etc/caddy/Caddyfile && sudo -n systemctl reload caddy; then
    echo "HTTPS configured for $DOMAIN. Backup: $BACKUP"
else
    sudo -n cp "$BACKUP" /etc/caddy/Caddyfile
    if sudo -n test -f "${BACKUP}.site"; then sudo -n cp "${BACKUP}.site" /etc/caddy/mintly.caddy; fi
    echo 'Caddy configuration failed; previous configuration restored.' >&2
    exit 1
fi
