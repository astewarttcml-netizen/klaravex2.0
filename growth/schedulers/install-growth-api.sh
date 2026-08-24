#!/usr/bin/env bash
# Install growth-api.service as a user systemd unit (persistent Layer C).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$DEST"
install -m 0644 "$SCRIPT_DIR/growth-api.service" "$DEST/growth-api.service"

# Rewrite paths for this checkout
tmp="$(mktemp)"
sed \
  -e "s|WorkingDirectory=.*|WorkingDirectory=${REPO_ROOT}|" \
  -e "s|EnvironmentFile=.*|EnvironmentFile=-${REPO_ROOT}/growth/.env|" \
  -e "s|ExecStart=.*|ExecStart=${REPO_ROOT}/.venv/bin/uvicorn growth.api.main:app --host 127.0.0.1 --port 4210|" \
  "$DEST/growth-api.service" >"$tmp"
install -m 0644 "$tmp" "$DEST/growth-api.service"
rm -f "$tmp"

systemctl --user daemon-reload
echo "Installed ${DEST}/growth-api.service"
echo "Enable: systemctl --user enable --now growth-api.service"
echo "Status: systemctl --user status growth-api.service"
