# Phase C — Klara AI EU shadow deployment

**Date:** 2026-08-24
**Operator:** Anthony approved (shadow + full-rename)
**Status:** SHADOW LIVE — verified healthy, awaiting cutover window

## What was deployed

Rebranded `loki-agents` → `klara-agents` and brought up a shadow stack
**alongside** the live `loki_eu_*` EU node. Same Azure EU Postgres
(active-active), separate ports/network so zero impact to live traffic.

| | Live (untouched) | Shadow (new) |
|---|---|---|
| Project | `/home/anthony/loki-agents-eu/` | `/home/anthony/klara-agents-eu/` |
| Build context | `/home/anthony/itexperts-berlin/loki-agents/` | `/home/anthony/klara-agents/` |
| Image | `loki-agents-eu:latest` | `klara-agents-eu:latest` |
| API container | `loki_eu_api` → `127.0.0.1:8003` | `klara_eu_api` → `127.0.0.1:8004` |
| Worker | `loki_eu_worker` | `klara_eu_worker` |
| Redis | `loki_eu_redis` → `6380` | `klara_eu_redis` → `6381` |
| Network | `loki_eu_net` | `klara_eu_net` |
| DB | `psql-klaravexde-prod …/klaravex_eu` | **same** (active-active) |

## Verified

- `GET http://127.0.0.1:8004/health` → `{"status":"ok","service":"klara-agents"}`
- `klara_eu_worker` celery `inspect ping` → `pong` (1 node online)
- `klara_eu_api` connected to Azure EU `klaravex_eu` DB
- Live `loki_eu_*` stack still healthy on :8003 — **untouched**

## Rebrand changes in the image

- Non-root user `loki` → `klara` (Dockerfile)
- `BRAND_NAME=Klara AI`, health `service: klara-agents`
- App source = rebranded `klara/agents` (from `scripts/port-loki-to-klara.py`)
- **Preserved:** `LOKI_INTERNAL_SECRET`, `LOKI_MODE=shadow` (autonomy enum),
  `/opt/loki-agents/...` server file paths, DB schema — aliased, not renamed.

## Cutover (when ready)

1. Point EU-Watchdog / nginx upstream from `loki_eu_api:8003` → `klara_eu_api:8004`
   (or swap host ports 8003↔8004 and restart both stacks).
2. Verify public EU health + a real support request.
3. `docker compose -f docker-compose.local-eu.yml down` in `loki-agents-eu/`
   to retire the old stack.

## Rollback

Shadow is fully isolated — `docker compose -f docker-compose.klara-eu.yml down`
removes it without affecting live `loki_eu_*`.
