#!/usr/bin/env bash
# klara-stack-watchdog.sh — USA host health probe for Klaravex2.0-owned surfaces.
# Ownership: Klaravex2.0/klara/watchdog (2026-08-25).
# Does NOT run the Cloud86 loki-watchdog (wrong container names for this host).
set -u

STATE_DIR="${STATE_DIR:-$HOME/.local/state/klara-stack-watchdog}"
LOG_TAG="klara-stack-watchdog"
mkdir -p "$STATE_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$LOG_TAG] $*"; }

fail=0
detail=()

probe_http() {
  local name="$1" url="$2" expect="${3:-200}"
  local code
  code=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 8 "$url" 2>/dev/null || echo 000)
  if [[ "$code" == "$expect" ]] || [[ "$expect" == "2xx" && "$code" =~ ^2 ]]; then
    log "OK  $name ($code) $url"
    return 0
  fi
  log "BAD $name ($code) $url"
  detail+=("$name:$code")
  fail=1
  return 1
}

probe_systemd_user() {
  local unit="$1"
  if systemctl --user is-active --quiet "$unit"; then
    log "OK  systemd $unit"
    return 0
  fi
  log "BAD systemd $unit"
  detail+=("systemd:$unit")
  fail=1
  return 1
}

heal_container() {
  local name="$1"
  if docker inspect "$name" >/dev/null 2>&1; then
    log "HEAL docker restart $name"
    docker restart "$name" >/dev/null 2>&1 || log "HEAL failed $name"
  fi
}

# --- Probes (Klaravex2.0 ownership surface) ---------------------------------
probe_http "vault-mcp" "http://127.0.0.1:3141/health" "2xx" || heal_container klara-vault-mcp
probe_http "klaravex-api" "http://127.0.0.1:8002/health" "200" || heal_container klaravex_api
probe_http "growth-api" "http://127.0.0.1:4210/healthz" "200"
probe_http "voice" "http://127.0.0.1:8440/health" "200"
probe_http "klaravex-os" "http://127.0.0.1:4100/api/agents" "200"

probe_systemd_user growth-api.service
probe_systemd_user klaravex-voice.service
probe_systemd_user klara-rarv-heartbeat.timer

date -u +%Y-%m-%dT%H:%M:%SZ > "$STATE_DIR/heartbeat"
echo "$fail" > "$STATE_DIR/last_rc"
printf '%s\n' "${detail[@]:-}" > "$STATE_DIR/last_detail"

if [[ "$fail" -eq 0 ]]; then
  log "all probes healthy"
  exit 0
fi
log "unhealthy: ${detail[*]}"
exit 10
