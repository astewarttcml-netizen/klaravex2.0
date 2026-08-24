# Vault MCP — US DB repoint (Klaravex2.0)

## Status (2026-08-24)

| Step | Status |
|---|---|
| Code ported to `Klaravex2.0/klara/vault-mcp/` | Done |
| `docker-compose.yml` / `.env.example` point at US tunnel `:15432` | Done |
| Schema `vault` created on `klaravex-db-r2` / db `klaravex` | Done |
| Azure `azure.extensions=VECTOR,PGCRYPTO` on `klaravex-db-r2` | Done |
| Tables `vault.vault_embeddings`, `vault.note_submissions`, `vault.memory_index` | Done |
| Credential wire into `klara/vault-mcp/.env` | Done (gitignored; via `wire-vault-mcp-env.sh`) |
| Live `loki-vault-mcp` container still on EU `psql-klaravexde-prod/loki_vault` | Not cut over (intentional — start Klaravex2.0 compose, verify, then orphan EU) |

## Why schema `vault`

`klaravex.note_submissions` is already the **RARV journal queue** (bigint + `submission_status`).
Vault MCP's `note_submissions` is a **different UUID embedding queue**.
Ownership boundary: RARV → `klaravex.*`; vault-mcp → `vault.*`.

## Azure extensions (resolved 2026-08-24)

Set on `klaravex-db-r2` (rg `klaravex-prod`):
```bash
az postgres flexible-server parameter set \
  --resource-group klaravex-prod \
  --server-name klaravex-db-r2 \
  --name azure.extensions \
  --value "VECTOR,PGCRYPTO"
```
Then `01-schema.sql` applied successfully.

## Credential wire (no secrets in git)

```bash
/home/anthony/Klaravex2.0/scripts/wire-vault-mcp-env.sh
```

Reads `DATABASE_URL` from the live worker `.env`, rewrites host to
`host.docker.internal:15432` for compose, adds `options=-csearch_path=vault`,
writes `klara/vault-mcp/.env` (gitignored). Logs var *names* only.

## Cutover (after tables exist)

1. Wire `.env` via script above.
2. `cd Klaravex2.0/klara/vault-mcp && docker compose up -d --build`
3. Smoke: `curl -s http://127.0.0.1:3141/health` (or MCP tools list).
4. Only then stop / leave orphaned the EU-pointing `loki-vault-mcp` on the
   monolith (ownership transfer — see plan Isolation section).
