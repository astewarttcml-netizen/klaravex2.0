#!/usr/bin/env bash
# =============================================================================
# loki-watchdog-azure.sh — health probe + self-heal for klaravex-api on Azure
#
# Runs from a systemd timer (or GitHub Actions cron, or Healthchecks.io paid
# active check) every 5–10 min. Probes the public api.klaravex.com endpoint
# and a SHALLOW set of synthetic-traffic routes. On failure, attempts a
# bounded self-heal via `az containerapp revision restart`. Always pings
# Healthchecks.io so an EXTERNAL system catches "watchdog itself is dead".
#
# DESIGN delta from infra/watchdog/loki-watchdog.sh (legacy Hetzner):
#   - No docker compose access (Azure Container App is managed).
#   - Probes are HTTP-only, against the public hostname.
#   - "Heal" = az revision restart; "give up" = surface to PagerDuty/email.
#   - Watchdog is HOST-AGNOSTIC — can run from any box with `az` + `curl`.
#
# Exit: 0 = healthy or healed; 10 = still down after heal attempts.
# =============================================================================
set -euo pipefail

# Self-source default env file for manual runs (HOST_LABEL set = systemd loaded it).
[[ -z "${HOST_LABEL:-}" && -f /etc/loki-watchdog-azure.env ]] && source /etc/loki-watchdog-azure.env

# ---- Config (override in /etc/loki-watchdog-azure.env) ----------------------
KLARAVEX_API="${KLARAVEX_API:-https://api.klaravex.com}"
KLARAVEX_API_HEALTH="${KLARAVEX_API_HEALTH:-${KLARAVEX_API}/health}"
KLARAVEX_API_OPENAPI="${KLARAVEX_API_OPENAPI:-${KLARAVEX_API}/openapi.json}"

AZURE_RG="${AZURE_RG:-klaravex-prod}"
AZURE_APP="${AZURE_APP:-klaravex-api}"

# Healthchecks.io ping URL — set HEALTHCHECK_URL in /etc/loki-watchdog-azure.env.
# Empty = no external ping (degraded mode; still probes + heals, just no
# off-host dead-man's-switch).
HEALTHCHECK_URL="${HEALTHCHECK_URL:-}"

# Self-heal cadence — restart the revision after this many consecutive
# failed probes within FLAP_WINDOW_SECONDS. Default 2 / 30 min.
HEAL_AFTER_FAILS="${HEAL_AFTER_FAILS:-2}"
FLAP_WINDOW_SECONDS="${FLAP_WINDOW_SECONDS:-1800}"

# After this many heals within FLAP_WINDOW_SECONDS, stop healing — surface
# to humans instead. Default 3.
MAX_HEALS_PER_WINDOW="${MAX_HEALS_PER_WINDOW:-3}"

# Where the watchdog persists its flap counters.
STATE_DIR="${STATE_DIR:-/var/lib/loki-watchdog-azure}"
HOST_LABEL="${HOST_LABEL:-$(hostname -s)}"

# Public-status JSON output (consumed by api.klaravex.com/static/watchdog-status.json
# style externalisation — same pattern as W11 from the legacy watchdog).
STATUS_JSON="${STATUS_JSON:-${STATE_DIR}/watchdog-status.json}"

# Timeouts
CURL_TIMEOUT="${CURL_TIMEOUT:-10}"
AZ_TIMEOUT="${AZ_TIMEOUT:-60}"

# ---- Helpers ----------------------------------------------------------------
mkdir -p "$STATE_DIR"

log() { printf "[%s] [%s] %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$HOST_LABEL" "$*" >&2; }
now_epoch() { date +%s; }

ping_healthcheck() {
  local suffix="${1:-}"  # "" | /fail | /start
  [[ -z "$HEALTHCHECK_URL" ]] && return 0
  curl -fsS -m 10 --retry 2 --retry-delay 2 -o /dev/null \
    "${HEALTHCHECK_URL}${suffix}" 2>/dev/null || true
}

write_status_json() {
  local rc="$1" healthy="$2" detail="$3"
  printf '{"host":"%s","ts":"%s","rc":%d,"healthy":%s,"detail":%s}\n' \
    "$HOST_LABEL" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$rc" "$healthy" \
    "$(printf '%s' "$detail" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
    > "${STATUS_JSON}.tmp" && mv "${STATUS_JSON}.tmp" "$STATUS_JSON"
}

# ---- Probes -----------------------------------------------------------------
probe_health() {
  local body http_code db_field status_field
  body="$(curl -fsS -m "$CURL_TIMEOUT" "$KLARAVEX_API_HEALTH" 2>/dev/null || echo "")"
  http_code="$(curl -s -o /dev/null -w "%{http_code}" -m "$CURL_TIMEOUT" "$KLARAVEX_API_HEALTH" 2>/dev/null || echo "000")"

  if [[ "$http_code" != "200" || -z "$body" ]]; then
    echo "HTTP $http_code body=$body"
    return 1
  fi

  status_field="$(printf '%s' "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status",""))' 2>/dev/null || echo "")"
  if [[ "$status_field" != "ok" && "$status_field" != "healthy" ]]; then
    echo "/health returned status=$status_field"
    return 1
  fi

  # DB field, if present, must be reachable. Allow missing field (some envs).
  db_field="$(printf '%s' "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("db",""))' 2>/dev/null || echo "")"
  if [[ -n "$db_field" && "$db_field" != "ok" && "$db_field" != "true" ]]; then
    echo "/health returned db=$db_field"
    return 1
  fi

  echo "health ok"
  return 0
}

