# Decommission log — legacy growth n8n (Phase A)

**Date:** 2026-08-24
**Operator:** Anthony approved (phased plan, Klara AI rebrand)
**Scope:** Safe decommission of legacy revenue n8n workflows. Containers/data intact.

## Action

Deactivated 6 revenue workflows in n8n (`klaravex_n8n`, SQLite `workflow_entity.active=0`), container restarted, verified live.

| Workflow | Active after | Reason |
|----------|:---:|--------|
| `[klaravex] seo-content` | 0 | Cut over to `growth-stream@seo-blog.timer` |
| `[klaravex] social-media` | 0 | Cut over to `growth-stream@socials.timer` |
| `[klaravex] leads-nurture` | 0 | Cut over to `growth-stream@leads.timer` |
| `[klaravex] freelance-pipeline` | 0 | Cut over to `growth-stream@freelance.timer` |
| `[klaravex] prospect-leads` | 0 | Cut over to `growth-stream@leads.timer` |
| `[klaravex] marketing-tick-all` | 0 | Superseded by individual Growth timers |
| `[klaravex] billing-sweeps` | **1 (kept)** | Ops/billing — not a Growth stream |
| `[klaravex] ops-sweeps` | **1 (kept)** | Ops/health — not a Growth stream |
| `[klaravex] reporting` | **1 (kept)** | Reporting — not a Growth stream |

## Safety

- These 6 were already gated downstream via `DISABLED_TRIGGERS` in `klaravex/app/api/beat_trigger.py` → **no behavior change**, this just removes the dead scheduler layer.
- DB backed up to `/tmp/n8n-db.sqlite.bak` before edit.
- Containers (`klaravex_api`, `klaravex_worker`, `klaravex_n8n`) left running.

## Rollback

```bash
docker cp /tmp/n8n-db.sqlite.bak klaravex_n8n:/home/node/.n8n/database.sqlite
docker restart klaravex_n8n
```

## Next

Phase B — scaffold `Klaravex2.0/klara` (Loki → Klara AI rebrand + port).
