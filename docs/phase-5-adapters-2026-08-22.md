# Phase 5 — Adapters + Layer D wire (COMPLETE)

**Date:** 2026-08-22  
**Verdict:** **PASS** — klaravex-os calls Growth API exclusively for growth operations

## Exit criteria (`MIGRATION.md`)

| Criterion | Status |
|-----------|--------|
| Clay / Taplio / Smartlead / WordPress adapter modules | ✅ `growth/adapters/` |
| `/v1/adapters` probe endpoint | ✅ |
| `/v1/adapters/{name}/invoke` sandbox invoke | ✅ **added Phase 5** |
| Credential awareness (no secret leakage) | ✅ `growth/adapters/credentials.py` reads worker `.env` |
| klaravex-os `/growth` → Layer C only | ✅ all routes via `lib/growth-api.ts` → `:4210` |
| Connections board `growth-api` connector | ✅ |

## Layer D → C route map

| klaravex-os route | Growth API |
|-------------------|------------|
| `GET /api/growth/scorecard` | `GET /v1/scorecard` |
| `GET /api/growth/runs` | `GET /v1/runs` |
| `GET /api/growth/adapters` | `GET /v1/adapters` |
| `POST /api/growth/adapters/[name]/invoke` | `POST /v1/adapters/{name}/invoke` |
| `POST /api/growth/streams/[name]/run` | `POST /v1/streams/{name}/run` |
| `POST /api/growth/streams/run-all` | `POST /v1/streams/run-all` |
| `POST /api/growth/gate/[draftId]/verdict` | `POST /v1/gate/{draftId}/verdict` |

No growth stream triggers go through legacy klaravex API or Celery from the OS UI.

## Adapter status (this rig, POC on)

Credential source: `klaravex/infra/docker-services/worker/.env` via `GROWTH_KLARAVEX_ROOT`.

| Adapter | Creds | Status (POC) |
|---------|-------|----------------|
| smartlead | ✅ `SMARTLEAD_API_KEY` | `ready` (sandbox sample) |
| wordpress | ✅ `WP_SITE_URL` + password | `ready` (sandbox sample) |
| clay | ❌ no `CLAY_API_KEY` | `poc_sandbox` / `stub` |
| taplio | ❌ no `TAPLIO_API_KEY` | `poc_sandbox` / `stub` |

Live I/O remains blocked while `GROWTH_POC_MODE=true`. Flip POC off + implement live calls per adapter when ready for production publish/outreach.

## Verify

```bash
chmod +x /home/anthony/Klaravex2.0/scripts/phase5-verify.sh
/home/anthony/Klaravex2.0/scripts/phase5-verify.sh
# UI: http://localhost:4100/growth — Adapters panel → Probe
```

## Migration complete

| Phase | Status |
|-------|--------|
| 0 Inventory | ✅ |
| 1 Stub C live | ✅ |
| 2 Shadow | ✅ |
| 3 Cutover (8 streams) | ✅ |
| 4 Beat-kill | ✅ |
| **5 Adapters + D wire** | ✅ |

## Production follow-ups (optional)

1. `GROWTH_POC_FAST=false` then `GROWTH_POC_MODE=false`
2. Implement live `smartlead.enqueue` / `wordpress.publish` in adapter modules
3. Add Clay + Taplio keys to worker env when those tools are adopted
4. Attio deals import for Funnel tab
