#!/usr/bin/env bash
# install-signals-cron.sh — install collect-signals.ts on a 15-min schedule.
#
# macOS  → installs a launchd plist at ~/Library/LaunchAgents/com.klaravex.signals.plist
# Linux  → installs a user crontab entry
#
# Usage:
#   tools/install-signals-cron.sh             # install
#   tools/install-signals-cron.sh --dry-run   # print what would be installed; no writes
#   tools/install-signals-cron.sh --uninstall # remove the schedule
#   tools/install-signals-cron.sh --status    # show current state
#
# Required env vars at run-time (loaded by the schedule via Bun):
#   STRIPE_SECRET_KEY   (or /tmp/klaravex_session_keys/stripe_key)
#   SMARTLEAD_API_KEY   (or /tmp/klaravex_session_keys/smartlead_key)
#   ATERA_API_KEY       (optional — flagged in collector_errors if missing)
#   DATABASE_URL        (Cloud86 Postgres)
#   DATABASE_URL_US     (Azure Postgres — optional)
#   HEALTHCHECKS_API_KEY (optional)
#
# The schedule shells through an ENV-FILE loader so Anthony can keep secrets
# out of the plist/crontab. See LOADER_SCRIPT below.

set -euo pipefail

# ─── arg parsing ────────────────────────────────────────────────────────────
DRY_RUN=0
UNINSTALL=0
STATUS=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --status)    STATUS=1 ;;
    -h|--help)
      sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

# ─── paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COLLECTOR="$PROJECT_ROOT/tools/collect-signals.ts"
ENV_FILE="$PROJECT_ROOT/.loki/state/.signals.env"
LOADER_SCRIPT="$PROJECT_ROOT/.loki/state/run-signals.sh"
LOG_DIR="$PROJECT_ROOT/.loki/logs"
LOG_FILE="$LOG_DIR/signals-collector.log"

BUN_BIN="${BUN_BIN:-$(command -v bun || true)}"
if [[ -z "$BUN_BIN" ]]; then
  echo "ERROR: bun not found in PATH. Install Bun first (curl -fsSL https://bun.sh/install | bash)." >&2
  exit 1
fi

OS_NAME="$(uname -s)"
PLIST_LABEL="com.klaravex.signals"
PLIST_FILE="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
CRON_MARKER="# klaravex-signals-collector (managed by install-signals-cron.sh)"
CRON_LINE="*/15 * * * * $LOADER_SCRIPT >> $LOG_FILE 2>&1 $CRON_MARKER"

# ─── helpers ────────────────────────────────────────────────────────────────
mk_loader() {
  # A tiny shell wrapper the schedule invokes. Sources env file if present,
  # then runs the collector. Keeps secrets out of the plist/crontab.
  cat <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$PROJECT_ROOT"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
exec "$BUN_BIN" "$COLLECTOR"
EOF
}

mk_plist() {
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LOADER_SCRIPT</string>
  </array>
  <key>StartInterval</key>    <integer>900</integer>   <!-- 15 min -->
  <key>RunAtLoad</key>        <true/>
  <key>StandardOutPath</key>  <string>$LOG_FILE</string>
  <key>StandardErrorPath</key><string>$LOG_FILE</string>
  <key>WorkingDirectory</key> <string>$PROJECT_ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
EOF
}

mk_env_template() {
  cat <<'EOF'
# Klaravex signal collector — secrets loaded by run-signals.sh.
# Anthony: fill these in, chmod 600. NOT in git.
# STRIPE_SECRET_KEY=sk_live_...
# SMARTLEAD_API_KEY=...
# ATERA_API_KEY=...
# DATABASE_URL=postgres://user:pw@lend.your-database.de:5432/dediviac_db0
# DATABASE_URL_US=postgres://...
# HEALTHCHECKS_API_KEY=...
EOF
}

