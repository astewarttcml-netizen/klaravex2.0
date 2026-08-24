#!/usr/bin/env bash
# Idempotent install of growth-stream@.service / .timer templates + digest timer.
# Default: user systemd (~/.config/systemd/user).
# System scope: INSTALL_SCOPE=system (requires root → /etc/systemd/system).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCOPE="${INSTALL_SCOPE:-user}"

if [[ "$SCOPE" == "system" ]]; then
  DEST="/etc/systemd/system"
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "INSTALL_SCOPE=system requires root" >&2
    exit 1
  fi
  RELOAD=(systemctl daemon-reload)
else
  DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p "$DEST"
  RELOAD=(systemctl --user daemon-reload)
fi

install -m 0644 "$SCRIPT_DIR/growth-stream@.service" "$DEST/growth-stream@.service"
install -m 0644 "$SCRIPT_DIR/growth-stream@.timer" "$DEST/growth-stream@.timer"
install -m 0644 "$SCRIPT_DIR/growth-digest.service" "$DEST/growth-digest.service"
install -m 0644 "$SCRIPT_DIR/growth-digest.timer" "$DEST/growth-digest.timer"

# Fix EnvironmentFile path for this checkout when not under ~/Klaravex2.0
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$REPO_ROOT/growth/.env"
if [[ "$SCOPE" == "user" ]]; then
  for unit in growth-stream@.service growth-digest.service; do
    tmp="$(mktemp)"
    sed "s|^EnvironmentFile=.*|EnvironmentFile=-${ENV_FILE}|" \
      "$DEST/$unit" >"$tmp"
    install -m 0644 "$tmp" "$DEST/$unit"
    rm -f "$tmp"
  done
fi

"${RELOAD[@]}"
echo "Installed growth-stream@.* and growth-digest.service/.timer → $DEST"
echo "Enable when ready, e.g.:"
if [[ "$SCOPE" == "system" ]]; then
  echo "  systemctl enable --now growth-stream@leads.timer"
  echo "  systemctl enable --now growth-digest.timer"
else
  echo "  systemctl --user enable --now growth-stream@leads.timer"
  echo "  systemctl --user enable --now growth-digest.timer"
  echo "  (optional) loginctl enable-linger \"\$USER\""
fi
