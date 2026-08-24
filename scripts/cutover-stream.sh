#!/usr/bin/env bash
# Phase 3 — per-stream cutover helper (disable legacy schedule manually; this arms Growth).
set -euo pipefail

STREAM="${1:-}"
if [[ -z "$STREAM" ]]; then
  echo "Usage: $0 <stream>" >&2
  echo "Allowed: leads socials seo-blog freelance gatekeeper ads kb backlinks" >&2
  exit 1
fi

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

echo "=== Cutover prep: $STREAM ==="
echo "1. Review docs/cutover-checklist.md"
echo "2. Disable legacy schedule for $STREAM only"
echo "3. Enable timer: systemctl --user enable --now growth-stream@${STREAM}.timer"
echo ""

read -r -p "Enable growth-stream@${STREAM}.timer now? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
  systemctl --user enable --now "growth-stream@${STREAM}.timer"
  systemctl --user list-timers "growth-stream@${STREAM}.timer"
fi

echo ""
echo "Force one run via API…"
curl -sS -X POST -H "X-Growth-Secret: $SECRET" "$BASE/v1/streams/$STREAM/run" | python3 -m json.tool

echo ""
echo "Scorecard:"
curl -sS -H "X-Growth-Secret: $SECRET" "$BASE/v1/scorecard" | python3 -m json.tool
