# Klara AI SecondBrain — Deployment Runbook

**Environment:** Cloud86 Docker  
**Author:** Klara AI / Anthony  
**Date:** 2026-05-29

---

## Pre-flight Checklist

Before starting, confirm:

- [ ] Cloud86 host has Docker Engine 24+ and docker-compose v2 installed
- [ ] Port 3141 is open in the firewall / security group (inbound from your local IP only, or via VPN)
- [ ] `git` is installed on Cloud86 host (for sync.sh)
- [ ] OpenAI API key is available (`sk-proj-…`)
- [ ] Vault git repo URL is known (for Phase 3 clone)

---

## Phase 1 — Cloud86: Repo Setup

```bash
# SSH into Cloud86
ssh user@<cloud86-host>

# Clone THIS repo (contains all deployment artifacts)
git clone <your-repo-url> /opt/loki-vault
cd /opt/loki-vault

# Make sync.sh executable
chmod +x sync.sh
```

---

## Phase 2 — Configure Secrets

```bash
cd /opt/loki-vault

# Copy template
cp .env.example .env
chmod 600 .env   # owner-readable only

# Edit — fill in all CHANGE_ME values
nano .env
```

Required fields in `.env`:

| Variable | Description |
|---|---|
| `POSTGRES_PASSWORD` | Postgres superuser password (postgres user) |
| `VAULT_SYNC_PASSWORD` | vault_sync_service app password |
| `OPENAI_API_KEY` | OpenAI key for embeddings |
| `MCP_API_KEY` | Shared secret for API auth (or leave blank) |

Generate strong passwords:
```bash
openssl rand -hex 32   # run twice: one for POSTGRES_PASSWORD, one for VAULT_SYNC_PASSWORD
openssl rand -hex 32   # for MCP_API_KEY
```

---

## Phase 3 — Clone the Vault Repo

```bash
# Clone your Obsidian / markdown vault
git clone <vault-git-url> /opt/loki-vault/vault

# Set env vars for sync.sh (add to /etc/environment for cron)
echo 'VAULT_REPO_PATH=/opt/loki-vault/vault' | sudo tee -a /etc/environment
echo 'MCP_ENDPOINT=http://localhost:3141'     | sudo tee -a /etc/environment
# If MCP_API_KEY is set:
echo 'MCP_API_KEY=<your-key>'                 | sudo tee -a /etc/environment
```

---

## Phase 4 — Build & Start the Stack

```bash
cd /opt/loki-vault

# Build the vault-mcp image (first run takes ~2 min)
docker compose build --no-cache

# Start in detached mode
docker compose up -d

# Confirm both containers are running
docker compose ps
```

Expected output:
```
NAME              IMAGE                  STATUS
loki-postgres     pgvector/pgvector:pg16 Up (healthy)
loki-vault-mcp    loki-vault-mcp:latest  Up (healthy)
```

If vault-mcp shows "starting" for >30 s, check logs:
```bash
docker compose logs vault-mcp --tail 50
```

---

## Phase 5 — Verify Schema & pgvector

```bash
# Connect to postgres
docker exec -it loki-postgres psql -U postgres -d loki_vault

# Verify pgvector extension
SELECT * FROM pg_extension WHERE extname = 'vector';
-- Expected: 1 row

# Verify tables
\dt
-- Expected: vault_embeddings, note_submissions, memory_index

# Verify vault_sync_service user
SELECT usename, usesuper, usecreatedb FROM pg_user WHERE usename = 'vault_sync_service';
-- Expected: 1 row, all false

\q
```

---

## Phase 6 — Health Check

```bash
curl -s http://localhost:3141/health | python3 -m json.tool
```

Expected response:
```json
{
  "status": "healthy",
  "db": true,
  "dbLatencyMs": 2,
  "poolTotal": 2,
  "poolIdle": 2,
  "uptime": 14.3,
  "timestamp": "2026-05-29T00:00:00.000Z"
}
```

**Degraded response** (status 503) means DB is unreachable — check postgres container health.

---

## Phase 7 — Git Auto-Sync Cron

```bash
# Test sync.sh manually first
cd /opt/loki-vault && ./sync.sh

# Add cron job (runs every 30 minutes)
crontab -e
```

Add this line:
```
*/30 * * * * /opt/loki-vault/sync.sh >> /var/log/loki-sync.log 2>&1
```

Verify cron runs:
```bash
tail -f /var/log/loki-sync.log
```

---

## Phase 8 — Local Machine Setup

### a) Environment variables (`~/.zshrc`)

```bash
# Klara AI SecondBrain
export CLOUD86_HOST="<your-cloud86-ip-or-hostname>"
export LOKI_MCP_TOKEN="<your-MCP_API_KEY-value>"     # omit if no auth
export OPENAI_API_KEY="sk-proj-..."                   # if not already set
export VAULT_LOCAL_PATH="$HOME/vault"                 # path to local vault clone

source ~/.zshrc
```

### b) Configure .loki/config.yaml

