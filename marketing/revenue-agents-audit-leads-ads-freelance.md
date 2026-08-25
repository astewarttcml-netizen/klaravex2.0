# Revenue Agents Audit — Leads / Ads / Freelancer streams

**Date:** 2026-08-21 · **Scope:** repo-only audit + minimal safe edits (worktree `klaravex-socials-leads-ads-23f707`)
**Files audited:** `app/tasks/prospect_leads.py`, `app/tasks/research_prospect.py`, `app/tasks/batch7_sweeps.py`, `app/tasks/outreach_followup.py`, `app/tasks/freelance_tasks.py`, `app/tasks/platform_message_agent_tasks.py`, `app/tasks/celery_app.py` (beat_schedule), `app/agents/lead_prospector.py`, `app/config.py`, `app/services/lead_capture.py`, `app/models/lead.py`, `ad-platform-signup-status.md`, `TASKS.md` Phase 15 / AC-VERIFY.

---

## 1. Current state per stream

### 1.1 Cold prospecting (Apollo → outreach)
- `prospect-leads-daily` beat entry fires `run_prospecting` daily 08:00 Berlin (iter-66). Task is healthy: dedup, daily cap (`PROSPECTING_DAILY_LIMIT=75` in prod worker.env), approval-gated sends.
- **US targeting is correct in production only by env override**: prod `worker.env` sets `APOLLO_LOCATIONS=United States`; until this audit the code default was the stale DACH `"Germany|Austria|Switzerland"` (fixed, see §3).
- Title-level ICP (`apollo_titles_list`, `app/config.py`) is correctly locked to law/accounting/medical-dental/consulting decision-makers with an explicit do-not-revert note (iter-77).
- **Industry filter was silently dead**: `lead_prospector.py:584` reads `getattr(settings, "apollo_industries_list", None)` but no such field existed in `app/config.py` — the iter-70 vertical scoping (`q_organization_keyword_tags`) never applied. Fixed (see §3).
- No defense/DIB/CMMC keyword *exclusion* exists anywhere in prospecting or freelance scouting. Titles/industries make defense hits unlikely but nothing blocks them. Left as a decision item (§4) — a negative-keyword gate is new behavior, not a config fix.

### 1.2 Research pipeline — DEAD TASK
- `app.tasks.research_prospect.run_research` is registered (celery_app.py:86, route :157) but **never dispatched**: no beat entry, no `.delay()`/`apply_async` caller anywhere. `prospect_leads.py` chains straight to `prospecting_outreach`, bypassing the research bundle entirely. Prospect research (`gather_research`) never runs.
- Not wired here (behavior change in the outbound path). Decision item §4.

### 1.3 Cold nurture / lead enrichment (batch7)
- All five batch7 sweeps have live beat entries: testimonial 09:00, cold_nurture 09:30, client_satisfaction 10:00, referral 11:00 daily; lead_enrichment 08:15 weekdays; contract_renewal Wed 09:00; weekly intelligence Mon 07:00. No dead schedules found in this file.
- `run_lead_enrichment` weekdays-only while prospecting is daily is a minor cadence mismatch (weekend prospects enriched Monday) — cosmetic, not changed.

### 1.4 Outreach follow-up cadence
- `outreach-followup-hourly` (crontab minute=15) live; multi-step cadence (phase19-007), Smartlead transport (2026-07-19 rewire), suppression-list check (phase4-005) all present.
- **Stale Berlin copy**: fallback subject `'IT support in Berlin'` was still being sent to US prospects when `outreach_subject` is null. Fixed to `'Managed IT support'` (en fallbacks only; dormant German strings left intact per the do-not-delete directive).
- **Voice-policy tension (not edited)**: follow-up bodies sign off as "Anthony" and offer "Anthony"-voiced copy. Repo voice policy bans personal-name sign-offs on marketing surfaces; cold email arguably converts better person-signed. Needs an explicit ruling from Anthony (§4). Same applies to `platform_message_reply_draft.py`'s "Anthony Stewart" sign-off — that one is defensible (freelance platform account *is* a personal identity).
- German bodies/`_pick_language` are correctly parked behind the US-only override (2026-07-19) with the .de logic commented, not deleted.

### 1.5 Freelance pipeline
- Scan 2h / strategy :30 offset / submission every 30 min / outcomes 4h / FM-cookie 5d — all live, 24/7 since 2026-07-19. Module docstrings still claimed the old 8-20 CET weekday window — fixed.
- `check_bid_outcomes` is an acknowledged placeholder (logs stats only) — fine.
- FM cookie renewal failure alert emails Anthony with runbook — good.

### 1.6 Freelance message agent (phase A draft mode)
- Poll every 15 min + draft generation 2 min later, both live, Freelancer.com only.
- **No documented promotion criteria exist anywhere** (grepped TASKS.md, PRD.md, SPEC.md, DECISIONS.md, SUMMARY.md) for phase A (draft-only) → phase B (auto-send). Drafts accumulate with no defined gate ("N consecutive drafts approved unedited", quality-gate score threshold, etc.). Decision item §4. Related: `autonomy_promotion_sweep` exists for agents generally — the message agent could plug into that framework, but nothing says so.

