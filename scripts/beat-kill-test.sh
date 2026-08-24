#!/usr/bin/env bash
# Phase 4 — beat-kill readiness check (does not stop beat unless BEAT_KILL_EXECUTE=1).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${GROWTH_ENV:-$ROOT/growth/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

BASE="${GROWTH_API_BASE:-http://127.0.0.1:4210}"
SECRET="${GROWTH_INTERNAL_SECRET:-}"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LOG="$ROOT/docs/beat-kill-${STAMP//:/-}.md"

mkdir -p "$ROOT/docs"

{
  echo "# Beat-kill test log — $STAMP"
  echo
  echo "## Pre-check"
  echo
  echo '```'
  echo "Growth health:"
  curl -sS "$BASE/healthz" || echo "healthz failed"
  echo
  echo "Growth timers:"
  systemctl --user list-timers 'growth-stream@*' 2>/dev/null || echo "(no user timers)"
  echo
  echo "Celery beat (docker):"
  docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -i beat || echo "(no beat container found)"
  echo '```'
  echo
  echo "## Scorecard (pre)"
  echo
  echo '```json'
  curl -sS -H "X-Growth-Secret: $SECRET" "$BASE/v1/scorecard" 2>/dev/null || echo '{}'
  echo
  echo '```'
} | tee "$LOG"

if [[ "${BEAT_KILL_EXECUTE:-0}" == "1" ]]; then
  echo ""
  echo "BEAT_KILL_EXECUTE=1 — stopping celery beat container (if present)…"
  docker stop klaravex-celery-beat 2>/dev/null || docker stop celery-beat 2>/dev/null || echo "No beat container to stop"
  WAIT="${BEAT_KILL_WAIT_S:-120}"
  echo "Waiting ${WAIT}s for Growth timer cadence…"
  sleep "$WAIT"
  {
    echo
    echo "## Post-wait scorecard"
    echo
    echo '```json'
    curl -sS -H "X-Growth-Secret: $SECRET" "$BASE/v1/scorecard"
    echo
    echo '```'
    echo
    echo "## Recent runs"
    echo
    echo '```json'
    curl -sS -H "X-Growth-Secret: $SECRET" "$BASE/v1/runs" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('runs',[])[-8:], indent=2))"
    echo
    echo '```'
  } | tee -a "$LOG"
  echo "Log written: $LOG"
else
  echo ""
  echo "Dry run only. To execute beat stop + wait:"
  echo "  BEAT_KILL_EXECUTE=1 BEAT_KILL_WAIT_S=120 $0"
  echo "Log written: $LOG"
fi
