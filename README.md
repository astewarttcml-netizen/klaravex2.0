# Klaravex2.0 — Growth OS (strangler-fig home)

**Status:** Phase 2 shadow — timers live; `growth-api.service` on `:4210`  
**Purpose:** Parallel product tree for Klaravex Growth OS. Live `/home/anthony/klaravex` stays the production monolith until streams cut over one at a time.

## What this is

Klaravex2.0 owns the **implementation home** for Growth OS Layers **A** (revenue-agent charters + local outbox) and **C** (Growth API + systemd timers). It points at, but does not vendor:

| Layer | Path / system | Role |
|-------|---------------|------|
| **A** | `revenue-agents/` (this repo) | Charters + outbox — SoT for agent behavior |
| **B** | n8n (ops glue) | Optional callers of Growth API — never owns rubrics |
| **C** | `growth/` (this repo) | FastAPI control plane + timers — independent of Celery beat / Loki |
| **D** | `/home/anthony/klaravex-os` | Operator cockpit (Next.js `:4100`) — sibling repo |

Legacy PRD: `/home/anthony/klaravex/docs/prd-growth-os.md` (points here).

## Relation to klaravex and klaravex-os

- **`/home/anthony/klaravex`** — live Growth / Loki / Celery world. Do not treat it as the Growth OS build target anymore. Shadow runs may still write there until cutover.
- **`/home/anthony/klaravex-os`** — Layer D operator UI. Calls Growth API (C). Not vendored into this tree yet.
- **This tree** — strangler destination for A+C, schedulers, adapters stubs, and migration runbooks.

## Non-goals

- Replacing Loki handlers, voice/support runtime, or product deploys
- Vendoring KLARAVEX-OS or Founders OS into this repo
- Sharing Celery beat / Loki crash domains (Growth must keep running if they die)
- ~~Full Claude charter execution in the API stub (Phase later — endpoints accept runs only)~~ Charter executor live in `growth/executor/` (Claude `-p` background thread)
- Defense / DIB / CMMC surfaces

## Quick start (Growth API stub)

```bash
cd /home/anthony/Klaravex2.0
python3 -m venv .venv && source .venv/bin/activate
pip install -r growth/requirements.txt
cp growth/.env.example growth/.env   # set GROWTH_INTERNAL_SECRET
export $(grep -v '^#' growth/.env | xargs)
uvicorn growth.api.main:app --host 127.0.0.1 --port "${PORT:-4200}"
curl -s "http://127.0.0.1:${PORT:-4200}/healthz"
```

Intended default is **4200** (Layer D / klaravex-os uses **4100**). If 4200 is already bound on this host, set `PORT=4210` (or free the port) and mirror that in timer `GROWTH_API_BASE`.

See `MIGRATION.md`, `docs/architecture.md`, and `docs/cutover-checklist.md`.
