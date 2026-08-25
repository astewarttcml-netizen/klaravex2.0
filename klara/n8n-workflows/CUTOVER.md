# Flows + n8n cutover status (2026-08-25)

## Ownership

| Piece | Owner | Notes |
|---|---|---|
| Loki flow YAML archetypes | **Klaravex2.0** `klara/flows/` | Ported 1:1 (pricing archetypes — not n8n) |
| n8n workflow JSON | **Klaravex2.0** `klara/n8n-workflows/` | Mirror of monolith JSON + archive |
| Resolution regression cron | **Klaravex2.0** `klara/cron/loki_resolution_regression.py` | Ported; scheduling separate |
| Live n8n runtime | **Monolith** `klaravex_n8n` | sqlite storage (Azure drift still open) |

## Live n8n (verified)

**Active (ops only):** billing-sweeps, ops-sweeps, reporting  

**Inactive (Growth OS owns cadence via `growth-stream@*.timer`):** prospect-leads, seo-content, social-media, freelance-pipeline, leads-nurture, marketing-tick-all  

Do **not** re-activate revenue workflows — dual-fire with Growth timers.

## Schedule ownership

Revenue / Growth streams → Klaravex2.0 Growth API timers (`growth-api.service` + `growth-stream@*.timer`).  
Ops/billing/reporting → n8n stays until a later ops cutover.

## Open remediation (not this cutover)

n8n compose claims Azure Postgres but container uses sqlite — separate drift ticket.