The file is at `<this-repo>/.loki/config.yaml`. The `${CLOUD86_HOST}` and `${LOKI_MCP_TOKEN}` values are read from environment at runtime.

### c) Test connection from local machine

```bash
# Health check from local machine
curl -s http://${CLOUD86_HOST}:3141/health

# If MCP_API_KEY is set:
curl -s http://${CLOUD86_HOST}:3141/health -H "X-API-Key: $LOKI_MCP_TOKEN"
```

---

## Phase 9 — Integration Testing

### Test vault_submit_note

```bash
curl -s -X POST "http://${CLOUD86_HOST}:3141/messages?sessionId=TEST" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${LOKI_MCP_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": 1,
    "params": {
      "name": "vault_submit_note",
      "arguments": {
        "content": "Klara AI integration test note. This is a test entry to validate the SecondBrain pipeline.",
        "note_path": "System/integration-test.md",
        "note_title": "Integration Test Note",
        "metadata": {"source": "integration-test", "date": "2026-05-29"}
      }
    }
  }'
```

Expected: `{"status":"indexed","message":"Note indexed successfully.","note_path":"System/integration-test.md"}`

### Test vault_search

```bash
curl -s -X POST "http://${CLOUD86_HOST}:3141/messages?sessionId=TEST" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${LOKI_MCP_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": 2,
    "params": {
      "name": "vault_search",
      "arguments": {"query": "integration test SecondBrain", "limit": 3, "threshold": 0.5}
    }
  }'
```

Expected: results array containing the test note with similarity > 0.5.

### Test vault_read

```bash
# Use note_id from vault_search result above
curl -s -X POST "http://${CLOUD86_HOST}:3141/messages?sessionId=TEST" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${LOKI_MCP_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": 3,
    "params": {
      "name": "vault_read",
      "arguments": {"note_path": "System/integration-test.md"}
    }
  }'
```

---

## Phase 10 — Enable consult-second-brain Skill

Add the MCP server to your Claude Code / Klara AI agent config so the `consult-second-brain` skill can call vault tools:

```json
{
  "mcpServers": {
    "loki-vault": {
      "url": "http://<cloud86-host>:3141/mcp",
      "headers": {
        "X-API-Key": "<MCP_API_KEY>"
      }
    }
  }
}
```

---

## Phase 11 — Monitoring Queries

Run these against the loki_vault DB to confirm pipeline health:

```sql
-- Embedding count and coverage
SELECT
  COUNT(*)                               AS total_notes,
  COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS indexed,
  COUNT(*) FILTER (WHERE embedding IS NULL)     AS pending_embed
FROM vault_embeddings;

-- Submission queue health
SELECT status, COUNT(*), MAX(created_at) AS latest
FROM note_submissions
GROUP BY status
ORDER BY status;

-- Failed submissions (investigate these)
SELECT id, LEFT(content, 80) AS preview, error_message, created_at
FROM note_submissions
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT 20;

-- Average search latency baseline (run EXPLAIN ANALYZE)
EXPLAIN ANALYZE
SELECT note_path, 1 - (embedding <=> '[0.1,0.2,...]'::vector) AS sim
FROM vault_embeddings
ORDER BY embedding <=> '[0.1,0.2,...]'::vector
LIMIT 10;

-- Memory index stats
SELECT category, COUNT(*) FROM memory_index GROUP BY category ORDER BY count DESC;
```

---

## Rollback Procedure

```bash
cd /opt/loki-vault

# Stop the stack
docker compose down

# Data is preserved in the pgdata volume.
# To fully reset (DESTRUCTIVE — deletes all embeddings):
docker compose down -v   # removes pgdata volume
```

To roll back to a previous image:
```bash
docker compose down
git checkout <previous-commit>
docker compose build
docker compose up -d
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| vault-mcp container exits immediately | `docker compose logs vault-mcp` — likely a missing env var (DATABASE_URL, OPENAI_API_KEY) |
| Health returns 503 | postgres container not healthy yet; `docker compose ps` to check |
| vault_search returns 0 results | Embeddings not generated yet — check `note_submissions` queue, check OPENAI_API_KEY validity |
| sync.sh fails "git merge failed" | Vault has diverged; log in to Cloud86, `cd /opt/loki-vault/vault && git status` |
| High embedding latency | OpenAI API rate limit — reduce batch size via `WORKER_INTERVAL_MS` or switch to `text-embedding-3-small` |
| SSE connection drops immediately | Check `MCP_API_KEY` match between client and server |

---

## Tuning Notes

- **IVFFlat lists parameter**: Default is 100. Tune to `sqrt(total_rows)` once you have >10k notes for better ANN accuracy.  
  `CREATE INDEX CONCURRENTLY ... WITH (lists = <value>)` — no downtime required.

- **Similarity threshold**: Start at 0.70. Lower to 0.60–0.65 if search is too restrictive; raise to 0.75–0.80 to reduce noise.

- **Worker interval**: Default 10 s. Reduce to 3–5 s for near-real-time indexing if OpenAI rate limits allow.
