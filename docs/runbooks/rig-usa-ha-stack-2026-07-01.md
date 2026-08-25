# Klaravex Rig + Hetzner USA HA Stack

**Deployed:** 2026-07-01 → 2026-07-02
**Owner:** Anthony Stewart
**Architect:** Loki (this session)
**Location doc:** `runbooks/rig-usa-ha-stack-2026-07-01.md`

Complete US-only 2-node **active-passive** architecture (formalized 2026-08-08 per Anthony directive — previously labeled "active-active"). Rig = primary-of-record for everything stateful/scheduled; USA VM = edge + hot standby with ALL services still running (see §1.1). Replaces Fujitsu bare-metal + Hetzner-DE Loki backend. No EU deploys per Anthony directive 2026-07-01.

---

## 1. Architecture at a glance

```
                Public internet (api.klaravex.com etc.)
                              │
                              ▼
                ┌──────────────────────────┐
                │  AZURE US-East             │
                │  • klaravex-api Container  │  (customer facing, unchanged)
                │  • klaravex-db Postgres    │  (unchanged, separate DB)
                └──────────────────────────┘

    ┌───────────────────────────────────────────────────────┐
    │                    Tailscale mesh                      │
    │                                                        │
    │   ┌─────────────────┐         ┌────────────────────┐   │
    │   │ Home rig        │         │ Hetzner USA VM     │   │
    │   │ anthony-klaravex│◄───────►│ hetzner-usa-       │   │
    │   │ 100.75.10.114   │         │  watchdog          │   │
    │   │                 │         │ 100.66.236.56      │   │
    │   │ AMD Ryzen 9 9900X│         │ ubuntu-16gb-ash-1  │   │
    │   │ 89 GB DDR5      │         │ 15 GB RAM / 150 GB │   │
    │   │ 2× RTX 3090     │         │ (no GPU)           │   │
    │   │ Ubuntu 26.04    │         │ Ubuntu 26.04       │   │
    │   └────────┬────────┘         └────────┬───────────┘   │
    │            │                            │               │
    └────────────┼────────────────────────────┼──────────────┘
                 │                            │
                 ▼                            ▼
              SSH / mosh                Public internet edge
              from Mac                  (SSH port 22 only,
              (thin gateway)             fail2ban-guarded)
```

**Design principles:**
- Mac = thin gateway only (SSH terminal + browser + 1P). No processing.
- Rig = primary compute (GPU inference, Loki backend, workers, WebUI).
- USA VM = HA edge (Postgres standby, second Vault/LiteLLM/Worker instance, HAProxy edge, watchdog, backup target).
- All service traffic on Tailscale — zero public ports on rig, public SSH only on USA.
- Azure (klaravex-api + klaravex-db) untouched.

### 1.1 Operating mode — active-passive (formalized 2026-08-08)

- **Rig = primary-of-record** for every stateful or scheduled role: api + worker + Celery beat, Redis, Postgres writer, GPU inference, WebUI. Since 2026-08-08 the app stack is the consolidated `infra/docker-services/` stack (`klaravex-api`, `klaravex-worker`, `klaravex-redis`) with code volume-mounted from the repo — restart-to-deploy, no image rebuilds for code changes. The legacy `infra/docker-compose.klaravex.yml` stack is RETIRED — never `up` it (its no-password Redis squats :6379 and crash-loops the workers; caused the 2026-08-08 outage).
- **USA VM stays fully RUNNING** — "passive" does not mean off: HAProxy edge (front door for pg/vault/LiteLLM), pgaf-monitor (failure detector — must live off the primary node), pgaf-standby (streaming replica), loki-watchdog-azure timer, public SSH ingress, and the second `litellm-usa` / `loki-vault-mcp-usa` / `klaravex-worker-usa` instances as hot standbys (zero-startup failover).
- **Single-writer rules:** exactly one Postgres primary (pg_auto_failover enforces) and exactly one Celery `--beat` scheduler (rig worker only — the USA worker must never carry `--beat`; duplicate beat = duplicate scheduled tasks = duplicate cold emails).
- **Failover direction: rig → USA only.** DB failover is automatic (monitor promotes standby, HAProxy re-elects in ~10s). App failover is manual (§15.5).
- The HAProxy round-robin frontends (`vault_mcp_fe`, `litellm_fe`) are capacity sharing between stateless second instances, not co-primacy — all state lives behind the single-writer DB + rig Redis + rig beat.

---

## 2. Hosts

### 2.1 Home rig (`anthony-klaravex`)

