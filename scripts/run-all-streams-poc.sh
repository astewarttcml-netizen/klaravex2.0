#!/usr/bin/env bash
# Phase 3 POC — trigger every Growth stream once (shadow / pre-cutover smoke test).
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

if [[ -z "$SECRET" ]]; then
  echo "GROWTH_INTERNAL_SECRET not set (source $ENV_FILE)" >&2
  exit 1
fi

STREAMS=(leads socials seo-blog freelance gatekeeper ads kb backlinks)
echo "Growth API: $BASE"
echo "POC mode: ${GROWTH_POC_MODE:-false}"
echo "Triggering ${#STREAMS[@]} streams…"

for stream in "${STREAMS[@]}"; do
  echo "--- POST /v1/streams/$stream/run"
  curl -sS -X POST \
    -H "X-Growth-Secret: $SECRET" \
    -H "Content-Type: application/json" \
    "$BASE/v1/streams/$stream/run" | python3 -m json.tool || true
  sleep 0.5
done

echo ""
echo "Scorecard:"
curl -sS -H "X-Growth-Secret: $SECRET" "$BASE/v1/scorecard" | python3 -m json.tool
