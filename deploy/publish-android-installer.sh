#!/usr/bin/env bash
set -euo pipefail
# Publish only an APK already verified against the Mintly release signing key.
# This directory contains public installers, never custody files or credentials.
[[ $# == 2 ]] || { echo 'Usage: publish-android-installer.sh verified.apk sha256' >&2; exit 1; }
SOURCE=$1
EXPECTED=$2
NAME=$(basename "$SOURCE")
ROOT=/var/www/mintly/downloads
[[ -f "$SOURCE" && ! -L "$SOURCE" ]]
[[ "$NAME" =~ ^Mintly-[0-9]+\.[0-9]+\.[0-9]+-[0-9]+\.apk$ ]]
[[ "$EXPECTED" =~ ^[0-9a-f]{64}$ ]]
[[ "$(sha256sum "$SOURCE" | cut -d' ' -f1)" == "$EXPECTED" ]]
[[ "$(realpath -m "$ROOT")" == "$ROOT" ]]
[[ ! -L "$ROOT/$NAME" ]]
sudo -n install -d -m 0755 "$ROOT"
if [[ -e "$ROOT/$NAME" ]]; then
    [[ "$(sha256sum "$ROOT/$NAME" | cut -d' ' -f1)" == "$EXPECTED" ]]
else
    sudo -n install -m 0644 "$SOURCE" "$ROOT/$NAME"
fi
echo "Verified installer published at https://mintly.duckdns.org/downloads/$NAME"
