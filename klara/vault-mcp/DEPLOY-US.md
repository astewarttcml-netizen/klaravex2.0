# Vault MCP — US (Klaravex2.0)

## Status (2026-08-25)

| Step | Status |
|---|---|
| Code in `Klaravex2.0/klara/vault-mcp/` | Done |
| `DATABASE_URL` → US tunnel `:15432`, schema `vault` | Done |
| Azure `azure.extensions=VECTOR,PGCRYPTO` on `klaravex-db-r2` | Done |
| Tables `vault.vault_embeddings`, `vault.note_submissions`, `vault.memory_index` | Done |
| Credential wire via `scripts/wire-vault-mcp-env.sh` | Done (`.env` gitignored) |
| Legacy monolith `loki-vault-mcp` (was on foreign Azure host) | **Stopped / removed** 2026-08-25 |
| Klaravex2.0 vault-mcp on `:3141` | Start with compose below |

## Why schema `vault`

`klaravex.note_submissions` is the **RARV journal queue** (bigint + `submission_status`).
Vault MCP's `note_submissions` is a **UUID embedding queue**.
Ownership: RARV → `klaravex.*`; vault-mcp → `vault.*`.

## Run

```bash
/home/anthony/Klaravex2.0/scripts/wire-vault-mcp-env.sh   # if .env missing
cd /home/anthony/Klaravex2.0/klara/vault-mcp
docker compose up -d --build
curl -sS http://127.0.0.1:3141/health || true
```

## Verify tables

```sql
SELECT n.nspname, c.relname
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'vault' AND c.relkind = 'r'
ORDER BY 2;
-- expect: memory_index, note_submissions, vault_embeddings
```