| | |
|---|---|
| Hostname | `anthony-Klaravex` |
| Tailscale IP | `100.75.10.114` |
| MagicDNS | `anthony-klaravex.tailbe73cd.ts.net` |
| LAN IP | `192.168.1.189` |
| Public IP | none (behind home NAT) |
| OS | Ubuntu 26.04 LTS (kernel 7.0.0-27) |
| CPU | AMD Ryzen 9 9900X (12c/24t) |
| RAM | 89 GB DDR5 |
| Storage | 1.8 TB NVMe (Samsung PM9E1) |
| GPU | 2× NVIDIA RTX 3090, 24 GB VRAM each (48 GB total), driver 595.71.05, CUDA 13.2 |
| SSH access | `ssh rig` (Mac alias) → `anthony@100.75.10.114` pubkey ed25519 |
| Sudo | password required (14 chars, 1P `l3u3fvuh45iwwvv6e2elsomr7q`) |
| 1P item | Claude vault — `Klaravex AI— bare-metal Ubuntu 26.04 (Anthony@192.168.1.231)` (title still shows old IP; actual is .189) |

### 2.2 Hetzner USA VM (`hetzner-usa-watchdog`)

| | |
|---|---|
| Hostname | `ubuntu-16gb-ash-1` |
| Tailscale IP | `100.66.236.56` |
| Public IP | `87.99.147.244` |
| OS | Ubuntu 26.04 LTS |
| CPU / RAM | 4 vCPU / 15 GB |
| Storage | 150 GB (2 GB used) |
| GPU | none |
| SSH access | Tailscale SSH (`tailscale ssh root@hetzner-usa-watchdog`) OR public root+pw |
| 1P item | Klaravex vault — `Hetzner — USA (root@87.99.147.244)` — `52bk74s7stijglpdsnmz3u2q5u` |

### 2.3 Mac (gateway only)

- Tailscale IP: `100.95.80.4`
- Role: SSH client + browser + 1P CLI + rsync bastion
- No persistent processes (Ollama/LiteLLM/Postgres etc. all live on rig)

---

## 3. Network + security

### 3.1 Tailscale mesh

Peers on Anthony's tailnet (`astewart.tcml@`):

| Node | Tailscale IP | Purpose |
|---|---|---|
| `anthony-klaravex` | 100.75.10.114 | rig (primary compute) |
| `hetzner-usa-watchdog` | 100.66.236.56 | USA edge + HA standby |
| `anthonys-macbook-pro` | 100.95.80.4 | Mac gateway |
| `hetzner-cx22` | 100.78.231.58 | EU Loki backend (retained read-only; no new deploys) |
| `anthony-primergy-tx1310-m3` | 100.114.136.101 | Fujitsu (decommissioned; still in tailnet) |

MagicDNS enabled — hostnames resolve automatically from any peer.

### 3.2 Rig firewall (ufw)

- Default: deny incoming, allow outgoing
- Allow SSH port 22 from `192.168.1.0/24` (LAN only, pubkey auth only)
- Allow everything on `tailscale0` iface (Tailscale traffic)
- Allow everything on `lo`
- Allow docker bridge: `from 172.16.0.0/12` + `in on docker0` (needed for container→host services)
- Per-service LAN allows on ports 3000 (Open WebUI), 4000 (NoMachine), 5353/udp (mDNS), 6379 (Redis), 8000 (LiteLLM), 11434 (Ollama), 3141 (vault-mcp)
- fail2ban sshd jail active (`maxretry=3, findtime=10m, bantime=1h`)
- SSH pubkey-only (`PasswordAuthentication no`, key at `~/.ssh/id_ed25519` on Mac)

### 3.3 USA VM firewall (ufw)

- Default: deny incoming, allow outgoing
- Allow SSH port 22 public (fail2ban guards it)
- Allow everything on `tailscale0`
- Allow everything on `lo`
- Allow docker bridge same as rig
- fail2ban sshd jail active

### 3.4 Public exposure surface

- **Rig:** ZERO public ports (behind home NAT; no port forwarding).
- **USA VM public:** SSH port 22 only (fail2ban-guarded, pubkey-preferred).
- Everything else (Postgres, LiteLLM, vault-mcp, Redis, HAProxy) tailnet-only.

---

## 4. Component inventory

### 4.1 Rig (6 containers)

| Container | Image | Port (host bind) | Role |
|---|---|---|---|
| `pgaf-primary` | `pgvector-af:pg17` | 100.75.10.114:5434 | pg_auto_failover managed Postgres (currently PRIMARY) |
| `loki-vault-mcp` | `loki-vault-mcp:latest` | anywhere:3141 | Vault MCP server, connects to primary via HAProxy TCP frontend |
| `litellm` | `ghcr.io/berriai/litellm:main-stable` | anywhere:8000 | LLM proxy + admin UI |
| `klaravex-worker` | `klaravex:latest` | (none — worker only) | Celery worker; consumes rig Redis; klaravex-api tasks |
| `klaravex-redis` | `redis:7-alpine` | anywhere:6379 | Celery broker + cache |
| `open-webui` | `ghcr.io/open-webui/open-webui:main` | anywhere:3000 | ChatGPT-style GUI over LiteLLM proxy |

Bare-metal on rig (not containerised):
- **Ollama 0.31.1** systemd service, binds `0.0.0.0:11434` — both 3090s auto-detected
- **NoMachine 9.7.3** systemd — remote desktop port 4000 (LAN + Tailscale only)

