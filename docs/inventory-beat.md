# Phase 0 — Legacy scheduler inventory → Growth OS cutover map

**Generated:** 2026-08-22  
**Live monolith:** `/home/anthony/klaravex`  
**Strangler home:** `/home/anthony/Klaravex2.0`  
**Rule:** Growth streams move to Layer C timers; Loki/beat/cron stay until per-stream cutover.

---

## Executive summary

| Finding | Implication |
|---------|-------------|
| Celery `beat_schedule` comment says pipelines are **n8n-only** | Revenue cadence is split: beat + n8n + `infra/cron` + charter sessions |
| **No beat container** in compose (2026-08-22 note) | Many beat entries are **documentation only**; live triggers are n8n → `beat_trigger` or rig cron |
| Klaravex2.0 timers **already installed** (8 streams) | Phase 2 shadow active — **Growth API must stay up** (`growth-api.service`) |
| `revenue-agents/` gatekeeper is SoT for publish | Legacy Celery/social/SEO paths still P3-approve to Anthony until cutover |

---

## Stream cutover matrix

| Growth stream (A/C) | Legacy scheduler(s) | Legacy task / script | Cutover phase | Shadow |
|---------------------|---------------------|----------------------|---------------|--------|
| **leads** | n8n → `beat_trigger` | `prospect-leads-daily` → `run_prospecting` | **1 — first** | ✅ Klaravex2.0 timer 06:15 |
| **leads** (research) | — (dead) | `research_prospect.run_research` never called | Wire or delete before cutover | Klaravex2.0 research pre-enrich |
| **socials** | beat (dead?) + n8n disabled | `generate-social-drafts-et/pt`, `generate-us-social-drafts` | 3 | ✅ timer 06:30 |
| **socials** (route wins) | beat live | `route-qualified-social-posts` every 15m | After socials draft cutover | n/a |
| **seo-blog** | n8n + beat | `seo-content-daily` | 3 | ✅ timer 06:45 |
| **seo-blog** (auto-publish) | rig cron | `infra/cron/daily_seo_blog.py` 06:00 | **Separate** — bypasses gatekeeper; cut last | Shadow compare outbox |
| **kb** | rig cron | `infra/cron/kb_writer.py` | 3 | ✅ timer Mon/Wed/Fri |
| **backlinks** | rig cron | `infra/cron/backlink_builder.sh` 07:00 | 4 | ✅ timer Wed |
| **freelance** | beat + n8n | `freelance-platform-scan-2h`, bid strategy/submission 30m | 2 | ✅ timer hourly |
| **freelance** | beat | `freelance-message-poll-15m`, drafts 15m | Stays on beat until freelance charter owns replies | n/a |
| **ads** | manual / console | No beat; proposals in outbox only | 2 | ✅ timer Mon |
| **gatekeeper** | charter session | `revenue-agents/charters/gatekeeper.md` | **Last among A** | ✅ timer 08:00 |
| **publish bridge** | rig cron | `infra/cron/fleet_publish_bridge.py` | After gatekeeper SoT = Klaravex2.0 outbox | Point bridge at 2.0 outbox |

---

## Keep on Loki / beat (not Growth OS)

| Beat / task | Reason |
|-------------|--------|
| `approval-notifier-30m` | Product approval queue (until adjudicator/CRO) |
| `health-check-sweep-daily` | Infra |
| `autonomy-promotion-sweep-nightly` | Agent autonomy |
| `llm-budget-alarm-daily` | Cost guard |
| `approval-expiry-daily` | Product |
| `critical-webhook-bridge-15m` | Ops |
| `smoke-test-sweep-daily` | QA |
| `invoice-*`, `contract-renewal-*` | Billing (CFO domain, not CRO) |
| Voice / remote session crons | Loki handlers |

---

## n8n → beat_trigger (revenue-related, from `TASK_REGISTRY`)

| Trigger name | Celery task | Growth stream | Notes |
|--------------|-------------|---------------|-------|
| `prospect-leads-daily` | `prospect_leads.run_prospecting` | **leads** | Primary cold outbound |
| `outreach-followup-hourly` | `outreach_followup` | leads (follow-up) | Keep until Smartlead adapter in C |
| `seo-content-daily` | `seo_content` | **seo-blog** | P3 approval path |
| `freelance-platform-scan-2h` | `freelance_tasks.run_platform_scan` | **freelance** | |
| `freelance-bid-strategy-30m` | `run_bid_strategy` | freelance | |
| `freelance-bid-submission-30m` | `run_bid_submission` | freelance | |
| `generate-us-social-drafts` | social drafts | socials | **DISABLED** at trigger gate |
| `route-qualified-social-posts` | social route | socials | Still live via beat |

---

## Shadow mode checklist (Phase 2 — current)

- [x] Klaravex2.0 Growth API stub + executor
- [x] User systemd timers for all 8 streams
- [ ] **`growth-api.service` enabled** (timers fail if API down)
- [ ] Compare outbox: `Klaravex2.0/revenue-agents/outbox/` vs `klaravex/revenue-agents/outbox/`
- [ ] Scorecard visible in klaravex-os `/growth` (needs `GROWTH_API_BASE` in `.env.local`)
- [ ] One full leads cadence: legacy + 2.0 both produce artifacts without double-send

---

## Per-stream cutover order (locked)

1. **leads** — lowest publish blast radius; Klaravex2.0 research pipeline already running  
2. **freelance** / **ads** — proposals, not auto-publish  
3. **socials** → **seo-blog** → **kb** → **backlinks**  
4. **gatekeeper** + repoint **fleet_publish_bridge** to Klaravex2.0 outbox  
5. Beat-kill test (Phase 4)

See `MIGRATION.md` and `docs/cutover-checklist.md`.
