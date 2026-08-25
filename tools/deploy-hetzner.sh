#!/bin/bash
# ⚠️ LEGACY DEPLOY — TARGET DECOMMISSIONED (2026-07-06)
#
# This script deploys to the RETIRED Hetzner CX22 (178.105.84.32).
# klaravex-api migrated to Azure Container Apps on 2026-07-05/06
# and the CX22 is now read-only (kept in tailnet as `hetzner-cx22`,
# 100.78.231.58, no new deploys).
#
# Current deploy paths (source of truth: runbooks/rig-usa-ha-stack-2026-07-01.md):
#   - Azure Container Apps for klaravex-api (rebuild + push to ACR)
#   - Rig (`anthony-klaravex`, Tailscale 100.75.10.114) for Ollama + LiteLLM + Celery worker
#   - Hetzner USA (`hetzner-usa-watchdog`, Tailscale 100.66.236.56 / public 87.99.147.244)
#     for HA standby (pg_auto_failover secondary, second LiteLLM/Worker, HAProxy edge, watchdog)
#
# Do NOT run this script against 178.105.84.32 for production changes.
# Kept in-repo for archaeological reference to the pre-migration flow.
#
# Original comment:
# Deploy Klaravex Loki backend to Hetzner CX22 (178.105.84.32).
# Used by Loki Mode for Phase D (PRD §6 CR-1). Exits 0 only on full success.

set -euo pipefail

SSH_KEY="${SSH_KEY:-$HOME/.ssh/loki_auto}"
HETZNER_HOST="${HETZNER_HOST:-178.105.84.32}"
HETZNER_USER="${HETZNER_USER:-root}"
REMOTE_BASE="${REMOTE_BASE:-/opt/loki/klaravex}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.klaravex.yml}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f "$SSH_KEY" ]; then
  echo "FAIL: SSH key not found at $SSH_KEY" >&2
  exit 1
fi

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes"

echo "[deploy] sanity ping..."
ssh $SSH_OPTS "$HETZNER_USER@$HETZNER_HOST" 'echo "ssh ok: $(hostname) $(uname -r)"' || {
  echo "FAIL: cannot SSH to $HETZNER_USER@$HETZNER_HOST" >&2
  exit 2
}

echo "[deploy] mkdir target dirs..."
ssh $SSH_OPTS "$HETZNER_USER@$HETZNER_HOST" "mkdir -p $REMOTE_BASE/infra"

echo "[deploy] rsync code..."
RSYNC_OPTS="-az --delete --exclude=__pycache__ --exclude=*.pyc --exclude=.pytest_cache --exclude=node_modules"
rsync $RSYNC_OPTS -e "ssh $SSH_OPTS" \
  "$REPO_ROOT/infra/" "$HETZNER_USER@$HETZNER_HOST:$REMOTE_BASE/infra/"

echo "[deploy] docker compose up --build -d..."
ssh $SSH_OPTS "$HETZNER_USER@$HETZNER_HOST" "cd $REMOTE_BASE/infra && docker-compose -f $COMPOSE_FILE up --build -d" || {
  echo "FAIL: docker-compose up failed" >&2
  exit 3
}

echo "[deploy] waiting for api.klaravex.com to expose >=10 routes..."
for i in $(seq 1 24); do
  COUNT=$(curl -fs --max-time 5 https://api.klaravex.com/openapi.json 2>/dev/null \
    | jq '.paths | keys | length' 2>/dev/null || echo 0)
  if [ "${COUNT:-0}" -ge 10 ]; then
    echo "[deploy] OK: api.klaravex.com exposes $COUNT routes"
    exit 0
  fi
  sleep 5
done

echo "FAIL: api.klaravex.com still has <10 routes after 2 minutes" >&2
exit 4
