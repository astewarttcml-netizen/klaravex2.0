# T-INF-09 deploy — Tailscale sidecar so klaravex-api reaches the tailnet embedder

**Goal:** let the Azure `klaravex-api` Container App call `nomic-embed-text` on the
USA node's LiteLLM (`100.66.236.56:8001`, Tailscale-only) for query-time embeddings —
**privately, no public ports** (Option A).

**Design:** add a Tailscale sidecar (userspace mode) to the `klaravex-api` Container App.
It joins the tailnet as an ephemeral, tagged node and exposes a local **outbound HTTP
proxy** on `localhost:1055`. The app routes *only* the embedding call through it
(`EMBEDDING_PROXY`), leaving all other outbound traffic (Stripe, Graph, …) direct.

```
klaravex-api replica (shared localhost)
 ├─ main container ── EMBEDDING_PROXY=http://localhost:1055 ─┐
 └─ tailscale sidecar (userspace) ── outbound-http-proxy :1055 ─┘
                        │  Tailscale mesh (private)
                        ▼
        100.66.236.56:8001  (USA LiteLLM → nomic-embed-text, 768-dim)
```

Prereqs already done (staged in repo, not deployed):
- migration `029_notes_semantic_search.sql`
- endpoint `POST /api/v1/internal/notes/search_semantic`
- `EMBEDDING_PROXY` support in `lib/embeddings.py`
- USA node `:8001` verified up on Tailscale and serving `nomic-embed-text`.

---

## Step 1 — (YOU) mint a tagged, ephemeral Tailscale auth key
Tailscale admin console → **Settings → Keys → Generate auth key**:
- **Reusable:** yes · **Ephemeral:** yes · **Tags:** `tag:azure-api`
- Copy the `tskey-auth-…` value → store in 1Password (Claude vault) and as a Container App **secret** `ts-authkey`.

If `tag:azure-api` doesn't exist yet, add it to the tailnet policy (`tagOwners`):
```jsonc
"tagOwners": { "tag:azure-api": ["autogroup:admin"] }
```

## Step 2 — (YOU) tailnet ACL: allow the Azure node → USA embedder only
Add to the tailnet policy `acls` (least-privilege — just the embedder port):
```jsonc
{ "action": "accept", "src": ["tag:azure-api"], "dst": ["100.66.236.56:8001"] }
```

## Step 3 — add the sidecar + env to the Container App
Export current spec, merge the fragments below, re-apply. (Portal works too:
Containers → add container; Application settings → add env + secrets.)

```bash
az containerapp show -g klaravex-prod -n klaravex-api -o yaml > klaravex-api.yaml
# ... merge the two fragments below into klaravex-api.yaml ...
az containerapp update -g klaravex-prod -n klaravex-api --yaml klaravex-api.yaml
```

**Secrets** (add under `properties.configuration.secrets`):
```yaml
- name: ts-authkey        # the tskey-auth-… from Step 1
  value: <PASTE>
- name: embedding-api-key # LiteLLM master key (1P: 66pfgqzljgxsw6yjox72el2y4a)
  value: <PASTE>
```

**Sidecar container** (add under `properties.template.containers`):
```yaml
- name: tailscale
  image: tailscale/tailscale:stable
  resources: { cpu: 0.25, memory: 0.5Gi }
  env:
    - name: TS_AUTHKEY
      secretRef: ts-authkey
    - name: TS_USERSPACE
      value: "true"
    - name: TS_HOSTNAME
      value: "klaravex-api"
    - name: TS_EXTRA_ARGS
      value: "--advertise-tags=tag:azure-api"
    - name: TS_OUTBOUND_HTTP_PROXY_LISTEN
      value: "0.0.0.0:1055"
    - name: TS_STATE_DIR
      value: "/tmp/tailscale"        # ephemeral node; no persistent volume needed
```

**Main container** — add env (under its `env:`):
```yaml
- name: EMBEDDING_BASE_URL
  value: "http://100.66.236.56:8001/v1"
- name: EMBEDDING_MODEL
  value: "nomic-embed-text"
- name: EMBEDDING_PROXY
  value: "http://localhost:1055"
- name: EMBEDDING_API_KEY
  secretRef: embedding-api-key
```

## Step 4 — apply the DB migration + backfill (from the rig)
```bash
# migration (Azure klaravex-db)
psql "$AZURE_KLARAVEX_DSN" -f infra/migrations/029_notes_semantic_search.sql
# backfill 8172 rows via local nomic (free); run on the rig where :8000 is local
DATABASE_URL="$AZURE_KLARAVEX_DSN" EMBEDDING_API_KEY="$LITELLM_MASTER_KEY" \
  python3 infra/scripts/backfill_note_embeddings.py --batch 100
```

## Step 5 — verify
```bash
# a) sidecar joined the tailnet (should appear as klaravex-api, tag:azure-api)
tailscale status | grep klaravex-api
# b) endpoint returns ranked hits (internal-secret gated)
curl -s https://api.klaravex.com/api/v1/internal/notes/search_semantic \
  -H "x-loki-internal-secret: $LOKI_INTERNAL_SECRET" -H 'content-type: application/json' \
  -d '{"query":"azure postgres connection errors","k":5}' | jq '.results[] | {score,title}'
```
Expected: top hits are the DB/infra notes (validated locally on ephemeral pgvector).

## Rollback
- Remove the `tailscale` sidecar container + the 4 embedding env vars from the app.
- The `klaravex-api` node auto-deregisters (ephemeral). Delete the auth key.
- Migration 029 is additive (nullable column + partial index) — safe to leave, or
  `ALTER TABLE klaravex.note_submissions DROP COLUMN embedding, DROP COLUMN embedding_model, DROP COLUMN embedded_at;`

## Security notes
- No public port opened; the embedder stays Tailscale-only. ACL restricts the Azure
  node to just `100.66.236.56:8001`.
- Ephemeral node = auto-cleanup on replica recycle; reusable key so scale-out works.
- `EMBEDDING_PROXY` scopes the proxy to the embedding call only — Stripe/Graph/etc.
  keep going out directly.
