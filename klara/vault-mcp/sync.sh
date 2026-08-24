#!/bin/bash
# ============================================================
# sync.sh — Klara AI Vault Git Auto-Sync  (patched 2026-06-06)
# Runs on the Cloud86 host every 30 minutes via cron.
# Pulls the latest vault from git; ON CHANGE it (1) enqueues new
# notes via bulk-index.py, then (2) kicks the vault-mcp embedding
# worker. This closes the gap where new commits were pulled but
# never embedded (index silently drifted).
#
# Required env (cron sets these):
#   VAULT_REPO_PATH  — path to the cloned vault git repo (default $HOME/loki-vault; /opt deprecated 2026-08-16)
#   MCP_ENDPOINT     — base URL of vault-mcp (default http://localhost:3141)
#   MCP_API_KEY      — auth token (optional)
#   DATABASE_URL     — optional; if unset, derived from the loki-vault-mcp container
# ============================================================
set -euo pipefail

VAULT_REPO_PATH="${VAULT_REPO_PATH:-$HOME/loki-vault}"
MCP_ENDPOINT="${MCP_ENDPOINT:-http://localhost:3141}"
MCP_API_KEY="${MCP_API_KEY:-}"
LOG_TAG="loki-sync"
BULK_INDEX="/root/loki-vault-mcp/bulk-index.py"
MCP_CONTAINER="${MCP_CONTAINER:-loki-vault-mcp}"

log() { echo "[$(date -Iseconds)] [$LOG_TAG] $*"; }
die() { log "ERROR: $*"; exit 1; }

# Container uses host alias @postgres; on the host that DB is at @localhost.
resolve_db_url() {
  if [[ -n "${DATABASE_URL:-}" ]]; then echo "$DATABASE_URL"; return 0; fi
  docker exec "$MCP_CONTAINER" printenv DATABASE_URL 2>/dev/null | sed 's/@postgres:/@localhost:/'
}

enqueue_new_notes() {
  local db_url; db_url="$(resolve_db_url || true)"
  if [[ -z "$db_url" ]]; then
    log "WARNING: no DATABASE_URL — skipping bulk-index (new notes will NOT be embedded)"; return 0
  fi
  command -v python3 >/dev/null 2>&1 || { log "WARNING: python3 missing — skipping bulk-index"; return 0; }
  [[ -f "$BULK_INDEX" ]] || { log "WARNING: $BULK_INDEX missing — skipping bulk-index"; return 0; }
  log "Enqueuing new notes via bulk-index.py"
  if python3 "$BULK_INDEX" --vault-path "$VAULT_REPO_PATH" --db-url "$db_url" 2>&1 | sed 's/^/[bulk-index] /'; then
    log "bulk-index complete"
  else
    log "WARNING: bulk-index.py exited non-zero"
  fi
}

trigger_reindex() {
  local endpoint="${MCP_ENDPOINT}/reindex"
  local http_args=(-s -o /dev/null -w "%{http_code}" -X POST "$endpoint")
  [[ -n "$MCP_API_KEY" ]] && http_args+=(-H "X-API-Key: $MCP_API_KEY")
  local code; code=$(curl "${http_args[@]}" || echo "000")
  if [[ "$code" == "200" ]]; then log "Reindex worker triggered (HTTP $code)"; else log "WARNING: /reindex returned HTTP $code"; fi
}

command -v git  >/dev/null 2>&1 || die "git not found in PATH"
command -v curl >/dev/null 2>&1 || die "curl not found in PATH"
[[ -d "$VAULT_REPO_PATH/.git" ]] || die "Vault repo not found at $VAULT_REPO_PATH"

log "Starting vault sync — repo: $VAULT_REPO_PATH"
cd "$VAULT_REPO_PATH"

if ! git diff --quiet || ! git diff --cached --quiet; then
  log "WARNING: local changes detected — stashing before pull"
  git stash push -m "auto-stash-before-sync-$(date +%s)"
fi

BEFORE=$(git rev-parse HEAD)
git fetch --quiet origin 2>&1 || die "git fetch failed"

if git rev-parse --verify origin/main >/dev/null 2>&1; then REMOTE_BRANCH="origin/main"
elif git rev-parse --verify origin/master >/dev/null 2>&1; then REMOTE_BRANCH="origin/master"
else die "Could not find origin/main or origin/master"; fi

git merge --ff-only "$REMOTE_BRANCH" 2>&1 || die "git merge failed (non-fast-forward)."
AFTER=$(git rev-parse HEAD)

if [[ "$BEFORE" == "$AFTER" ]]; then
  log "No changes — vault is up to date ($BEFORE)"; exit 0
fi

CHANGED_FILES=$(git diff --name-only "$BEFORE" "$AFTER" | wc -l)
log "Vault updated: $BEFORE -> $AFTER ($CHANGED_FILES files changed)"

enqueue_new_notes     # NEW: put new notes into the submission queue
trigger_reindex       # kick the embedding worker to drain the queue

log "Sync complete"
