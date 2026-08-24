# Shadow compare — old vs new outbox

During Phase 2, legacy klaravex and Klaravex2.0 may both receive drafts (or only one produces while the other is dry-run). Use this to decide cutover readiness.

## Paths

| Side | Root |
|------|------|
| Legacy | `/home/anthony/klaravex/revenue-agents/outbox/<stream>/` |
| New | `/home/anthony/Klaravex2.0/revenue-agents/outbox/<stream>/` |

## Procedure (per stream, per day)

1. List dated files on both sides for the shadow window:

   ```bash
   STREAM=leads
   DAY=$(date +%F)
   ls -la /home/anthony/klaravex/revenue-agents/outbox/$STREAM/${DAY}* 2>/dev/null || true
   ls -la /home/anthony/Klaravex2.0/revenue-agents/outbox/$STREAM/${DAY}* 2>/dev/null || true
   ```

2. Diff structure (headings, CTA presence, gate section) — not byte-identical prose:

   ```bash
   # example: compare latest files if both exist
   diff -u <(head -n 40 legacy.md) <(head -n 40 new.md) || true
   ```

3. Check Growth ledger: `GET /v1/runs` and `/v1/scorecard` for accepted runs matching the timer fire times.

4. Pass criteria for cutover candidate:
   - New side produced on cadence (± grace)
   - No dual-publish risk (or publish bridge still pointed at legacy only — documented)
   - Failures understood (secret, API down, charter path)

5. Fail → stay in shadow; fix C/timers before disabling legacy.
