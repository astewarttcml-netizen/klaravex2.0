# Vault MCP — EU (Klaravex DE)

## Status (2026-08-29)

| Step | Status |
|---|---|
| Code | Reuse this repo verbatim — no EU fork |
| EU host | `gateway.klaravex.de` / `162.55.163.242` (Hetzner, EU) — **never the US host** |
| EU Postgres | `psql-klaravexde-prod` (Azure, EU region), schema `vault` |
| Public route | `https://api.klaravex.de/vault/mcp` → container `:3141` `/mcp` |
| Console client | `klaravex-os` eu tenant → `TENANT_EU_BRAIN_PROVIDER=loki-mcp` (done, `.env.eu.local`) |
| Server deployment | **Not started** — route currently 404s |

## Legal boundary (binding, per counsel 2026-08-25)

- This instance runs on EU infrastructure only. Do **not** `docker compose up`
  on `anthony-Klaravex` (US host) — see
  `klaravex/infra/docker-services/EU-STACK-DECOMMISSIONED.md`.
- EU vault data lives in `psql-klaravexde-prod`, schema `vault`. No
  replication, backup, or embedding pipeline may target US infrastructure.
- The US console (`klaravex-os`) calls this endpoint over HTTPS only, with a
  **read-only** key. No EU memory is written from US systems; EU note capture
  happens inside the EU stack.

## Architecture

```
klaravex-os (US console, eu tenant requests only)
  │  POST https://api.klaravex.de/vault/mcp   Bearer TENANT_EU_LOKI_VAULT_KEY (read-only)
  ▼
gateway.klaravex.de (Caddy/nginx on 162.55.163.242)
  │  location /vault/ → strip prefix → 127.0.0.1:3141
  ▼
klara-vault-mcp-eu container (this repo, docker-compose.yml)
  │  tools: vault_search · vault_read · vault_submit_note
  ▼
psql-klaravexde-prod / schema vault (pgvector)
  tables: vault_embeddings · note_submissions · memory_index
```

## Deploy (on the EU host)

```bash
git clone <repo> /opt/klara-vault-mcp-eu && cd /opt/klara-vault-mcp-eu
# .env — EU values only
cat > .env <<'EOF'
DATABASE_URL=postgres://klaravex:<pw>@psql-klaravexde-prod.postgres.database.azure.com/klaravex_de?sslmode=require
VAULT_PORT=3141
VAULT_API_KEY=<rw-key-uuid>          # EU stack internal writes
VAULT_API_KEY_READ_ONLY=<ro-key-uuid> # → TENANT_EU_LOKI_VAULT_KEY in klaravex-os .env.eu.local
OLLAMA_HOST=<eu-embeddings-endpoint>  # or OpenAI key held on EU host
EOF
docker compose up -d --build
curl -sS http://127.0.0.1:3141/health
```

Schema bootstrap: `01-schema.sql` + `02-permissions.sql` against the EU DB
(same as US — tables land in schema `vault`, no collision with the RARV
`klaravex.note_submissions` queue).

## Gateway routing

```
# Caddy example on gateway.klaravex.de
api.klaravex.de {
  handle_path /vault/* {
    reverse_proxy 127.0.0.1:3141
  }
  # existing loki-agents routes unchanged
}
```

`/vault/mcp` → `:3141/mcp` (Streamable HTTP: POST for JSON-RPC, GET for SSE
stream, DELETE for session close — all three must proxy; the `mcp-session-id`
header must pass through).

## Contract the console client relies on

- `initialize` → standard MCP handshake (`protocolVersion 2025-03-26`).
- `tools/call vault_search { query, limit }` → text block containing JSON
  `{ results: [{ notePath, noteTitle, content, similarity }], total }`.
- Auth: `Authorization: Bearer <key>`; read-only key must reject
  `vault_submit_note` (already enforced by `readOnly` in
  `src/mcp-server-part3.ts`).
- Failure semantics: any non-200 / unreachable → console falls back to the
  eu tenant's local markdown store (`~/.claude/knowledge/eu-vault`); the UI
  shows "local fallback active", never an error page.

## Verify (from the US host, after deploy)

```bash
KEY=<ro-key-uuid>
curl -s https://api.klaravex.de/vault/mcp \
  -H "authorization: Bearer $KEY" -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
# expect: result.serverInfo.name = "loki-vault"

# read-only enforcement
curl -s https://api.klaravex.de/vault/mcp -H "authorization: Bearer $KEY" ... \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"vault_submit_note","arguments":{"content":"x"}}}'
# expect: "not permitted for this API key (read-only access)"
```

Then in `klaravex-os`: Brain page on an eu-host request shows provider
`loki-vault`, `connected: true`.

## Open items

- [ ] Generate rw + ro API keys; store ro key in 1Password `Klaravex Ad Tokens`
      (or new `Klaravex DE Vault` item) and `.env.eu.local`.
- [ ] Confirm EU embeddings path (Ollama on EU host vs OpenAI) — embeddings
      leave the vault, so the provider must be counsel-cleared for EU data.
- [ ] Backfill: `bulk-index.py` against the EU vault git repo (EU host only).
- [ ] Decide session affinity: MCP sessions are in-memory per container —
      pin to one replica.
