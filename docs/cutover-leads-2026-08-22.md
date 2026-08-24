# Cutover log — leads stream

**Date:** 2026-08-22  
**Operator:** klaravex-os agent (Anthony approved cutover start)  
**Stream:** `leads` (Phase 3 stream 1 of 8)

## Pre-flight ✅

| Check | Result |
|-------|--------|
| Growth `/healthz` | ok, growth_enabled=true |
| Charter | `Klaravex2.0/revenue-agents/charters/leads.md` |
| Outbox | `Klaravex2.0/revenue-agents/outbox/leads/` |
| Shadow compare | `docs/shadow-compare-2026-08-22.md` |
| Growth timer | `growth-stream@leads.timer` enabled, 06:15 daily |

## Legacy disabled ✅

| Path | Action |
|------|--------|
| Rig cron `prospect_daily.sh` | Already commented out (2026-08-21) |
| n8n `[klaravex] prospect-leads` | **Deactivated** (`kvxProspectLeadsV1`) |
| `beat_trigger` | **`prospect-leads-daily` added to DISABLED_TRIGGERS** (app + infra) |

## Growth source of truth ✅

- Timer: `systemctl --user enable --now growth-stream@leads.timer`
- API: `POST /v1/streams/leads/run` with `X-Growth-Secret`
- klaravex-os: `/growth` cockpit

## Rollback

```bash
systemctl --user stop growth-stream@leads.timer
systemctl --user disable growth-stream@leads.timer
docker exec klaravex_n8n n8n update:workflow --id=kvxProspectLeadsV1 --active=true
# Remove prospect-leads-daily from DISABLED_TRIGGERS in beat_trigger.py and restart API
```

## Next streams (order)

1. ~~leads~~ **CUT OVER**
2. freelance / ads
3. socials → seo-blog → kb → backlinks
4. gatekeeper (last)
