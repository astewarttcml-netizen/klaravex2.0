#!/usr/bin/env bash
# safe-restart-growth-api.sh — restart growth-api.service only when no charter
# run is genuinely in-flight. Refuses (exit 1) if any run with status
# accepted/running started within the last --hours hours (default 2). Stale
# orphaned runs older than the window are ignored (they are reconciled to
# `failed` on startup by Fix B in growth/api/main.py).
#
# Usage: safe-restart-growth-api.sh [--hours N] [--dry-run]
# No external deps beyond python3 + systemctl.
set -euo pipefail

HOURS="${HOURS:-2}"
DRY_RUN=0
RUNS_PATH="/home/anthony/Klaravex2.0/growth/data/runs.jsonl"
UNIT="growth-api.service"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hours) HOURS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -f "$RUNS_PATH" ]]; then
  echo "safe-restart: $RUNS_PATH missing — proceeding (no runs to check)" >&2
fi

# Determine in-flight runs (latest record per id with status accepted/running
# whose started_at is within the last $HOURS hours). Pure python3, no jq.
INFLIGHT_JSON="$(python3 - "$RUNS_PATH" "$HOURS" <<'PY'
import json, sys, datetime
path, hours = sys.argv[1], float(sys.argv[2])
cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
by_id = {}
try:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "gate_verdict":
                continue
            rid = rec.get("id")
            if not rid:
                continue
            prev = by_id.get(rid)
            if prev is None:
                by_id[rid] = rec
            else:
                prev.update(rec)
except FileNotFoundError:
    pass
inflight = []
for rid, rec in by_id.items():
    if rec.get("status") not in ("accepted", "running"):
        continue
    started = rec.get("started_at") or rec.get("finished_at")
    try:
        ts = datetime.datetime.fromisoformat(started.replace("Z", "+00:00")) if started else None
    except (ValueError, AttributeError):
        ts = None
    if ts is None or ts > cutoff:
        inflight.append({"id": rid, "stream": rec.get("stream"), "status": rec.get("status"), "started_at": started})
print(json.dumps(inflight, ensure_ascii=False))
PY
)"

COUNT="$(python3 -c 'import json,sys; print(len(json.loads(sys.argv[1])))' "$INFLIGHT_JSON")"

if [[ "$COUNT" -gt 0 ]]; then
  echo "safe-restart: REFUSING — $COUNT in-flight run(s) within last ${HOURS}h:" >&2
  python3 -c 'import json,sys; [print(f"  {r[\"stream\"]} {r[\"id\"]} {r[\"status\"]} {r[\"started_at\"]}") for r in json.loads(sys.argv[1])]' "$INFLIGHT_JSON" >&2
  echo "safe-restart: wait for them to finish, or mark them failed via sweep_stale_runs.py, then retry." >&2
  exit 1
fi

echo "safe-restart: no in-flight runs within last ${HOURS}h — proceeding."
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "safe-restart: --dry-run set; would run: systemctl --user restart $UNIT"
  exit 0
fi

systemctl --user restart "$UNIT"

# Verify
sleep 1
STATE="$(systemctl --user is-active "$UNIT" 2>/dev/null || true)"
if [[ "$STATE" == "active" ]]; then
  echo "safe-restart: $UNIT active"
else
  echo "safe-restart: WARNING — $UNIT not active (state=$STATE)" >&2
  exit 3
fi

# Confirm port 4210 listening
if ss -ltn 2>/dev/null | grep -q ':4210 '; then
  echo "safe-restart: port 4210 listening"
else
  echo "safe-restart: WARNING — port 4210 not detected as listening (ss may be unavailable)" >&2
fi
exit 0