### 4.2 USA VM (6 containers)

| Container | Image | Port | Role |
|---|---|---|---|
| `pgaf-standby` | `pgvector-af:pg17` | 100.66.236.56:5434 | pg_auto_failover Postgres (SECONDARY, streaming replica) |
| `pgaf-monitor` | `pgvector-af:pg17` | 100.66.236.56:5433 | pg_auto_failover coordinator |
| `loki-vault-mcp-usa` | `loki-vault-mcp:latest` | anywhere:3141 | Vault MCP server (active-active) |
| `litellm-usa` | `ghcr.io/berriai/litellm:main-stable` | anywhere:8000 | LiteLLM proxy (active-active) |
| `klaravex-worker-usa` | `klaravex:latest` | (none) | Celery worker (consumes rig Redis via Tailscale) |
| `klaravex-haproxy` | `haproxy-pg:2.9` (custom, includes psql) | host network | Edge LB + pg-primary TCP frontend |

Bare-metal on USA:
- **Tailscale 1.98.8** — tailnet client + Tailscale SSH
- **loki-watchdog-azure** systemd timer (T-INF-11 escalation to Anthony via Vapi)

---

## 5. pg_auto_failover cluster (Phase 6)

### 5.1 Custom image `pgvector-af:pg17`

Built from `pgvector/pgvector:pg17` (Debian bookworm base) + PGDG apt repo + `postgresql-17-auto-failover` + `pg-auto-failover-cli`. Compatible with pg_autoctl 2.2.

Dockerfile lives at `/tmp/pgvector-af-build/Dockerfile` on rig (also on USA). Ubuntu 26.04 host uses libicu76 which is incompatible with PGDG PG 17 packages — hence custom Docker image on top of Debian bookworm's libicu74.

### 5.2 Cluster topology

| Role | Node | Container | Tailnet host:port |
|---|---|---|---|
| Monitor | USA VM | `pgaf-monitor` | 100.66.236.56:5433 |
| Node 527 | Rig | `pgaf-primary` | 100.75.10.114:5434 |
| Node 528 | USA VM | `pgaf-standby` | 100.66.236.56:5434 |

⚠️ **Role drift (verified 2026-08-08):** the cluster was re-initialized after this doc was first written (node IDs are 527/528, not 281/279), and the **current read-write primary is node_528 on the USA VM** — the rig node is the streaming secondary. Roles flipped during earlier failover testing and never switched back. Container names (`pgaf-primary` / `pgaf-standby`) describe *intended* roles, not current ones. Under active-passive the writer belongs on the rig — planned switchover (§15.1) is pending Anthony's go.

State command:
```bash
tailscale ssh root@hetzner-usa-watchdog 'docker exec pgaf-monitor pg_autoctl show state --pgdata /var/lib/postgresql/data'
```

Databases restored from 169 KB `pg_dumpall` of the retired `loki-postgres` container:
- `loki_vault` (vault-mcp storage, vault_embeddings pgvector)
- `litellm` (LiteLLM proxy admin DB)
- Roles: `postgres`, `replicator`, `vault_sync_service`

### 5.3 Config specifics

- `--pgdata=/pgaf/data` (NOT `/var/lib/postgresql/data`) — pg_autoctl needs to remove/recreate the pgdata dir during pg_basebackup fallback, and Docker volumes mounted directly at pgdata prevent that. Volume mounts at parent `/pgaf/` and pg_autoctl owns `/pgaf/data`.
- `init-perms` init container chowns `/pgaf` to postgres:postgres before pg_autoctl runs.
- `--auth=trust` — internal cluster; hardening later if needed
- `--ssl-self-signed` — self-signed cert auto-generated by pg_autoctl for internal replication
- `--hostname=<tailnet_ip>` (NOT MagicDNS — pg_autoctl needs a hostname that resolves inside the container to a local interface; MagicDNS not present inside container)
- `network_mode: host` for all three pgaf containers (so tailnet IP is a local interface)

### 5.4 pg_hba entries (both nodes)

Auto-generated by pg_autoctl for replication + monitor traffic (over TLS, trust auth), plus hand-added for app clients:

```
# Trust for app clients from tailnet, LAN, and any Docker bridge subnet
host all vault_sync_service 100.64.0.0/10 trust
host all vault_sync_service 172.16.0.0/12 trust
host all vault_sync_service 192.168.1.0/24 trust
host all postgres 100.64.0.0/10 trust
host all postgres 172.16.0.0/12 trust
host all postgres 192.168.1.0/24 trust
```

### 5.5 Manual failover

```bash
# Perform planned switchover (fenced, ordered):
tailscale ssh root@hetzner-usa-watchdog \
  'docker exec pgaf-monitor pg_autoctl perform switchover \
     --formation default --pgdata /var/lib/postgresql/data'

# Force failover on primary-down (unplanned):
tailscale ssh root@hetzner-usa-watchdog \
  'docker exec pgaf-monitor pg_autoctl perform failover \
     --formation default --pgdata /var/lib/postgresql/data'
```

