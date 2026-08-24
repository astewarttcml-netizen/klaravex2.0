# Shadow compare — leads — 2026-08-22 (POC fast path)

## Growth side (Klaravex2.0)

- **Mode:** `GROWTH_POC_MODE=true`, `GROWTH_POC_FAST=true`
- **Scorecard:** 8/8 streams `completed`
- **Outbox:** `/home/anthony/Klaravex2.0/revenue-agents/outbox/leads/2026-08-22-*-poc.md` (3 fixture prospects)
- **Earlier Claude runs:** full drafts also present (`tx-accounting-practices-shortlist`, etc.)

## Legacy side

- No dated files under `/home/anthony/klaravex/revenue-agents/outbox/leads/` for 2026-08-22 at compare time.

## Verdict

**POC shadow pass** — Growth produces on demand; legacy path idle for this stream/day. Safe to rehearse cutover checklist; do **not** disable legacy beat until Anthony signs off.

## Phase 4

Beat-kill dry-run log: `docs/beat-kill-2026-08-22T11-24-34Z.md` — 8 Growth timers armed; no Celery beat container on this rig.
