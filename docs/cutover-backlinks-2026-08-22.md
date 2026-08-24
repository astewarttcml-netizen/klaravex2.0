# Cutover log — backlinks stream

**Date:** 2026-08-22  
**Operator:** klaravex-os agent (Anthony approved)  
**Stream:** `backlinks` (Phase 3 stream 7 of 8)

## Pre-flight

| Check | Status |
|-------|--------|
| Growth API `/healthz` | ✅ `ok: true`, `poc_mode: true` |
| Charter | `Klaravex2.0/revenue-agents/charters/backlinks.md` |
| Outbox | `Klaravex2.0/revenue-agents/outbox/backlinks/` |
| Growth timer | `growth-stream@backlinks.timer` enabled, **Wed 07:15 weekly** |

## Actions taken

| Component | Action |
|-----------|--------|
| n8n `[klaravex] backlink-builder` | **Unpublished** (`kvxBacklinkBuilderV1`) + n8n restarted |
| `beat_trigger` | **`backlink-builder-daily` → DISABLED_TRIGGERS** (app + infra) |
| Rig cron `backlink_builder.sh` | **Disabled** in user crontab (2026-08-22) |
| `klaravex_api` | Restarted to load trigger gate |
| Forced run | `POST /v1/streams/backlinks/run` |

## Verify

```bash
systemctl --user list-timers growth-stream@backlinks.timer
docker exec klaravex_n8n n8n list:workflow --active=true | grep -i backlink || true
crontab -l | grep backlink
curl -s -H "X-Growth-Secret: $GROWTH_INTERNAL_SECRET" \
  http://127.0.0.1:4210/v1/scorecard
ls -la /home/anthony/Klaravex2.0/revenue-agents/outbox/backlinks/
```

## Rollback

```bash
systemctl --user stop growth-stream@backlinks.timer
systemctl --user disable growth-stream@backlinks.timer
# Re-enable rig cron line in crontab (remove disabled comment prefix)
docker exec klaravex_n8n n8n publish:workflow --id=kvxBacklinkBuilderV1 2>/dev/null || \
  docker exec klaravex_n8n n8n update:workflow --id=kvxBacklinkBuilderV1 --active=true
docker restart klaravex_n8n
# Remove backlink-builder-daily from DISABLED_TRIGGERS in beat_trigger.py and restart API
```

## Next streams

1. ~~leads~~ **CUT OVER**
2. ~~freelance~~ **CUT OVER**
3. ~~ads~~ **CUT OVER**
4. ~~socials~~ **CUT OVER**
5. ~~seo-blog~~ **CUT OVER**
6. ~~kb~~ **CUT OVER**
7. ~~backlinks~~ **CUT OVER**
8. **gatekeeper** (last)
