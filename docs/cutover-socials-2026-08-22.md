# Cutover log — socials stream

**Date:** 2026-08-22  
**Operator:** klaravex-os agent (Anthony approved)  
**Stream:** `socials` (Phase 3 stream 4 of 8)

## Pre-flight

| Check | Status |
|-------|--------|
| Growth API `/healthz` | ✅ `ok: true`, `poc_mode: true` |
| Charter | `Klaravex2.0/revenue-agents/charters/socials.md` |
| Outbox | `Klaravex2.0/revenue-agents/outbox/socials/` |
| Growth timer | `growth-stream@socials.timer` enabled, **06:30 daily** |

## Actions taken

| Component | Action |
|-----------|--------|
| n8n `[klaravex] social-media` | **Unpublished** (`kvxSocialMediaV1`) + n8n restarted |
| `beat_trigger` | Social triggers → **DISABLED_TRIGGERS** (app + infra): |
| | `generate-us-social-drafts`, `generate-social-drafts-et`, `generate-social-drafts-pt` |
| | `route-qualified-social-posts`, `linkedin-drafts-sweep-daily`, `social-publish` |
| `klaravex_api` | Restarted to load trigger gate |
| Forced run | `POST /v1/streams/socials/run` |

## Not cut over (intentional)

| Path | Reason |
|------|--------|
| `fleet_publish_bridge.py` rig cron | Publish bridge — repoint after gatekeeper SoT = Klaravex2.0 |
| `social-report-daily` | Reporting only; already disabled at trigger gate |
| `[klaravex] marketing-tick-all` | Separate marketing tick; not socials charter |

## Verify

```bash
systemctl --user list-timers growth-stream@socials.timer
docker exec klaravex_n8n n8n list:workflow | grep -i social
curl -s -H "X-Growth-Secret: $GROWTH_INTERNAL_SECRET" \
  http://127.0.0.1:4210/v1/scorecard
ls -la /home/anthony/Klaravex2.0/revenue-agents/outbox/socials/
```

## Rollback

```bash
systemctl --user stop growth-stream@socials.timer
systemctl --user disable growth-stream@socials.timer
docker exec klaravex_n8n n8n update:workflow --id=kvxSocialMediaV1 --active=true
docker restart klaravex_n8n
# Remove social entries from DISABLED_TRIGGERS in beat_trigger.py and restart API
```

## Next streams

1. ~~leads~~ **CUT OVER**
2. ~~freelance~~ **CUT OVER**
3. ~~ads~~ **CUT OVER**
4. ~~socials~~ **CUT OVER**
5. seo-blog → kb → backlinks → gatekeeper (last)
