#!/usr/bin/env bash
# Phase 5 — verify Layer D → Layer C wiring and adapter registry.
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
OS_BASE="${KLARAVEX_OS_URL:-http://127.0.0.1:4100}"

echo "=== Phase 5 verification ==="
echo "Growth health:"
curl -sS "$BASE/healthz" | python3 -m json.tool

echo ""
echo "Adapters (Layer C):"
curl -sS -H "X-Growth-Secret: $SECRET" "$BASE/v1/adapters" | python3 -m json.tool

echo ""
echo "Invoke smartlead (sandbox):"
curl -sS -X POST -H "X-Growth-Secret: $SECRET" "$BASE/v1/adapters/smartlead/invoke" | python3 -m json.tool

echo ""
echo "klaravex-os proxy (adapters):"
curl -sS "$OS_BASE/api/growth/adapters" 2>/dev/null | python3 -m json.tool || echo "(klaravex-os not running — start :4100 to verify D proxy)"

echo ""
echo "=== Phase 5 checks done ==="
