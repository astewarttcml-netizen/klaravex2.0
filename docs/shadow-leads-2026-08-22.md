# Shadow — leads stream (Phase 2)

**Started:** 2026-08-22  
**Stream:** `leads`  
**Legacy schedule:** `prospect-leads-daily` → `app.tasks.prospect_leads.run_prospecting` (Celery beat, still enabled during shadow)

## Pre-flight

| Check | Status |
|-------|--------|
| Growth API `/healthz` | ✅ |
| Charter `revenue-agents/charters/leads.md` | ✅ |
| Outbox dir `revenue-agents/outbox/leads/` | ✅ |
| Timer `growth-stream@leads.timer` | ✅ enabled (daily 06:15) |
| Layer D `/growth` | ✅ |

## Shadow window rules

- **Legacy beat stays ON** — no dual-publish risk (legacy outbox empty; publish bridge not pointed at Klaravex2.0 yet).
- **Growth path must produce** dated artifact in `Klaravex2.0/revenue-agents/outbox/leads/`.
- Executor hardened 2026-08-22: restricted tools, fail if no `DONE` line / no outbox file.

## Verify

```bash
# Force run (same as timer)
systemctl --user start growth-stream@leads.service

# Ledger
curl -s -H "X-Growth-Secret: $GROWTH_INTERNAL_SECRET" \
  http://127.0.0.1:4210/v1/runs | python3 -m json.tool

# Outbox compare
ls -la /home/anthony/klaravex/revenue-agents/outbox/leads/2026-08-22* 2>/dev/null || true
ls -la /home/anthony/Klaravex2.0/revenue-agents/outbox/leads/2026-08-22* 2>/dev/null || true
```

## Cutover gate (not yet)

- [ ] Green shadow run with outbox artifact
- [ ] Shadow compare reviewed
- [ ] Disable `prospect-leads-daily` on legacy beat only
- [ ] Confirm no dual cadence for 48h
