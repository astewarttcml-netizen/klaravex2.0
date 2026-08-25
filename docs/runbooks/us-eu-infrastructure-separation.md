# US/EU Infrastructure Separation Plan
**2026-08-06** — Created after cert generation session

## Why This Exists

Klaravex LLC (US, Wyoming) and the EU operation are legally distinct entities. They have separate databases, separate Azure Postgres instances, and separate customer bases. But at the infrastructure level, they share a host, share a Docker daemon, and — critically — the `note_submissions` audit pipeline only recognized EU surfaces. Any cross-contamination of data, credentials, or audit trails between the two entities is an existential legal risk.

This document defines the hard boundary and the steps to enforce it.

---

## Layer 1: Certificate Authority Separation (DONE)

| Entity | CA | Location | Purpose |
|--------|----|----------|---------|
| US (Klaravex LLC) | `Klaravex US Internal CA` (C=US, O=Klaravex LLC) | `/home/anthony/loki-us-certs/` | Signs all US node certificates |
| EU | `Klaravex EU Internal CA` (C=DE, O=Klaravex EU) | `/home/anthony/loki-eu-certs/` | Signs all EU node certificates |

**Rule:** No cross-signing. A cert signed by the US CA must never be accepted by EU infrastructure, and vice versa. Each side trusts only its own CA.

### US Certificates (generated 2026-08-06)

| File | CN | Purpose |
|------|----|---------|
| `klaravex-us-ca.crt` | Klaravex US Internal CA | Root CA — 4096-bit RSA, 10-year |
| `node-us-api.crt` | node-us-api | US API container TLS |
| `node-us-worker.crt` | node-us-worker | US Worker container TLS |

### EU Certificates (existing, generated 2026-08-05)

| File | CN | Purpose |
|------|----|---------|
| `klaravex-eu-ca.crt` | Klaravex EU Internal CA | Root CA — 4096-bit RSA, 10-year |
| `node-local.crt` | node-local | EU API container TLS |
| `node-eu-watchdog.crt` | node-eu-watchdog | EU Watchdog TLS |

---

## Layer 2: Database Separation (DONE)

| Entity | Host | Database | Schema | Auth |
|--------|------|----------|--------|------|
| US | `klaravex-db-r2.postgres.database.azure.com:5432` | `klaravex` | `klaravex.note_submissions` | `klaravexadmin` (1P: `4v7hrmrs6t5dj2q5oyfhba63qe`) |
| EU | `psql-klaravexde-prod.postgres.database.azure.com:5432` | `klaravex_eu` | `public.note_submissions` | `pgadmin` (separate vault item) |

**Already separate.** Different servers, different databases, different credentials. No shared schema.

---

## Layer 3: Container & Network Separation (DONE for certs, network isolation remains)

### Production deployment (discovered 2026-08-06)
The local `~/klaravex/infra/docker-compose.klaravex.yml` does NOT match production. Production on the USA VM (Hetzner, 87.99.147.244 / Tailscale 100.66.236.56) is deployed via `/opt/klaravex/worker/docker-compose.yml` with:
- `admin-api` → container `klaravex-admin-api` (uvicorn, port 8010)
- `worker` → container `klaravex-worker-usa` (Celery, queue klaravex)
- Both mount `/opt/klaravex/worker/app` → `/app/app` and `/opt/klaravex/worker/migrations` → `/app/migrations`

### What was done
1. **[DONE]** Created `/opt/loki-us-certs/` on USA VM
2. **[DONE]** Copied all 7 US cert files (CA + node certs) to USA VM via scp over Tailscale
3. **[DONE]** Added cert volume `/opt/loki-us-certs:/etc/loki-us-certs:ro` to both services in production compose
4. **[DONE]** Added `US_NODE_CERT_PATH=/etc/loki-us-certs/node-us-api.crt` to admin-api and `/etc/loki-us-certs/node-us-worker.crt` to worker
5. **[DONE]** Containers recreated and restarted — both healthy, certs visible at `/etc/loki-us-certs/` inside containers
6. **Network-level isolation** — still TODO. Both stacks use Docker bridge networks but there's no firewall rule preventing a compromised US container from reaching EU containers.