probe_route_count() {
  # Soft probe: openapi.json should expose >10 paths. Catches "app booted but
  # most routers crashed silently on import".
  local n
  n="$(curl -fsS -m "$CURL_TIMEOUT" "$KLARAVEX_API_OPENAPI" 2>/dev/null \
        | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d.get("paths",{})))' 2>/dev/null \
        || echo "0")"
  if [[ "$n" -lt 10 ]]; then
    echo "openapi only $n paths (expected >=10)"
    return 1
  fi
  echo "openapi $n paths"
  return 0
}

# ---- Heal ladder ------------------------------------------------------------
heal_restart_revision() {
  if ! command -v az >/dev/null 2>&1; then
    log "az CLI not installed — cannot self-heal; surfacing to humans"
    return 1
  fi

  local active
  active="$(timeout "$AZ_TIMEOUT" az containerapp revision list \
            -g "$AZURE_RG" -n "$AZURE_APP" \
            --query "[?properties.active].name | [0]" -o tsv 2>/dev/null || echo "")"
  if [[ -z "$active" ]]; then
    log "could not find active revision"
    return 1
  fi

  log "restarting revision $active"
  if timeout "$AZ_TIMEOUT" az containerapp revision restart \
        -g "$AZURE_RG" -n "$AZURE_APP" --revision "$active" >/dev/null 2>&1; then
    log "restart issued; waiting 30s before re-probe"
    sleep 30
    return 0
  fi
  log "az revision restart failed"
  return 1
}

# ---- Flap counter persistence ------------------------------------------------
FAIL_LOG="${STATE_DIR}/fails.log"
HEAL_LOG="${STATE_DIR}/heals.log"

record_event() {
  local kind="$1"; local file="${STATE_DIR}/${kind}.log"
  echo "$(now_epoch)" >> "$file"
  # Trim to last 100 entries.
  tail -n 100 "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
}

count_within_window() {
  local file="$1"; local cutoff=$(( $(now_epoch) - FLAP_WINDOW_SECONDS ))
  [[ -f "$file" ]] || { echo 0; return; }
  awk -v c="$cutoff" '$1 >= c' "$file" | wc -l | tr -d ' '
}

# ---- Main -------------------------------------------------------------------
main() {
  ping_healthcheck "/start"
  log "probing $KLARAVEX_API"

  local detail=""
  local healed=false

  # Layered probe
  detail="$(probe_health)" && health_rc=0 || health_rc=1
  if [[ $health_rc -eq 0 ]]; then
    detail+=" | $(probe_route_count)" && routes_rc=0 || routes_rc=1
    [[ $routes_rc -ne 0 ]] && health_rc=1
  fi

  if [[ $health_rc -eq 0 ]]; then
    log "OK — $detail"
    # Reset fail counter on success.
    : > "$FAIL_LOG"
    ping_healthcheck ""
    write_status_json 0 true "$detail"
    exit 0
  fi

  log "DOWN — $detail"
  record_event "fails"
  local fails; fails="$(count_within_window "$FAIL_LOG")"
  log "fails in last ${FLAP_WINDOW_SECONDS}s: $fails"

  if (( fails < HEAL_AFTER_FAILS )); then
    log "below HEAL_AFTER_FAILS ($HEAL_AFTER_FAILS) — not healing yet"
    ping_healthcheck "/fail"
    write_status_json 10 false "$detail (not healing — under threshold)"
    exit 10
  fi

  local heals; heals="$(count_within_window "$HEAL_LOG")"
  if (( heals >= MAX_HEALS_PER_WINDOW )); then
    log "already healed $heals times in window — escalating, not healing"
    ping_healthcheck "/fail"
    write_status_json 10 false "$detail (chronic — escalated)"
    exit 10
  fi

  log "attempting heal — restart Azure revision"
  if heal_restart_revision; then
    record_event "heals"
    if detail="$(probe_health)"; then
      log "post-heal probe OK — $detail"
      : > "$FAIL_LOG"
      ping_healthcheck ""
      write_status_json 0 true "healed: $detail"
      exit 0
    fi
    log "post-heal probe FAILED — $detail"
  fi

  ping_healthcheck "/fail"
  write_status_json 10 false "$detail (heal failed)"
  exit 10
}

main "$@"