Timeline advances on every failover; the demoted node runs pg_rewind (or full pg_basebackup fallback) automatically to catch up.

---

## 6. HAProxy edge (Phase 5 + 6)

Runs on USA VM in `network_mode: host`, binds to `100.66.236.56` (Tailscale iface only).

### 6.1 Frontends

| Frontend | Bind | Mode | Backend | Balance |
|---|---|---|---|---|
| `vault_mcp_fe` | 100.66.236.56:3142 | http | rig+USA vault-mcp on 3141 | round-robin |
| `litellm_fe` | 100.66.236.56:8001 | http | rig+USA LiteLLM on 8000 | round-robin |
| `pg_primary` | 100.66.236.56:**5432** | tcp | pgaf-primary OR pgaf-standby on 5434 (whichever is primary) | external-check |
| stats | 100.66.236.56:8404 | http | HAProxy stats UI | n/a |

### 6.2 pg_primary auto-election

Custom `haproxy-pg:2.9` image (Alpine base + `postgresql17-client`). External check script at `/etc/haproxy/check-primary.sh`:

```bash
#!/bin/bash
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/lib/postgresql/17/bin
srv="$3"
port="$4"
res=$(PGCONNECT_TIMEOUT=3 /usr/bin/psql -h "$srv" -p "$port" -U postgres -d postgres \
        --set=sslmode=disable -tAc "SELECT NOT pg_is_in_recovery();" 2>>/tmp/pgcheck.err)
[[ "$res" == "t" ]] && exit 0 || exit 1
```

Only the current primary returns `t` (NOT pg_is_in_recovery). HAProxy marks the other node DOWN, all TCP traffic to `100.66.236.56:5432` is proxied to the primary. On failover, HAProxy re-elects within `inter 5s * fall 2 = 10s` cycle.

### 6.3 Apps use HAProxy pg-primary endpoint

All 4 app DATABASE_URLs point at `100.66.236.56:5432` (HAProxy TCP frontend). They auto-follow the primary without config change.

---

## 7. Ollama + LiteLLM + models

### 7.1 Ollama bare-metal (rig only)

Listens on `0.0.0.0:11434`. `OLLAMA_KEEP_ALIVE=15m`. Systemd unit at `/etc/systemd/system/ollama.service.d/override.conf`.

Both 3090s auto-detected (`CUDA0` + `CUDA1`, 23.6 GiB each). qwen2.5:72b tensor-splits across both cards.

**Pulled models (~97 GB total):**
- `nomic-embed-text` (274 MB) — embeddings for vault-mcp
- `qwen2.5:32b` (19 GB) — general chat
- `qwen2.5-coder:32b` (19 GB) — coding
- `deepseek-r1:32b` (19 GB) — reasoning
- `qwen2.5:72b` (~40 GB) — high-quality chat, tensor-parallel

### 7.2 LiteLLM proxy config

