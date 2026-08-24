#!/usr/bin/env bash
# Phase 0: inventory Celery beat / revenue-task hints in live klaravex.
# Read-only against /home/anthony/klaravex — writes only under Klaravex2.0/docs/.
set -euo pipefail

KLARAVEX="${KLARAVEX_ROOT:-/home/anthony/klaravex}"
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/docs"
OUT="$OUT_DIR/inventory-beat.todo.md"
mkdir -p "$OUT_DIR"

{
  echo "# Beat / revenue inventory (Phase 0 stub)"
  echo
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Source tree: \`$KLARAVEX\` (read-only scan)"
  echo
  echo "## Next actions"
  echo
  echo "- [ ] Map each match to a Growth stream or \`n/a\`"
  echo "- [ ] Decide shadow vs ignore for non-growth beat entries"
  echo "- [ ] Record cutover owner per stream"
  echo
  echo "## ripgrep hints"
  echo
} >"$OUT"

scan() {
  local label="$1"
  local pattern="$2"
  echo "### $label" >>"$OUT"
  echo >>"$OUT"
  echo '```' >>"$OUT"
  if [[ -d "$KLARAVEX" ]]; then
    rg -n --no-heading -S "$pattern" "$KLARAVEX" \
      --glob '!**/node_modules/**' \
      --glob '!**/.venv/**' \
      --glob '!**/venv/**' \
      --glob '!**/__pycache__/**' \
      --glob '!**/.git/**' \
      --glob '!**/dist/**' \
      --glob '!**/build/**' \
      2>/dev/null | head -n 80 || echo "(no matches or rg unavailable)"
  else
    echo "(klaravex root missing: $KLARAVEX)"
  fi >>"$OUT"
  echo '```' >>"$OUT"
  echo >>"$OUT"
}

scan "celery beat / Celery beat" "celery[._ ]?beat|CeleryBeat|beat_schedule"
scan "revenue / growth task names" "revenue.?agent|growth.?os|revenue_agents"
scan "crontab / OnCalendar nearby" "crontab|OnCalendar|beat_schedule\\s*="
scan "charter stream names" "socials|seo-blog|gatekeeper|freelance"

echo "Wrote $OUT"
