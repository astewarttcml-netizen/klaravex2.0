# Growth OS strangler-fig migration

Minimal-downtime path: **shadow → cutover per stream**. Live klaravex keeps serving until each stream’s cadence and outbox SoT move to Klaravex2.0.

## Phases 0–5

| Phase | Name | Exit criteria |
|-------|------|----------------|
| **0** | Inventory | Beat/task hints catalogued (`scripts/phase0-inventory.sh` → `docs/inventory-beat.todo.md`); streams named; secrets plan (`GROWTH_INTERNAL_SECRET`) |
| **1** | Stub C live | Growth API `/healthz` + auth’d endpoints up; timers **installed but disabled** or dry-run only |
| **2** | Shadow | Timers fire → Growth API accepts runs; charters still may dual-write or compare outboxes (`scripts/shadow-compare.md`); legacy beat still owns “truth” |
| **3** | Per-stream cutover | One stream at a time: disable legacy schedule → enable Growth timer → verify outbox + scorecard |
| **4** | Beat-kill test | Stop Celery beat (controlled window); Growth streams still run on cadence; document evidence |
| **5** | Adapters + D wire | Optional Clay/Taplio/Smartlead/WordPress adapters; KLARAVEX-OS (D) calls C exclusively for growth |

## Per-stream cutover order (recommended)

1. `leads` (low publish blast radius)  
2. `freelance` / `ads` (human proposals, not gated publish)  
3. `socials` → `seo-blog` → `kb` → `backlinks` (gated publish path)  
4. `gatekeeper` last among A (depends on ungated drafts landing in new outbox)

Use `docs/cutover-checklist.md` for each stream.

## Rollback (per stream)

1. Disable `growth-stream@<name>.timer` (`systemctl --user stop` + `disable`).
2. Re-enable the legacy klaravex schedule for that stream only.
3. Leave Klaravex2.0 outbox intact (do not delete) — treat as forensic / replay.
4. Confirm legacy outbox path is receiving new drafts; note gap window in scorecard.

**Do not** roll back all streams because one failed — strangler is stream-scoped.

## Beat-kill test (Phase 4)

**Goal:** Prove Growth OS does not share Celery beat / Loki crash domain.

1. Record pre-test: timer list, last successful Growth runs, beat status.  
2. Stop Celery beat only (leave workers if needed for non-growth).  
3. Wait ≥ one cadence slot for at least two cut-over streams.  
4. Expect: Growth API ledger shows `accepted`/completed runs; outbox gains dated files; Loki may be idle/failed — **irrelevant**.  
5. Restart beat; attach evidence to CAB / daily log.  
6. If Growth did not fire: treat as P1 — timers/API before re-enabling reliance on Growth.

## Kill switch

`GROWTH_ENABLED=false` → API returns 503 on run triggers; timers should still call API (no silent local bypass). Document any cron that shells Claude without hitting C as a migration defect.