---

## Layer 4: Audit Pipeline Separation (DONE)

### Resolution: Option A
- `~/.claude/hooks/klaravex-policy/config-us.json` created with US surfaces only
- `~/.claude/hooks/klaravex-policy/bin/policy-check-us` created (Bun, loads from `config-us.json` via `loadConfigUS()`)
- `~/.claude/bin/note-submit` auto-routes to correct policy checker based on surface prefix (case statement)
- `~/.claude/hooks/klaravex-policy/lib/config.ts` — added `loadConfigUS()` export
- Dead Cloud86 safety gate removed from `note-submit` (Cloud86 was decommissioned long ago, all surfaces route to Azure now)
- Both EU config.json and US config-us.json surfaces now correctly map to `azure` target

### Verified
- 3 stuck US fallback rows resubmitted to Azure (IDs 19440-19442)
- New US note_submissions land in Azure correctly (verified through 19444)

---

## Layer 5: Credential Isolation (MOSTLY DONE)

| Credential | US | EU | Shared? |
|-----------|----|----|---------|
| DB password | 1P `4v7hrmrs6t5dj2q5oyfhba63qe` | Separate vault item | NO |
| LiteLLM key | 1P `66pfgqzljgxsw6yjox72el2y4a` | N/A | NO |
| Stripe keys | US-only | N/A | NO |
| Hetzner server | Shared host | Shared host | YES — risk |
| Docker daemon | Shared | Shared | YES — risk |
| Tailscale network | Shared tailnet | Shared tailnet | YES — risk |

### Risk: Shared host
Both stacks run on the same Hetzner CX22. The US scaling trigger (ARR > $50K → dedicated US VPS) is the permanent fix for this. Until then, Docker network isolation and cert separation are the mitigations.

---

## Layer 6: Code & Config Separation (PARTIAL)

### What's already separate
- Separate docker-compose files
- Separate .env files (US: `infra/docker-services/worker/.env`, EU: separate)
- Separate databases
- Separate CA + certs (as of today)

### What still touches both
- `~/.claude/hooks/klaravex-policy/` — single hook directory, currently EU-only config
- `~/.claude/bin/note-submit` — single script, currently rejects US surfaces
- `~/.claude/mcp/note-submit-server/server.ts` — single MCP server, has all surfaces in enum but config blocks US
- Same git repo (`~/klaravex`) — US and EU code coexist

---

## Immediate Actions (ALL DONE 2026-08-06)

1. **[DONE]** Generate US CA + node certificates in `/home/anthony/loki-us-certs/`
2. **[DONE]** Mount US certs into US Docker containers — updated both local `docker-compose.klaravex.yml` AND production `/opt/klaravex/worker/docker-compose.yml` on USA VM
3. **[DONE]** Add `US_NODE_CERT_PATH` env var to both admin-api and worker services on USA VM
4. **[DONE]** Fix note_submit for US surfaces (Option A: separate config — `config-us.json` + `policy-check-us`)
5. **[DONE]** Submit stuck rows in `~/.claude/note-submissions-fallback.jsonl` (all resolved, file is now empty)
6. **[DONE]** Copy certs to USA VM and restart containers — certs verified visible and services healthy

## Medium-Term Actions

6. Add Docker network egress rules — US containers must not reach EU containers
7. Separate the git repo or enforce directory-level ownership (US code vs EU code)
8. Scale to dedicated US VPS when ARR crosses $50K (already policy)

---

## Hard Rules (binding)

1. **No config file may list both US and EU surfaces.** One company = one config.
2. **No credential may be shared between US and EU services.**
3. **No US container mounts EU certs. No EU container mounts US certs.**
4. **A note_submissions row must never be routed to the wrong database.** Surface → target mapping is deterministic and enforced at the policy-check level.
5. **Any new cross-entity infrastructure must be reviewed against this document before creation.**
