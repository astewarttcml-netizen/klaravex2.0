#!/usr/bin/env bash
# =============================================================================
# loki-watchdog.sh — health-check + self-heal for the Klara AI stack on ONE host
#
# Runs from a systemd timer every 30 min. Detects the "running but broken"
# states that Docker's `restart: unless-stopped` policy CANNOT see:
#   - vault-mcp process alive but /health returns 503 or db:false
#   - embedding worker stalled (note_submissions backing up)
#   - ollama daemon alive but the embedding model is missing/unloaded
#   - postgres up but not accepting connections
#
# Heal ladder (per service, bounded within a single run):
#   probe -> up -d -> restart -> restart -> rebuild+up -> give up + CRIT alert
# "Rebuild" happens ONLY after restarts fail (per operator decision).
# A flap counter persists across runs so chronic failures escalate instead of
# silently looping every 30 min.
#
# DESIGN: one watchdog per host (Cloud86, Hetzner). Self-heal is LOCAL so it
# keeps working during a network partition. A separate EXTERNAL dead-man's-
# switch (see INSTALL-watchdog.md, Layer 2) catches a host that is fully down,
# because a dead host cannot alert about itself.
#
# Exit: 0 = all healthy or healed this run; 10 = >=1 service still down.
# =============================================================================
set -euo pipefail

# Self-source default env file for manual runs (HOST_LABEL already set = systemd loaded it).
[[ -z "${HOST_LABEL:-}" && -f /etc/loki-watchdog.env ]] && source /etc/loki-watchdog.env

# ---- Config (override in /etc/loki-watchdog.env) ----------------------------
COMPOSE_DIR="${COMPOSE_DIR:-$HOME/loki-vault}"
COMPOSE_FILE="${COMPOSE_FILE:-$COMPOSE_DIR/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env}"

HOST_LABEL="${HOST_LABEL:-$(hostname -s)}"

# Which checks to run on THIS host (Hetzner Klara AI has no local pg/ollama -> set false)
WATCH_POSTGRES="${WATCH_POSTGRES:-true}"
WATCH_OLLAMA="${WATCH_OLLAMA:-true}"
WATCH_MCP="${WATCH_MCP:-true}"
WATCH_QUEUE="${WATCH_QUEUE:-true}"     # embedding-queue stall check (needs local pg)

# Container + service names (compose service names are the 2nd arg to heal())
PG_CONTAINER="${PG_CONTAINER:-loki-postgres}"
OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-loki-ollama}"
MCP_CONTAINER="${MCP_CONTAINER:-loki-vault-mcp}"
MCP_SERVICE="${MCP_SERVICE:-vault-mcp}"
MCP_LABEL="${MCP_LABEL:-mcp}"

# App probes
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:3141/health}"
HEALTH_STATUS_VALUE="${HEALTH_STATUS_VALUE:-healthy}"   # expected value of "status" field
HEALTH_REQUIRE_DB="${HEALTH_REQUIRE_DB:-true}"          # require "db":true in health response
MCP_API_KEY="${MCP_API_KEY:-}"
OLLAMA_MODEL="${OLLAMA_MODEL:-nomic-embed-text}"
PG_DB="${PG_DB:-loki_vault}"
PG_USER="${PG_USER:-postgres}"

# Thresholds / timing
QUEUE_STALL_SECONDS="${QUEUE_STALL_SECONDS:-600}"  # oldest pending older than this => worker stalled
PROBE_RETRIES="${PROBE_RETRIES:-5}"
PROBE_WAIT="${PROBE_WAIT:-6}"                       # seconds between probe retries
RESTART_SETTLE="${RESTART_SETTLE:-20}"             # seconds after a restart before re-probing

# Alerting
WEBHOOK_URL="${WEBHOOK_URL:-}"                      # Slack/Discord/generic; blank => log only
HEALTHCHECK_URL="${HEALTHCHECK_URL:-}"             # healthchecks.io ping URL; blank => skip

# State
STATE_DIR="${STATE_DIR:-/var/lib/loki-watchdog}"
LOCK_FILE="${LOCK_FILE:-/run/loki-watchdog.lock}"
LOG_TAG="loki-watchdog"

COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")

mkdir -p "$STATE_DIR"

# ---- single instance (a slow rebuild must not overlap the next timer) -------
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "[$LOG_TAG] previous run still active — skipping"; exit 0; }

# ---- logging + alerting -----------------------------------------------------
log(){ echo "[$(date -Iseconds)] [$HOST_LABEL] $*"; }

alert(){   # alert <SEVERITY> <message...>
  local sev="$1"; shift; local msg="$*"
  log "ALERT[$sev] $msg"
  [[ -z "$WEBHOOK_URL" ]] && return 0
  local text="[$sev] Klara AI watchdog @ ${HOST_LABEL}: ${msg}"
  # Dual key payload works with Slack ("text") and Discord ("content")
  curl -fsS -m 10 -X POST "$WEBHOOK_URL" -H 'Content-Type: application/json' \
    -d "$(printf '{"text":"%s","content":"%s"}' "$text" "$text")" >/dev/null 2>&1 \
    || log "WARN: webhook POST failed"
}

# ---- low-level probes (0 = healthy, non-0 = unhealthy) ----------------------
container_running(){ [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" == "true" ]]; }

probe_postgres(){
  container_running "$PG_CONTAINER" || return 1
  docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1
}

probe_ollama(){
  container_running "$OLLAMA_CONTAINER" || return 1
  docker exec "$OLLAMA_CONTAINER" ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"
}

probe_mcp(){
  container_running "$MCP_CONTAINER" || return 1
  local hdr=(); [[ -n "$MCP_API_KEY" ]] && hdr=(-H "X-API-Key: $MCP_API_KEY")
  local body norm
  body=$(curl -fsS -m 8 "${hdr[@]}" "$HEALTH_URL" 2>/dev/null) || return 1
  norm=$(printf '%s' "$body" | tr -d ' \t\n')
  echo "$norm" | grep -q "\"status\":\"${HEALTH_STATUS_VALUE:-healthy}\"" || return 1
  [[ "${HEALTH_REQUIRE_DB:-true}" == "true" ]] && { echo "$norm" | grep -q '"db":true' || return 1; }
  # Worker-stall detection: oldest pending submission older than threshold.
  if [[ "$WATCH_QUEUE" == "true" ]] && container_running "$PG_CONTAINER"; then
    local age
    age=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -tAc \
      "SELECT COALESCE(CEIL(EXTRACT(EPOCH FROM now()-min(created_at)))::int,0) \
         FROM note_submissions WHERE status='pending';" 2>/dev/null || echo 0)
    age=${age//[^0-9]/}; age=${age:-0}
    if (( age > QUEUE_STALL_SECONDS )); then
      log "mcp: embedding queue STALLED (oldest pending ${age}s > ${QUEUE_STALL_SECONDS}s)"
      return 1
    fi
  fi
  return 0
}

probe_retry(){  # probe_retry <probe_fn> — true if healthy within PROBE_RETRIES
  local fn="$1" i
  for ((i=1; i<=PROBE_RETRIES; i++)); do
    "$fn" && return 0
    sleep "$PROBE_WAIT"
  done
  return 1
}

# ---- heal ladder ------------------------------------------------------------
heal(){  # heal <label> <compose_service> <probe_fn>
  local name="$1" svc="$2" probe="$3"
  local fails_file="$STATE_DIR/$name.fails"

  if probe_retry "$probe"; then
    echo 0 > "$fails_file"
    log "$name: healthy"
    return 0
  fi

  local fails; fails=$(cat "$fails_file" 2>/dev/null || echo 0); fails=$((fails+1))
  echo "$fails" > "$fails_file"
  alert WARN "$name UNHEALTHY (consecutive failing runs: $fails) — beginning heal"

  # Step 0: ensure it's at least up (handles a removed/exited container)
  "${COMPOSE[@]}" up -d "$svc" >/dev/null 2>&1 || true
  sleep "$RESTART_SETTLE"
  if probe_retry "$probe"; then alert INFO "$name recovered (up -d)"; echo 0 > "$fails_file"; return 0; fi

  # Step 1-2: restart twice
  local r
  for r in 1 2; do
    log "$name: restart attempt $r/2"
    "${COMPOSE[@]}" restart "$svc" >/dev/null 2>&1 || true
    sleep "$RESTART_SETTLE"
    if probe_retry "$probe"; then alert INFO "$name recovered (restart #$r)"; echo 0 > "$fails_file"; return 0; fi
  done

  # Step 3: rebuild — ONLY because restarts failed
  log "$name: restarts exhausted — rebuilding image for $svc"
  alert WARN "$name still down after 2 restarts — rebuilding $svc"
  if "${COMPOSE[@]}" build "$svc" >/dev/null 2>&1 && "${COMPOSE[@]}" up -d "$svc" >/dev/null 2>&1; then
    sleep "$RESTART_SETTLE"
    if probe_retry "$probe"; then alert INFO "$name recovered (rebuild)"; echo 0 > "$fails_file"; return 0; fi
  fi

  alert CRIT "$name STILL DOWN after restart+rebuild (failing runs: $fails) — MANUAL INTERVENTION REQUIRED"
  return 1
}

# ---- cheap pre-step: make sure the embedding model is present ----------------
ensure_ollama_model(){
  container_running "$OLLAMA_CONTAINER" || return 0
  if ! docker exec "$OLLAMA_CONTAINER" ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
    log "ollama: model $OLLAMA_MODEL missing — pulling"
    alert WARN "ollama model $OLLAMA_MODEL missing — pulling"
    docker exec "$OLLAMA_CONTAINER" ollama pull "$OLLAMA_MODEL" >/dev/null 2>&1 \
      || alert CRIT "ollama pull $OLLAMA_MODEL FAILED — embeddings will not work"
  fi
}

# ---- main -------------------------------------------------------------------
[[ -d "$COMPOSE_DIR" ]] || { alert CRIT "COMPOSE_DIR $COMPOSE_DIR not found — cannot manage stack"; exit 10; }
cd "$COMPOSE_DIR"
log "watchdog run start (pg=$WATCH_POSTGRES ollama=$WATCH_OLLAMA mcp=$WATCH_MCP)"
rc=0

# Order matters: db -> ollama(+model) -> mcp (mcp depends on both).
[[ "$WATCH_POSTGRES" == "true" ]] && { heal postgres postgres probe_postgres || rc=10; }
if [[ "$WATCH_OLLAMA" == "true" ]]; then
  ensure_ollama_model
  heal ollama ollama probe_ollama || rc=10
fi
[[ "$WATCH_MCP" == "true" ]] && { heal "$MCP_LABEL" "$MCP_SERVICE" probe_mcp || rc=10; }

# Heartbeat consumed by the external dead-man's-switch (Layer 2).
date -Iseconds > "$STATE_DIR/heartbeat"
echo "$rc"      > "$STATE_DIR/last_rc"

# Write public status JSON for external HTTP monitor (served via nginx /static/).
# 2026-08-17: /opt deleted; align with az-watchdog pattern → ${STATE_DIR}/watchdog-status.json
WATCHDOG_STATUS_FILE="${WATCHDOG_STATUS_FILE:-${STATE_DIR}/watchdog-status.json}"
if [[ -d "$(dirname "$WATCHDOG_STATUS_FILE")" ]]; then
  printf '{"host":"%s","ts":"%s","rc":%s,"healthy":%s}\n' \
    "$HOST_LABEL" "$(date -Iseconds)" "$rc" "$([[ $rc -eq 0 ]] && echo true || echo false)" \
    > "$WATCHDOG_STATUS_FILE"
fi

# Ping external dead-man's-switch (healthchecks.io or compatible).
if [[ -n "$HEALTHCHECK_URL" ]]; then
  ping_url="${HEALTHCHECK_URL}$([[ $rc -ne 0 ]] && echo '/fail' || echo '')"
  curl -fsS -m 10 "$ping_url" >/dev/null 2>&1 || log "WARN: healthcheck ping failed ($ping_url)"
fi

log "watchdog run end rc=$rc"
exit "$rc"
