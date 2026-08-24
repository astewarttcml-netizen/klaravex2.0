#!/usr/bin/env bash
# =============================================================================
# install-watchdog.sh — one-shot installer for the Klara AI watchdog (run PER HOST)
#
# Run this ON the target host (Cloud86, then Hetzner), from inside the ops/
# directory that contains the artifacts. It is idempotent and SAFE:
#   - installs the script + systemd units
#   - creates /etc/loki-watchdog.env from the template ONLY if absent
#   - runs a dry-run and REFUSES to arm the timer unless it exits 0
#
# Usage:
#   sudo ./install-watchdog.sh            # install + dry-run, do NOT arm
#   sudo ./install-watchdog.sh --arm      # install + dry-run, arm timer if clean
# =============================================================================
set -euo pipefail

ARM=false; [[ "${1:-}" == "--arm" ]] && ARM=true
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

err(){ echo "ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || err "must run as root (use sudo)"
command -v docker >/dev/null || err "docker not found on this host"
docker compose version >/dev/null 2>&1 || err "docker compose v2 not available"
for f in loki-watchdog.sh loki-watchdog.service loki-watchdog.timer loki-watchdog.env.example; do
  [[ -f "$SRC_DIR/$f" ]] || err "missing artifact: $f (run from the ops/ dir)"
done

echo "==> installing binaries + units"
install -m 0755 "$SRC_DIR/loki-watchdog.sh"      /usr/local/sbin/loki-watchdog.sh
install -m 0644 "$SRC_DIR/loki-watchdog.service" /etc/systemd/system/loki-watchdog.service
install -m 0644 "$SRC_DIR/loki-watchdog.timer"   /etc/systemd/system/loki-watchdog.timer
mkdir -p /var/lib/loki-watchdog

if [[ -f /etc/loki-watchdog.env ]]; then
  echo "==> /etc/loki-watchdog.env already exists — leaving it untouched"
else
  install -m 0600 "$SRC_DIR/loki-watchdog.env.example" /etc/loki-watchdog.env
  echo "==> created /etc/loki-watchdog.env from template"
  echo "    !! EDIT IT NOW: set HOST_LABEL, COMPOSE_DIR, WEBHOOK_URL, MCP_API_KEY,"
  echo "       and the correct host block (Cloud86 vs Hetzner), then re-run with --arm."
fi

systemctl daemon-reload

echo "==> dry run (no timer armed yet)"
set +e
/usr/local/sbin/loki-watchdog.sh
rc=$?
set -e
echo "==> dry-run exit code: $rc"

if ! $ARM; then
  echo "==> not arming (no --arm). Review output above, edit env, then: sudo $0 --arm"
  exit 0
fi
if [[ $rc -ne 0 ]]; then
  err "dry-run returned $rc — NOT arming. Fix config/health first (see journalctl)."
fi

echo "==> arming timer"
systemctl enable --now loki-watchdog.timer
systemctl list-timers loki-watchdog.timer --no-pager
echo "==> done. Tail logs with: journalctl -u loki-watchdog.service -f"
