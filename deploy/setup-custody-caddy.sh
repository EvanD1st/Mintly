#!/usr/bin/env bash
set -euo pipefail
# Existing Mintly site only. No changes to other Caddy sites or public signer routes.
SITE=/etc/caddy/mintly.caddy
BACKUP="${SITE}.backup-$(date +%s)"
sudo -n cp "$SITE" "$BACKUP"
sudo -n tee "$SITE" >/dev/null <<'CADDY'
mintly.duckdns.org {
    encode gzip
    handle_path /downloads/* {
        root * /var/www/mintly/downloads
        header Cache-Control "public, max-age=86400, immutable"
        header Content-Type application/vnd.android.package-archive
        header Content-Disposition attachment
        file_server
    }
    @custody path /api/automatic/import /api/automatic/import/config
    handle @custody {
        request_body {
            max_size 4KB
        }
        reverse_proxy 127.0.0.1:18768 {
            header_up X-Forwarded-Proto https
        }
    }
    handle {
        reverse_proxy 127.0.0.1:8095
    }
}
CADDY
if sudo -n caddy validate --config /etc/caddy/Caddyfile && sudo -n systemctl reload caddy; then
    echo "Custody HTTPS route configured; backup retained at $BACKUP"
else
    sudo -n cp "$BACKUP" "$SITE"
    sudo -n systemctl reload caddy
    exit 1
fi