`/opt/klaravex/litellm/config.yaml` on both rig + USA. Model aliases match the pre-existing Fujitsu setup (per CLAUDE.md constraint #9):

| Alias | Route | Purpose |
|---|---|---|
| `qwen-72b` | ollama_chat/qwen2.5:72b (local) | **DEFAULT** chat |
| `deepseek` | ollama_chat/deepseek-r1:32b (local) | reasoning |
| `qwen-coder` | ollama_chat/qwen2.5-coder:32b (local) | coding |
| `qwen-coder-32b` | same as `qwen-coder` | explicit 32b name |
| `claude-sonnet` | openrouter/anthropic/claude-sonnet-4-6 | cloud fallback |
| `claude-opus` | openrouter/anthropic/claude-opus-4-7 | cloud premium |
| `gpt-4o` | openrouter/openai/gpt-4o | cloud OpenAI |
| `gpt-5` | openrouter/openai/gpt-5 | cloud OpenAI premium |
| `gemini-flash` | openrouter/google/gemini-2.5-flash | cloud Google |
| `nomic-embed-text` | ollama/nomic-embed-text | embeddings |
| `smart` | 3 deployments: local qwen-72b + OpenRouter Claude Sonnet + OpenRouter DeepSeek V3.1, `routing_strategy: latency-based-routing` | auto-picks fastest available |

**Fallback chain (auto-escalate on failure):**
- `qwen-72b` → `deepseek` → `claude-sonnet`
- `deepseek` → `qwen-72b` → `claude-sonnet`
- `qwen-coder` → `qwen-coder-32b` → `claude-sonnet`
- `claude-sonnet` → `gpt-4o` → `gemini-flash`
- `gpt-4o` → `claude-sonnet` → `gemini-flash`

`num_retries=2`, `allowed_fails=3`, `cooldown_time=60s`.

### 7.3 LiteLLM admin UI

- URL: `http://anthony-klaravex:8000/ui` (rig direct) or `http://hetzner-usa-watchdog:8001/ui` (HA)
- Credentials: `admin` / `122f99ce9c99dafcfbe8047c` (in-band; rotate + move to 1P before production)
- Backed by pg_auto_failover's `litellm` database (Prisma migrations on startup)

### 7.4 Open WebUI

- URL: `http://anthony-klaravex:3000` (Tailscale or LAN)
- First visitor becomes admin (signup then disabled)
- Two pre-configured connections:
  - Ollama direct: `http://host.docker.internal:11434` (5 raw models)
  - OpenAI-compatible → LiteLLM: `http://host.docker.internal:8000/v1` (all 11 aliases including OpenRouter)
- Default model: `qwen-72b`
- Local SentenceTransformer embedding model downloaded on first boot (~90 MB, cached in `open-webui-data` volume)

---

## 8. Vault-mcp (Loki SecondBrain)

Two instances, both connect to pg_auto_failover primary via HAProxy:

- Source: `/opt/klaravex/loki-vault-mcp/` (both nodes) — rsync'd from hetzner-cx22 `/root/loki-vault-mcp/`
- Custom-built image `loki-vault-mcp:latest`
- Listens on `:3141`, X-API-Key auth
- Uses Ollama for embeddings: `OLLAMA_HOST=http://host.docker.internal:11434` (rig) or `http://100.75.10.114:11434` (USA, via Tailscale)
- Model: `nomic-embed-text` (768 dims)
- Vector similarity threshold: 0.70, search limit: 10

Health probe (no auth needed): `curl http://ANY_HOST:3141/health`

MCP endpoint: `http://ANY_HOST:3141/mcp` (Streamable HTTP, X-API-Key required)

---

## 9. Celery workers (Phase 4b)

Both nodes run the `klaravex:latest` image (transferred via `docker save` from hetzner-cx22). Same env file, differ only on Redis URL.

- Rig: `celery -A app.tasks.celery_klaravex worker --pool=solo -Q klaravex,default,approvals --beat --schedule=/tmp/celerybeat-schedule`
- USA: `celery -A app.tasks.celery_klaravex worker --concurrency=4 -Q klaravex,default,approvals,usa-only --hostname=celery-usa@%h`
- Redis broker: `redis://:PASSWORD@host.docker.internal:6379/0` (rig) or `redis://:PASSWORD@100.75.10.114:6379/0` (USA over Tailscale)
- CELERY_BROKER_URL uses DB 1, CELERY_RESULT_BACKEND uses DB 2

Both workers consume from the same queue on the rig Redis. `celery inspect ping` shows both `celery@<hostname>` and `celery-usa@<hostname>`.

**Scheduler (2026-08-18):** the canonical Celery app is `celery_klaravex` (app name `klaravex_agents`); `celery_app` (app name `loki_agents`) was retired as the scheduler. Both workers run `-A app.tasks.celery_klaravex`. The USA worker's queue list includes `usa-only` and it runs `--hostname=celery-usa@%h`.

**Beat rule (2026-08-08):** the rig worker runs `--beat` (`celery -A app.tasks.celery_klaravex worker --pool=solo -Q klaravex,default,approvals --beat --schedule=/tmp/celerybeat-schedule`) and is the ONLY scheduler in the fleet. The USA worker is a hot-standby consumer and must NOT carry `--beat`. Two beats = every cron task fires twice (duplicate Smartlead sends, duplicate SEO posts).

---

## 10. Redis (Phase 4a)

Rig only. Not replicated to USA yet (single Redis = broker SPOF; upgrade to Sentinel + 3 nodes in a later phase).

- `klaravex-redis` container (`redis:7-alpine`)
- `redis-server --requirepass ... --appendonly yes --maxmemory 2gb --maxmemory-policy allkeys-lru`
- Bind `0.0.0.0:6379`, ufw allows LAN + Tailscale
- Password 64 hex chars, in `/opt/klaravex/redis/.env` (mode 600), also inspectable via `docker inspect klaravex-redis`

---

## 11. Watchdog (T-INF-11)

Deployed on USA VM in prior session — not touched tonight. Details in `.loki/audits/T-INF-11-artifact-spec-gap-2026-06-30.md`.

- systemd timer `loki-watchdog-azure.timer` (5-min cadence)
- Probes `https://api.klaravex.com/health`
- On failure: escalates via `POST /api/v1/vapi/escalate_to_anthony` (dual-secret hardening path)
- Config: `/etc/loki-watchdog-azure.env`

---

## 12. Credentials + 1Password map

All secrets in 1Password. **NEVER echo pw into ssh command strings** (leaks via `ps` output — hit this earlier tonight on rig; rotate the rig password soon).

| Item title | Vault | ID | Used for |
|---|---|---|---|
| Klaravex AI— bare-metal Ubuntu 26.04 | Claude | `l3u3fvuh45iwwvv6e2elsomr7q` | rig SSH + sudo |
| Hetzner — USA (root@87.99.147.244) | Klaravex | `52bk74s7stijglpdsnmz3u2q5u` | USA VM SSH |
| LiteLLM Master Key — Fujitsu | Claude | `66pfgqzljgxsw6yjox72el2y4a` | LiteLLM API key |
| OpenRouter API Key — Klarave | Claude | `tb5ihjdxzgu3al5a4nyf7mbeqe` | OpenRouter proxy (stored in **`username` field**, not password — data-hygiene todo) |
| Klaravex API — LOKI_INTERNAL_SECRET | Klaravex | `7x5i2l34oa3a5swanzmrmx5ryy` | /api/v1/escalate auth |
| Klaravex API — WATCHDOG_ESCALATION_SECRET | Klaravex | `gsr7mte5npkiitwbooihmi3ecq` | Vapi watchdog secret (in **`credential` field** — likewise, not password) |
| Loki Postgres — replicator user (rig primary) | Klaravex | `5ucy6mtyjtbhp6vjicfx3rlfh4` | pg_auto_failover replication user (created earlier this session; obsolete now — auto-managed pw) |

Application-level secrets (Postgres passwords, MCP API keys, LiteLLM UI creds) currently live in `.env` files on the target host under `chmod 600`. Rotate + move to 1P before prod use.

---

## 13. Endpoints cheat sheet

**Tailnet-only (no public):**

```
Open WebUI                 http://anthony-klaravex:3000
LiteLLM (rig)              http://anthony-klaravex:8000
LiteLLM admin UI           http://anthony-klaravex:8000/ui        (admin / 122f99ce9c99dafcfbe8047c)
LiteLLM (HA balanced)      http://hetzner-usa-watchdog:8001
vault-mcp (rig)            http://anthony-klaravex:3141           (X-API-Key required)
vault-mcp (HA balanced)    http://hetzner-usa-watchdog:3142
HAProxy stats              http://hetzner-usa-watchdog:8404
Ollama (raw)               http://anthony-klaravex:11434
Postgres primary (auto-flip) 100.66.236.56:5432
pg_auto_failover monitor   100.66.236.56:5433
NoMachine (LAN + Tailscale) anthony-klaravex:4000
Redis                      100.75.10.114:6379                    (password-gated)
```

**Public (USA VM only):**
```
SSH                        ssh root@87.99.147.244    # fail2ban-guarded
```

Mac-side SSH alias — `ssh rig` uses `100.75.10.114` via Tailscale, pubkey `~/.ssh/id_ed25519`.

---

## 14. Common ops

### 14.1 Check cluster state

```bash
# Postgres HA state
tailscale ssh root@hetzner-usa-watchdog \
  'docker exec pgaf-monitor pg_autoctl show state --pgdata /var/lib/postgresql/data'

# HAProxy backend health
curl -sS http://hetzner-usa-watchdog:8404/\;csv | column -t -s,
```

### 14.2 Restart a service

```bash
# Rig:
ssh rig 'sudo docker compose -f /opt/klaravex/<component>/docker-compose.yml restart'

# USA VM:
tailscale ssh root@hetzner-usa-watchdog \
  'docker compose -f /opt/klaravex/<component>/docker-compose.yml restart'
```

### 14.3 Update LiteLLM model config

Edit `/opt/klaravex/litellm/config.yaml` on rig AND USA (they need to match; USA points ollama at `100.75.10.114:11434` instead of `host.docker.internal:11434`). Then `docker compose up -d --force-recreate` on both.

### 14.4 Add a model to Ollama

```bash
ssh rig 'ollama pull <model-name>'
```

Then add a `model_name` block to LiteLLM `config.yaml` pointing at `ollama_chat/<model-name>`. Reload LiteLLM.

### 14.5 Rotate rig password

**Should be done — was exposed in ps output earlier tonight during a wrong-quoting bash mistake.**

```bash
ssh rig 'sudo passwd anthony'                    # interactive
# Then update 1P item l3u3fvuh45iwwvv6e2elsomr7q with new password
```

---

## 15. Failover procedures

### 15.1 Planned switchover (both nodes healthy)

```bash
tailscale ssh root@hetzner-usa-watchdog \
  'docker exec pgaf-monitor pg_autoctl perform switchover --formation default --pgdata /var/lib/postgresql/data'
```

Takes ~15-20s. Apps auto-follow via HAProxy pg-primary endpoint. No manual config edits.

### 15.2 Unplanned failover (primary down)

pg_auto_failover monitor detects primary unreachable after ~30s. Auto-promotes secondary. HAProxy re-elects within 10s of promotion.

Manual trigger if the monitor is slow:
```bash
tailscale ssh root@hetzner-usa-watchdog \
  'docker exec pgaf-monitor pg_autoctl perform failover --formation default --pgdata /var/lib/postgresql/data'
```

### 15.3 Recovering the old primary as secondary

pg_auto_failover attempts pg_rewind automatically when the old primary comes back. If pg_rewind fails (state file corruption etc.), it falls back to full pg_basebackup from the current primary. Both are automatic.

### 15.4 Verify apps auto-followed

```bash
curl -sS http://hetzner-usa-watchdog:8404/\;csv | awk -F, '$1 == "pg_primary" { print $1, $2, $18 }'
# rig UP + usa DOWN  = rig is current primary, all app traffic routes there
# rig DOWN + usa UP  = usa is current primary, all app traffic routes there
```

### 15.5 App-layer failover (rig down → USA serves)

DB failover is automatic (§15.2); the app layer is not. Manual procedure:

1. Confirm DB primary flipped: HAProxy `pg_primary` shows usa UP (§15.4).
2. **Redis** — rig Redis is a SPOF (§10). Start a fresh Redis on USA (or promote `redis-replica` if present). Queued-but-unprocessed Celery tasks are lost; scheduled tasks re-fire — acceptable.
3. Point the USA worker env at the local Redis and start it **WITH `--beat`** (rig is down, so the single-scheduler rule still holds). Code is already synced by `sync-usa-replica.sh` (health monitor alerts if sync is >2h stale).
4. Start the api on USA (same image/env as the rig api, port 8002) and repoint the `api.klaravex.com` ingress from the rig to `100.66.236.56:8002`.
5. When the rig returns: stop the USA beat FIRST, then start the rig stack, then (optionally) switch the DB primary back (§15.1).

**Untested as of 2026-08-08** — first live drill needs Anthony present.

### 15.6 Patching + OS updates (HA-safe order)

unattended-upgrades is enabled + active on both hosts (security channel auto-installs; verified 2026-08-08). Policy per Anthony's 2026-08-08 directive ("everything should be the same version and we should be pushing software updates"):

- **Python/dependencies live inside the Docker images, not the host.** "Upgrade Python" = rebuild on the rig (`docker build -f infra/Dockerfile -t infra-api:latest .` / `-t klaravex:latest`), push to USA (`docker save … | tailscale ssh … docker load`), recreate the container. Host Python versions are irrelevant to containers.
- **USA VM first**: `apt update && apt upgrade -y`, reboot if `/var/run/reboot-required` exists. It's the standby — brief HAProxy/watchdog/replica blip, self-heals; pgaf secondary catches up automatically.
- **Rig (primary)**: patch in a maintenance window. If a reboot is required: switch the DB writer to USA first (§15.1), patch + reboot rig, verify stack health, switch back. **Never reboot the rig while it holds the writer without switching over first.**
- **Container images**: stateful images stay pinned (`pgvector-af:pg17`, `postgres:16-alpine`, `redis:7-alpine`) — major bumps are deliberate projects. Stateless images (`litellm`, `open-webui`, `haproxy`) can `docker compose pull && up -d` any time.
- **Never auto-reboot.** `/var/run/reboot-required` = schedule the window, don't let the OS pick it.

---

## 16. Gotchas hit tonight (in-context notes for next time)

1. **Ubuntu 26.04 breaks PGDG PG 17 install** — libicu76 vs libicu74. Use custom Docker image on Debian bookworm base, not native apt.
2. **pg_autoctl needs pgdata in a subdirectory** of the docker volume mount (`/pgaf/data`, not `/pgaf` directly), because it removes+recreates the dir during pg_basebackup fallback.
3. **`init-perms` init container** required to chown docker volume before pg_autoctl (which runs as postgres user) can write.
4. **pg_autoctl `--hostname` must resolve to a local iface** — MagicDNS doesn't work inside the container; use tailnet IP directly.
5. **HAProxy external-check needs full PATH set** in the script — HAProxy exec context PATH is minimal.
6. **HAProxy on bridge network can't reach tailnet IPs** — use `network_mode: host` (or `host.docker.internal` for local host services).
7. **Docker bridge → host services need ufw `allow from 172.16.0.0/12`** — Docker publishes ports via iptables that bypass ufw, but container → host on the tailnet IP goes through ufw.
8. **Node pg client treats `sslmode=require` as `verify-full`** — self-signed cert fails. Use `sslmode=disable` since our pg_hba `host` entries don't require SSL, or set `sslmode=no-verify`.
9. **Docker volume mount at pgdata blocks pg_autoctl basebackup dir replace** — move mount to parent path.
10. **fail2ban banned my Mac IP briefly** — during the retry cascade after a wrong-pw bash command. Recovered via Tailscale SSH (bypasses public port).
11. **Rig password leaked in `ps` output** — I embedded pw in a `bash -c '...'` remote SSH command; the pw was visible via `ps -ef` for the duration of that command's parent bash session. Rotate.
12. **Do not commit `.env` files** — all have chmod 600 secrets. `.env` files are on target hosts only.

---

## 17. Known gaps / follow-ups

- [ ] Rotate rig anthony password (leaked in ps output earlier — 1P item `l3u3fvuh45iwwvv6e2elsomr7q`)
- [ ] Move LiteLLM UI admin pw + MCP API keys + Postgres/Redis passwords into 1P (currently in `.env` files on hosts)
- [ ] Redis Sentinel (or Azure Cache) for HA on the broker — currently rig-only SPOF
- [ ] pg_hba re-tighten: currently `trust` from wide CIDRs. Later switch to scram-sha-256 with per-user passwords once client configs support it.
- [ ] LiteLLM should use pg_auto_failover's shared DB explicitly — Prisma migrations occasionally rerun on restart because it re-syncs schema
- [ ] USA `klaravex-worker-usa` shows Docker healthcheck "unhealthy" (probe hostname mismatch); worker itself runs fine. Fix healthcheck.
- [ ] `bridge_call=true` in watchdog vapi payload if you want mobile dial on outage (currently email + Telegram only)
- [ ] `az` CLI on USA VM + `Container Apps Contributor` role → re-enable watchdog self-heal leg (currently escalation-only)
- [ ] Healthchecks.io enrolment for dead-watchdog detection
- [ ] T-INF-12 (audit): `/api/v1/escalate` accepts synthesised ticket_id via FK fallback (code merged locally, needs Container App image rebuild + deploy)
- [ ] Retire `loki-vault-mcp_pgdata` docker volume on rig (obsolete since Phase 6 moved to `pgaf-primary`)
- [ ] Docker image transfer path: currently hetzner-cx22 → Mac → rig (klaravex image, 566 MB gz). Migrate to Azure ACR pull once az login works on rig.
- [ ] Fujitsu (`anthony-primergy-tx1310-m3`) decommission — currently offline but still in tailnet ACL. Remove from tailnet + revoke Tailscale identity.

---

## 18. Directory layout on hosts

Both rig and USA VM under `/opt/klaravex/`:

```
/opt/klaravex/
├── loki-vault-mcp/          docker-compose + Dockerfile + src/ + .env  (vault-mcp)
├── litellm/                 docker-compose + config.yaml + .env
├── open-webui/              (rig only) docker-compose + .env
├── redis/                   (rig only) docker-compose + .env + data/
├── worker/                  docker-compose + .env  (klaravex_worker celery)
├── pgaf-primary/            (rig only) docker-compose  (pg_auto_failover primary)
├── pgaf-standby/            (USA only) docker-compose  (pg_auto_failover standby)
├── pgaf-monitor/            (USA only) docker-compose  (pg_auto_failover monitor)
├── haproxy/                 (USA only) docker-compose + haproxy.cfg (edge LB + pg-primary)
├── haproxy-pg-build/        (USA only) Dockerfile + check-primary.sh (custom HAProxy image)
```

Config files live inside each component's dir. `.env` files chmod 600. Backup pattern: `.env.bak-<timestamp>` before edits.

---

## 19. Session receipts (chronology)

1. Rig hardware verify: 2× 3090 (second card needed reseating), 89 GB RAM
2. Tailscale installed both nodes, mesh live
3. SSH hardened rig: pubkey-only, ufw, fail2ban
4. NoMachine 9.7.3 installed on rig (port 4000, LAN+Tailscale only)
5. Docker + NVIDIA Container Toolkit on rig, GPU passthrough verified
6. Ollama systemd on rig, both GPUs seen (47.2 GiB VRAM total)
7. LiteLLM Docker on rig + USA (`ghcr.io/berriai/litellm:main-stable`), then USA rebuild
8. All 5 models pulled sequentially (~97 GB, ~40 min total): nomic-embed-text, qwen2.5:32b, qwen2.5-coder:32b, deepseek-r1:32b, qwen2.5:72b
9. Migrated vault-mcp source from hetzner-cx22 via rsync + Mac; deployed on rig using bare-metal Ollama
10. Migrated klaravex-api image (2.18 GB / 566 MB gz) hetzner-cx22 → rig; celery worker deployed
11. Same image → USA; second worker joined the queue (both consume rig Redis via Tailscale)
12. Postgres streaming replication rig → USA (manual, PG 16 in original loki-postgres container)
13. Deployed HAProxy on USA (vault-mcp + LiteLLM LB frontends, port 3142 + 8001)
14. Phase 6 pg_auto_failover: built custom `pgvector-af:pg17` image, initialized cluster (monitor USA:5433, primary rig:5434, secondary USA:5434), migrated data via pg_dumpall
15. HAProxy `pg_primary` TCP frontend with external-check for primary detection
16. All 4 apps repointed to `100.66.236.56:5432` (auto-follows failover)
17. Controlled failover verified twice (USA→rig and rig→USA)
18. Retired legacy `loki-postgres` + `loki-postgres-standby` docker containers
19. LiteLLM final config: 11 aliases matching Fujitsu naming, `qwen-72b` default, `smart` alias with latency-based routing across local+cloud, comprehensive fallback chain
20. Open WebUI default model set to `qwen-72b`

---

*end of doc — reach me via mosh anthony@rig if this file is inaccurate or a service is behaving differently than described.*
