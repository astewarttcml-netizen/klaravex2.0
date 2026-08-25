# Beat trigger cutover status (2026-08-25)

## Ownership

| Piece | Owner |
|---|---|
| Growth stream cadence | Klaravex2.0 `growth-stream@*.timer` + `growth-api.service` |
| `DISABLED_TRIGGERS` source of truth | `klaravex/app/api/beat_trigger.py` (= Klaravex2.0 `klara/beat/beat_trigger.py`, 32 names) |
| Live API enforcement | `klaravex_api` bind-mount of `app/api/beat_trigger.py` |

## Phase 3 Growth block (must stay DISABLED in monolith)

prospect-leads-daily, freelance×4, social×6, seo×3, kb×2, backlink-builder-daily

## Verify

```bash
docker exec klaravex_api python -c 'from app.api.beat_trigger import DISABLED_TRIGGERS; print(len(DISABLED_TRIGGERS))'
# expect 32
systemctl --user list-timers 'growth-stream@*' --no-pager
```