show_status() {
  echo "── Klaravex Signal Collector — current status ──"
  echo "PROJECT_ROOT : $PROJECT_ROOT"
  echo "COLLECTOR    : $COLLECTOR  ($( [[ -f $COLLECTOR ]] && echo present || echo MISSING ))"
  echo "LOADER       : $LOADER_SCRIPT  ($( [[ -f $LOADER_SCRIPT ]] && echo present || echo missing ))"
  echo "ENV_FILE     : $ENV_FILE       ($( [[ -f $ENV_FILE ]] && echo present || echo missing ))"
  echo "LOG          : $LOG_FILE"
  echo
  if [[ "$OS_NAME" == "Darwin" ]]; then
    echo "[macOS launchd]"
    if [[ -f "$PLIST_FILE" ]]; then
      echo "  plist installed at $PLIST_FILE"
      launchctl list 2>/dev/null | grep -F "$PLIST_LABEL" || echo "  (not loaded — run: launchctl load $PLIST_FILE)"
    else
      echo "  plist NOT installed"
    fi
  else
    echo "[cron]"
    if crontab -l 2>/dev/null | grep -qF "$CRON_MARKER"; then
      crontab -l | grep -F "$CRON_MARKER" | sed 's/^/  /'
    else
      echo "  cron entry NOT installed"
    fi
  fi
}

# ─── status mode ────────────────────────────────────────────────────────────
if [[ "$STATUS" -eq 1 ]]; then show_status; exit 0; fi

# ─── uninstall mode ─────────────────────────────────────────────────────────
if [[ "$UNINSTALL" -eq 1 ]]; then
  if [[ "$OS_NAME" == "Darwin" ]]; then
    if [[ -f "$PLIST_FILE" ]]; then
      launchctl unload "$PLIST_FILE" 2>/dev/null || true
      rm -f "$PLIST_FILE"
      echo "removed $PLIST_FILE"
    else echo "no plist to remove"; fi
  else
    tmp=$(mktemp)
    crontab -l 2>/dev/null | grep -vF "$CRON_MARKER" > "$tmp" || true
    crontab "$tmp" && rm -f "$tmp"
    echo "removed cron entry"
  fi
  exit 0
fi

# ─── dry-run preview ────────────────────────────────────────────────────────
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "── DRY RUN — nothing will be written ──"
  echo
  echo "Loader script that would be written to $LOADER_SCRIPT:"; echo
  mk_loader | sed 's/^/  /'
  echo
  if [[ "$OS_NAME" == "Darwin" ]]; then
    echo "Plist that would be written to $PLIST_FILE:"; echo
    mk_plist | sed 's/^/  /'
    echo
    echo "Activation: launchctl load $PLIST_FILE"
  else
    echo "Cron line that would be appended (via crontab -):"
    echo "  $CRON_LINE"
  fi
  echo
  echo "Env-file template would be written to $ENV_FILE (if missing):"
  mk_env_template | sed 's/^/  /'
  exit 0
fi

# ─── install mode ───────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR" "$(dirname "$LOADER_SCRIPT")"

# loader
mk_loader > "$LOADER_SCRIPT"
chmod +x  "$LOADER_SCRIPT"
echo "wrote   $LOADER_SCRIPT"

# env-file template (don't overwrite if present)
if [[ ! -f "$ENV_FILE" ]]; then
  mk_env_template > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "wrote   $ENV_FILE (template — fill in secrets)"
else
  echo "kept    $ENV_FILE (existing)"
fi

if [[ "$OS_NAME" == "Darwin" ]]; then
  mkdir -p "$(dirname "$PLIST_FILE")"
  mk_plist > "$PLIST_FILE"
  echo "wrote   $PLIST_FILE"
  launchctl unload "$PLIST_FILE" 2>/dev/null || true
  launchctl load   "$PLIST_FILE"
  echo "loaded  $PLIST_LABEL (runs every 15 min, first run on next agent wake)"
  echo
  echo "Verify: launchctl list | grep $PLIST_LABEL"
  echo "Tail  : tail -f $LOG_FILE"
else
  # cron — append uniquely
  tmp=$(mktemp)
  ( crontab -l 2>/dev/null | grep -vF "$CRON_MARKER" || true ) > "$tmp"
  echo "$CRON_LINE" >> "$tmp"
  crontab "$tmp" && rm -f "$tmp"
  echo "installed cron entry (every 15 min)"
  echo
  echo "Verify: crontab -l | grep klaravex-signals"
  echo "Tail  : tail -f $LOG_FILE"
fi

echo
echo "Next: fill secrets in $ENV_FILE, then test once with:"
echo "  $LOADER_SCRIPT"
echo "Or run the collector directly:"
echo "  bun $COLLECTOR --dry-run --verbose"
