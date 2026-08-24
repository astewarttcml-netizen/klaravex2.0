# Cutover log — seo-blog stream

**Date:** 2026-08-22  
**Operator:** klaravex-os agent (Anthony approved)  
**Stream:** `seo-blog` (Phase 3 stream 5 of 8)

## Pre-flight

| Check | Status |
|-------|--------|
| Growth API `/healthz` | ✅ `ok: true`, `poc_mode: true` |
| Charter | `Klaravex2.0/revenue-agents/charters/seo-blog.md` |
| Outbox | `Klaravex2.0/revenue-agents/outbox/seo-blog/` |
| Growth timer | `growth-stream@seo-blog.timer` enabled, **06:45 daily** |
| Rig cron `daily_seo_blog.sh` | Already disabled in crontab (2026-08-21) |

## Actions taken

| Component | Action |
|-----------|--------|
| n8n `[klaravex] seo-content` | **Unpublished** (`kvxSeoContentV1`) + n8n restarted |
| `beat_trigger` | SEO pipeline → **DISABLED_TRIGGERS** (app + infra): |
| | `seo-content-daily`, `brand-voice-check`, `seo-publish` |
| `klaravex_api` | Restarted to load trigger gate |
| Forced run | `POST /v1/streams/seo-blog/run` → `9db80dd2…` |

## Not cut over (intentional)

| Path | Reason |
|------|--------|
| `infra/cron/daily_seo_blog.py` | Legacy auto-publish bypassing gatekeeper — already commented out in crontab; stays off until gatekeeper SoT = Klaravex2.0 |
| `fleet_publish_bridge.py` | Publish bridge — repoint after gatekeeper cutover |

## Verify

```bash
systemctl --user list-timers growth-stream@seo-blog.timer
docker exec klaravex_n8n n8n list:workflow --active=true | grep -i seo || true
crontab -l | grep daily_seo_blog
curl -s -H "X-Growth-Secret: $GROWTH_INTERNAL_SECRET" \
  http://127.0.0.1:4210/v1/scorecard
ls -la /home/anthony/Klaravex2.0/revenue-agents/outbox/seo-blog/
```

## Rollback

```bash
systemctl --user stop growth-stream@seo-blog.timer
systemctl --user disable growth-stream@seo-blog.timer
docker exec klaravex_n8n n8n publish:workflow --id=kvxSeoContentV1 2>/dev/null || \
  docker exec klaravex_n8n n8n update:workflow --id=kvxSeoContentV1 --active=true
docker restart klaravex_n8n
# Remove seo-blog entries from DISABLED_TRIGGERS in beat_trigger.py and restart API
```

## Next streams

1. ~~leads~~ **CUT OVER**
2. ~~freelance~~ **CUT OVER**
3. ~~ads~~ **CUT OVER**
4. ~~socials~~ **CUT OVER**
5. ~~seo-blog~~ **CUT OVER**
6. kb → backlinks → gatekeeper (last)
