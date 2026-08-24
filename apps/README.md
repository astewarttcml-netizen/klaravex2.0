# Apps — external layers (not vendored)

## Layer D — KLARAVEX-OS

**Path:** `/home/anthony/klaravex-os` (sibling repository / tree)  
**Role:** Operator cockpit (Next.js, typically `:4100`). Funnel, social, finances, agents, pipelines. Token-gated. Calls **Growth API (C)** for stream run / scorecard / gate after cutover.

Do **not** confuse with Founders OS at `/home/anthony/klaravex/klaravex-os` (client portal).

Not vendored into Klaravex2.0 yet — wire via HTTP + `X-Growth-Secret`.

## Layer B — n8n

Optional ops glue. May call Growth API for triggers and notifications. Must **not** own charter rubrics, gate verdicts SoT, or be required for cadence (timers → C still run if n8n is down).