### 1.7 Ads (Phase 15 / ad-platform-signup-status.md)
- Phase 15 A–F all ✅ per TASKS.md (Google Ads, GA4/GTM, LinkedIn, Meta live as of 2026-07-20); conversion endpoints verified live 2026-07-26.
- Open per TASKS.md: 15.18 Looker Studio 6-KPI dashboard (deferred to 30 days of data — that window has now passed), GA4 Realtime verification (needs console access).
- `ad-platform-signup-status.md` (2026-06-12) is now largely superseded by Phase 15 completion but still holds unresolved items: Google Ads legacy account 503-382-6192 suspension check, UniFi firewall exceptions for ad-serving domains, hello@klaravex.com admin access, account IDs → 1Password. Not edited (status doc, needs Anthony's console facts).
- AC-VERIFY gate: lifted for everything except SMS (Twilio A2P 10DLC still stuck — AV.6/AV.20).

### 1.8 Consumer lead capture (personal.klaravex.com) — GAP
- `app/services/lead_capture.py` (spam scoring, UTM attribution, dedup) is **orphaned** — zero callers in `app/` or `infra/`. Its docstring claimed `app/api/leads.py` calls it; that endpoint actually routes through `klaravex_orchestrator`. Docstring corrected.
- The consumer flow (`consumer_intake` agent → Atera ticket) never creates a `Lead` row at all: consumer leads get no spam gate, no UTM/source attribution, no dedup, and are invisible to lead scoring, funnel analytics, and nurture sweeps.
- `LeadSource` had no consumer value; added `personal_site` (additive — column is `String(30)`, no migration). Wiring `consumer_intake` → `capture_lead(source="personal_site")` is a behavior change → decision item §4.

## 2. Beat-schedule findings (celery_app.py)
- No orphaned beat entries found: every scheduled task name resolves to a registered task module in `include=[...]`.
- Inverse gap: `research_prospect` registered but unscheduled/uncalled (§1.2).
- Social 2x/day US-timed entries carry a documented ±1h DST drift caveat — accepted by design.
- Timezone is Europe/Berlin globally; all "CET" comments on US-market tasks are Berlin-clock, intentional.

## 3. Edits made (this audit)
| File:line | Change |
|---|---|
| `app/config.py:216-235` | `apollo_locations` default `"Germany\|Austria\|Switzerland"` → `"United States"` (prod worker.env already set this; default was stale DACH); added new `apollo_industries` field with US ICP vertical tags + defense-exclusion note |
| `app/config.py:565-577` | Added missing `apollo_industries_list` property — restores the dead iter-70 industry filter in `lead_prospector.py:584` |
| `app/config.py:541-550` | `apollo_locations_list` docstring + final fallback `"Germany"` → `"United States"` |
| `app/tasks/outreach_followup.py:130,237` | Fallback subject `'IT support in Berlin'` → `'Managed IT support'` (en only; German strings untouched) |
| `app/tasks/prospect_leads.py:6-7` | Stale "weekdays Mon–Fri" docstring → daily (matches iter-66 beat entry) |
| `app/tasks/freelance_tasks.py:6-15` | Stale "08:00-20:00 CET weekdays" docstrings → 24/7 (matches 2026-07-19 directive) |
| `app/tasks/platform_message_agent_tasks.py:8-11` | Stale "weekdays 8-20 CET" docstring → 24/7 |
| `app/models/lead.py:39-43` | Added `LeadSource.personal_site` (additive, String(30) column, no migration) |
| `app/services/lead_capture.py:13-19` | Corrected false "Called from app/api/leads.py" docstring; documented orphaned status |

All edited files pass `py_compile`. No env files, migrations, SSH, or production APIs touched.

## 4. Actions requiring Anthony (ordered)
1. **Deploy + env check for the Apollo industry filter** — the new `apollo_industries` default only takes effect on worker redeploy; optionally set `APOLLO_INDUSTRIES` explicitly in `/opt/klaravex/worker/.env` (and the Hetzner USA `celery-usa` worker, which per AV.12 lags rig config). Verify next prospecting run logs vertical-scoped results.
2. **Decide: wire the research pipeline or delete it** — `run_research` is dead code; either have `prospect_leads` dispatch it per new prospect (chains to outreach with research bundle) or remove the module. Currently all cold outreach goes out un-researched.
3. **Rule on the "Anthony" sign-off in cold email/follow-ups** vs the corporate voice policy (no personal names on customer surfaces). If person-signed stays, record the exception in CLAUDE.md; if not, follow-up bodies in `outreach_followup.py` and the outreach agents need re-copy.
4. **Define phase A → B promotion criteria for the freelance message agent** (e.g. 25 consecutive drafts approved unedited + zero escalation misses over 30 days → auto-send for intent=QUESTION only), and decide whether it rides the existing `autonomy_promotion_sweep` framework. Nothing is documented today.
5. **Decide consumer lead-capture wiring** — approve routing `consumer_intake` submissions through `capture_lead(source=LeadSource.personal_site)` so personal.klaravex.com leads get spam gating, attribution, and analytics visibility (currently they exist only as Atera tickets).
6. **Ads console cleanup** (all console-side, no repo change): resolve legacy Google Ads account 503-382-6192 suspension question; add remaining UniFi firewall exceptions (`googleadservices.com`, `googletagmanager.com`, `doubleclick.net`, `googlesyndication.com`); record all three ad-account IDs in 1Password + note_submissions; add hello@klaravex.com as admin; verify GA4 Realtime events; build the 15.18 Looker Studio dashboard (30-day data window has now elapsed).
7. **Twilio A2P 10DLC** (AV.6/AV.20) — still the only outbound channel gated; phone-call escalation to Twilio support recommended per AC-VERIFY notes.
8. **Defense/DIB/CMMC negative filter** — decide whether prospecting + freelance scouting should hard-exclude defense keywords (currently only implicit via vertical targeting). If yes, it's a small follow-up change in `bid_strategist`/`lead_prospector`.
