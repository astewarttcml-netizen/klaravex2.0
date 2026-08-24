# Per-stream cutover checklist (copy-paste)

**Stream:** `________________`  
**Date / operator:** `________________`  
**Rollback SHA / timer unit known:** `________________`

## Pre-flight

- [ ] Growth API `/healthz` → `ok: true`, `growth_enabled: true`
- [ ] `POST /v1/streams/<stream>/run` with `X-Growth-Secret` → `202`
- [ ] Charter exists: `revenue-agents/charters/<stream>.md`
- [ ] Outbox dir exists: `revenue-agents/outbox/<stream>/`
- [ ] Shadow compare reviewed for this stream (`scripts/shadow-compare.md`)
- [ ] Legacy schedule identified (beat task / cron / session name) and documented

## Cutover

- [ ] Announce window (ops channel / note_submissions)
- [ ] Disable **only this stream** on legacy scheduler
- [ ] Enable `growth-stream@<stream>.timer` (user or system — see `growth/schedulers/README.md`)
- [ ] Force one run: `systemctl --user start growth-stream@<stream>.service` **or** curl `POST /v1/streams/<stream>/run`
- [ ] Confirm ledger: `GET /v1/runs` shows new record
- [ ] Confirm outbox artifact (when executor wired) or accepted stub log for Phase 1–2
- [ ] Scorecard: `GET /v1/scorecard` counts look sane

## Gate / publish path (if applicable)

- [ ] Gatekeeper sees drafts in **Klaravex2.0** outbox (not only legacy)
- [ ] `POST /v1/gate/{draft_id}/verdict` recorded if used
- [ ] Publishing bridge path updated or still intentionally on legacy (note which)

## Sign-off

- [ ] No dual cadence (legacy + Growth both firing) for this stream
- [ ] Rollback steps rehearsed mentally / pasted below
- [ ] note_submissions / daily log updated

## Immediate rollback (if needed)

```bash
systemctl --user stop growth-stream@STREAM.timer
systemctl --user disable growth-stream@STREAM.timer
# re-enable legacy schedule for STREAM only
curl -s -H "X-Growth-Secret: $GROWTH_INTERNAL_SECRET" \
  http://127.0.0.1:4200/v1/scorecard
```
