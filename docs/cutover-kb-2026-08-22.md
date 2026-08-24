# Cutover log — kb stream

**Date:** 2026-08-22  
**Operator:** klaravex-os agent (Anthony approved)  
**Stream:** `kb` (Phase 3 stream 6 of 8)

## Pre-flight

| Check | Status |
|-------|--------|
| Growth API `/healthz` | ✅ `ok: true`, `poc_mode: true` |
| Charter | `Klaravex2.0/revenue-agents/charters/kb.md` |
| Outbox | `Klaravex2.0/revenue-agents/outbox/kb/` |
| Growth timer | `growth-stream@kb.timer` enabled, **Mon/Wed/Fri 07:30** |
| Rig cron `kb_writer.py` | Not in user crontab at cutover time |

## Actions taken

| Component | Action |
|-----------|--------|
| n8n `[klaravex] kb-sync` | **Unpublished** (`kvxKbSyncV1`) + n8n restarted |
| `beat_trigger` | KB pipeline → **DISABLED_TRIGGERS** (app + infra): |
| | `kb-sync`, `kb-publish` |
| `klaravex_api` | Restarted to load trigger gate |
| Forced run | `POST /v1/streams/kb/run` |

## Not cut over (intentional)

| Path | Reason |
|------|--------|
| `infra/cron/kb_writer.py` | Legacy rig cron — not scheduled in user crontab; if re-enabled elsewhere, disable before dual cadence |
| `fleet_publish_bridge.py` | Publish bridge — repoint after gatekeeper cutover |

## Verify

```bash
systemctl --user list-timers growth-stream@kb.timer
docker exec klaravex_n8n n8n list:workflow --active=true | grep -i kb || true
curl -s -H "X-Growth-Secret: $GROWTH_INTERNAL_SECRET" \
  http://127.0.0.1:4210/v1/scorecard
ls -la /home/anthony/Klaravex2.0/revenue-agents/outbox/kb/
```

## Rollback

```bash
systemctl --user stop growth-stream@kb.timer
systemctl --user disable growth-stream@kb.timer
docker exec klaravex_n8n n8n publish:workflow --id=kvxKbSyncV1 2>/dev/null || \
  docker exec klaravex_n8n n8n update:workflow --id=kvxKbSyncV1 --active=true
docker restart klaravex_n8n
# Remove kb entries from DISABLED_TRIGGERS in beat_trigger.py and restart API
```

## Next streams

1. ~~leads~~ **CUT OVER**
2. ~~freelance~~ **CUT OVER**
3. ~~ads~~ **CUT OVER**
4. ~~socials~~ **CUT OVER**
5. ~~seo-blog~~ **CUT OVER**
6. ~~kb~~ **CUT OVER**
7. backlinks → gatekeeper (last)
