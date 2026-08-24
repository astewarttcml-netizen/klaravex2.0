# Beat / revenue inventory (Phase 0 stub)

Generated: 2026-08-22T04:20:26Z
Source tree: `/home/anthony/klaravex` (read-only scan)

## Next actions

- [ ] Map each match to a Growth stream or `n/a`
- [ ] Decide shadow vs ignore for non-growth beat entries
- [ ] Record cutover owner per stream

## ripgrep hints

### celery beat / Celery beat

```
/home/anthony/klaravex/scripts/watchdog/README.md:46:schedule it in `beat_schedule`, retire the cron.
/home/anthony/klaravex/scripts/watchdog/watchdog.py:122:    lines.append("\nFix: ssh anthony-klaravex (rig via Tailscale) OR ssh root@hetzner-usa-watchdog; docker logs klaravex-worker --since 24h | grep error; verify celery beat schedule. See runbooks/rig-usa-ha-stack-2026-07-01.md §9.")
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:524:| 2026-08-18 | celery_app.py timezone → America/New_York; beat_schedule cleaned | Claude |
/home/anthony/klaravex/marketing/revenue-agents-audit-leads-ads-freelance.md:4:**Files audited:** `app/tasks/prospect_leads.py`, `app/tasks/research_prospect.py`, `app/tasks/batch7_sweeps.py`, `app/tasks/outreach_followup.py`, `app/tasks/freelance_tasks.py`, `app/tasks/platform_message_agent_tasks.py`, `app/tasks/celery_app.py` (beat_schedule), `app/agents/lead_prospector.py`, `app/config.py`, `app/services/lead_capture.py`, `app/models/lead.py`, `ad-platform-signup-status.md`, `TASKS.md` Phase 15 / AC-VERIFY.
/home/anthony/klaravex/marketing/revenue-agents-audit-socials-blogs.md:4:seo_content, beat_trigger, celery beat, infra/cron content pipelines, n8n
/home/anthony/klaravex/marketing/revenue-agents-audit-socials-blogs.md:103:from celery beat directly. If the DISABLED_TRIGGERS business-stage rationale
/home/anthony/klaravex/marketing/revenue-agents-audit-socials-blogs.md:164:   `social-report-daily` / `generate-report-daily` gating to celery beat to
/home/anthony/klaravex/drafts/dispatch-2026-06-18/T14.27.md:23:app.conf.beat_schedule = {
/home/anthony/klaravex/app/api/beat_trigger.py:208:    # celery_app.py's beat_schedule entries of the same names NEVER fire —
/home/anthony/klaravex/runbooks/rig-usa-ha-stack-2026-07-01.md:368:- Rig: `celery -A app.tasks.celery_klaravex worker --pool=solo -Q klaravex,default,approvals --beat --schedule=/tmp/celerybeat-schedule`
/home/anthony/klaravex/runbooks/rig-usa-ha-stack-2026-07-01.md:377:**Beat rule (2026-08-08):** the rig worker runs `--beat` (`celery -A app.tasks.celery_klaravex worker --pool=solo -Q klaravex,default,approvals --beat --schedule=/tmp/celerybeat-schedule`) and is the ONLY scheduler in the fleet. The USA worker is a hot-standby consumer and must NOT carry `--beat`. Two beats = every cron task fires twice (duplicate Smartlead sends, duplicate SEO posts).
/home/anthony/klaravex/app/tasks/rarv_heartbeat.py:15:Not in any beat_schedule yet. When ready, add to
/home/anthony/klaravex/app/tasks/rarv_heartbeat.py:16:app/tasks/celery_app.py beat_schedule:
/home/anthony/klaravex/app/tasks/celery_klaravex.py:152:    beat_schedule={
/home/anthony/klaravex/app/tasks/celery_klaravex.py:177:            "kwargs": {"triggered_by": "celery_beat"},
/home/anthony/klaravex/app/tasks/celery_app.py:202:    beat_schedule={
/home/anthony/klaravex/app/tasks/daily_report.py:6:Scheduled via celery beat at 07:00 Europe/Berlin every morning.
/home/anthony/klaravex/app/tasks/daily_report.py:37:def generate_daily_report(self, report_date: str | None = None, triggered_by: str = "celery_beat"):
/home/anthony/klaravex/app/tasks/outreach_followup.py:6:Schedule: every hour via celery_app.beat_schedule.
/home/anthony/klaravex/app/tasks/prospect_leads.py:43:def run_prospecting(self, triggered_by: str = "celery_beat"):
/home/anthony/klaravex/app/tasks/prospect_leads.py:48:        triggered_by: 'celery_beat' or 'admin_api' — for logging only.
/home/anthony/klaravex/app/tasks/followup.py:6:Schedule: top of every hour (beat_schedule in celery_app.py)
/home/anthony/klaravex/app/tasks/invoice_reminder.py:6:Schedule: weekdays 09:00 CET (beat_schedule in celery_app.py)
/home/anthony/klaravex/app/tasks/social_media.py:6:Scheduling (celery_app.py beat_schedule is the single source of truth —
/home/anthony/klaravex/app/tasks/social_media.py:159:    celery beat's "generate-daily-social-drafts" entry which relied on this
/home/anthony/klaravex/app/tasks/pipeline_reporter.py:6:Schedule: Monday 08:30 Europe/Berlin (beat_schedule in celery_app.py)
/home/anthony/klaravex/app/tasks/proposal_followup.py:6:Schedule: every 6 hours (beat_schedule in celery_app.py)
/home/anthony/klaravex/app/tasks/weekly_growth_advisor.py:7:Scheduled via celery beat every Monday at 08:00 UTC (10:00 CEST). May
/home/anthony/klaravex/app/tasks/weekly_growth_advisor.py:46:def run_weekly_growth_advisor(self, triggered_by: str = "celery_beat") -> dict:
/home/anthony/klaravex/app/tasks/batch7_sweeps.py:6:Schedule: daily at various times (beat_schedule in celery_app.py)
/home/anthony/klaravex/app/tasks/rarv_heartbeat_klaravex.py:13:Fired by klaravex_beat every 30 min via beat_schedule entry
/home/anthony/klaravex/app/tasks/freelance_tasks.py:7:were sitting unbid for up to ~12h; see beat_schedule comment in celery_app.py):
/home/anthony/klaravex/app/tasks/platform_message_agent_tasks.py:8:  poll_freelancer_com_messages   - Every 15 minutes, 24/7 (beat_schedule
/home/anthony/klaravex/app/models/weekly_growth_report.py:39:        String(100), nullable=False, server_default="celery_beat"
/home/anthony/klaravex/app/models/report.py:36:        String(100), nullable=False, default="celery_beat"
/home/anthony/klaravex/app/models/report.py:37:    )  # "celery_beat" | "api.manual" | agent name
/home/anthony/klaravex/infra/docker-services/beat/docker-compose.yml:8:              "--loglevel=info", "--schedule=/tmp/celerybeat-schedule"]
/home/anthony/klaravex/infra/docker-services/beat/docker-compose.yml:17:      test: ["CMD-SHELL", "test -f /tmp/celerybeat-schedule && echo ok || exit 1"]
/home/anthony/klaravex/infra/scripts/klaravex-beat-watchdog.sh:18:# Celery beat rewrites /tmp/celerybeat-schedule inside the container every time
/home/anthony/klaravex/infra/scripts/klaravex-beat-watchdog.sh:32:SCHEDULE_PATH="/tmp/celerybeat-schedule"
/home/anthony/klaravex/infra/api/beat_trigger.py:102:    # beat_schedule now (2026-07-19, Anthony directive: exactly 2x/day, one
/home/anthony/klaravex/infra/api/beat_trigger.py:186:    # social draft generation is owned by celery_app.py's own beat_schedule.
/home/anthony/klaravex/infra/docker-services/worker/docker-compose.yml:8:              "--loglevel=info", "--pool=solo", "-Q", "klaravex,default,approvals", "--beat", "--schedule=/tmp/celerybeat-schedule"]
/home/anthony/klaravex/infra/backups/r2-schema-before-delta8-20260814T040948Z.sql:1416:    triggered_by character varying(100) DEFAULT 'celery_beat'::character varying NOT NULL,
/home/anthony/klaravex/infra/agents/daily_report.py:10:  triggered_by — who triggered this (default: "celery_beat")
/home/anthony/klaravex/infra/agents/daily_report.py:50:        triggered_by = input_data.get("triggered_by", "celery_beat")
/home/anthony/klaravex/infra/agents/registry_additions.py:89:Add to app/tasks/celery_app.py beat_schedule:
/home/anthony/klaravex/infra/models/weekly_growth_report.py:39:        String(100), nullable=False, server_default="celery_beat"
/home/anthony/klaravex/infra/models/report.py:36:        String(100), nullable=False, default="celery_beat"
/home/anthony/klaravex/infra/models/report.py:37:    )  # "celery_beat" | "api.manual" | agent name
/home/anthony/klaravex/infra/tasks/rarv_heartbeat.py:15:Not in any beat_schedule yet. When ready, add to
/home/anthony/klaravex/infra/tasks/rarv_heartbeat.py:16:app/tasks/celery_app.py beat_schedule:
/home/anthony/klaravex/infra/tasks/celery_klaravex.py:148:    beat_schedule={
/home/anthony/klaravex/infra/tasks/celery_klaravex.py:171:            "kwargs": {"triggered_by": "celery_beat"},
/home/anthony/klaravex/infra/tasks/celery_app.py:177:    beat_schedule={
/home/anthony/klaravex/infra/tasks/celery_app.py:194:            "kwargs": {"triggered_by": "celery_beat"},
/home/anthony/klaravex/infra/tasks/daily_report.py:6:Scheduled via celery beat at 07:00 Europe/Berlin every morning.
/home/anthony/klaravex/infra/tasks/daily_report.py:37:def generate_daily_report(self, report_date: str | None = None, triggered_by: str = "celery_beat"):
/home/anthony/klaravex/infra/tasks/outreach_followup.py:6:Schedule: every hour via celery_app.beat_schedule.
/home/anthony/klaravex/infra/tasks/prospect_leads.py:42:def run_prospecting(self, triggered_by: str = "celery_beat"):
/home/anthony/klaravex/infra/tasks/prospect_leads.py:47:        triggered_by: 'celery_beat' or 'admin_api' — for logging only.
/home/anthony/klaravex/infra/tasks/followup.py:6:Schedule: top of every hour (beat_schedule in celery_app.py)
/home/anthony/klaravex/infra/tasks/rarv_heartbeat_klaravex.py:13:Fired by klaravex_beat every 30 min via beat_schedule entry
/home/anthony/klaravex/infra/tasks/weekly_growth_advisor.py:7:Scheduled via celery beat every Monday at 08:00 UTC (10:00 CEST). May
/home/anthony/klaravex/infra/tasks/weekly_growth_advisor.py:46:def run_weekly_growth_advisor(self, triggered_by: str = "celery_beat") -> dict:
/home/anthony/klaravex/infra/tasks/batch7_sweeps.py:6:Schedule: daily at various times (beat_schedule in celery_app.py)
/home/anthony/klaravex/infra/tasks/pipeline_reporter.py:6:Schedule: Monday 08:30 Europe/Berlin (beat_schedule in celery_app.py)
/home/anthony/klaravex/infra/tasks/proposal_followup.py:6:Schedule: every 6 hours (beat_schedule in celery_app.py)
/home/anthony/klaravex/infra/tasks/invoice_reminder.py:6:Schedule: weekdays 09:00 CET (beat_schedule in celery_app.py)
```

### revenue / growth task names

```
/home/anthony/klaravex/marketing/revenue-agents-audit-leads-ads-freelance.md:1:# Revenue Agents Audit — Leads / Ads / Freelancer streams
/home/anthony/klaravex/marketing/revenue-agents-audit-socials-blogs.md:1:# Revenue Agents Audit — Socials + Blogs Streams
/home/anthony/klaravex/marketing/revenue-agents-audit-socials-blogs.md:135:| `marketing/revenue-agents-audit-socials-blogs.md` | This report |
/home/anthony/klaravex/marketing/revenue-agents-audit-seo-kb-backlinks.md:1:# Revenue Agents Audit — SEO + Knowledge Base + Backlinks
/home/anthony/klaravex/marketing/revenue-agents-audit-seo-kb-backlinks.md:53:| `marketing/revenue-agents-audit-seo-kb-backlinks.md` | **NEW** — this report |
/home/anthony/klaravex/revenue-agents/README.md:1:# Revenue Agents — Standalone Claude Agent Fleet
/home/anthony/klaravex/revenue-agents/README.md:5:A fleet of Claude-native revenue agents, **fully separate from Loki and Celery**.
/home/anthony/klaravex/revenue-agents/README.md:14:revenue-agents/
/home/anthony/klaravex/revenue-agents/README.md:32:2. The session reads `revenue-agents/README.md` and its own charter file.
/home/anthony/klaravex/revenue-agents/README.md:143:- Surface is `klaravex.com` or `personal.klaravex.com` (all revenue-agent work
/home/anthony/klaravex/revenue-agents/outbox/socials/2026-08-21-hipaa-risk-analysis-plus-wifi-deadzones-r2.md:173:- `revenue-agents/outbox/media-test/img-2026-08-21-stat-callout-89pct.png`
/home/anthony/klaravex/revenue-agents/outbox/socials/2026-08-21-hipaa-risk-analysis-plus-wifi-deadzones-r2.md:179:- `revenue-agents/outbox/media-test/cgt-20260821141619-7598h.mp4` — proven
/home/anthony/klaravex/revenue-agents/tools/infographic/render.py:26:  revenue-agents/outbox/socials/<date>-<slug>-infographic.png
/home/anthony/klaravex/revenue-agents/tools/infographic/render.py:48:# tools/infographic -> revenue-agents -> outbox/socials
/home/anthony/klaravex/docs/prd-growth-os.md:1:# Klaravex Growth OS PRD
/home/anthony/klaravex/docs/prd-growth-os.md:6:**Related:** `revenue-agents/README.md` (legacy Layer A; see Implementation home)
/home/anthony/klaravex/docs/prd-growth-os.md:10:> Build and cut over Growth OS in **`/home/anthony/Klaravex2.0`** (strangler-fig: Layers A+C, timers, runbooks). Layer D remains **`/home/anthony/klaravex-os`**. This live `klaravex` tree stays production until per-stream cutover; do not treat it as the Growth OS implementation target.
/home/anthony/klaravex/docs/prd-growth-os.md:16:> | `/home/anthony/klaravex-os` | **KLARAVEX-OS** | Internal operator console (Next.js `:4100`). Token-gated. Funnel, social, finances, agents, pipelines → Klaravex API / n8n. **Not** a client portal. **This** is Growth OS Layer D. |
/home/anthony/klaravex/docs/prd-growth-os.md:23:Deliver an **all-in-one Growth OS** for the non-engineering revenue lifecycle: lead generation, socials, SEO/blog, knowledge base, backlinks, ads, freelance bids, gated publish prep, and accountability scorecards.
/home/anthony/klaravex/docs/prd-growth-os.md:27:- Revenue streams keep running when Celery beat or Loki crash — Growth OS must not share their failure domain.
/home/anthony/klaravex/docs/prd-growth-os.md:68:| **A** | `revenue-agents/` | Charters, outbox, **gatekeeper SoT for agent behavior** and approval rubric |
/home/anthony/klaravex/docs/prd-growth-os.md:98:A  revenue-agents/   B  n8n (optional)    D  klaravex-os (:4100)
/home/anthony/klaravex/docs/prd-growth-os.md:117:  revenue-agents/          # A (existing)
/home/anthony/klaravex/docs/prd-growth-os.md:123:  docs/prd-growth-os.md    # this PRD
/home/anthony/klaravex/docs/prd-growth-os.md:168:**Explicit:** **no Celery beat** for Growth OS streams.
/home/anthony/klaravex/docs/prd-growth-os.md:170:| Stream | Cadence (aligned with `revenue-agents/README.md`) |
/home/anthony/klaravex/docs/prd-growth-os.md:191:- Optional future: **Approval Adjudicator** for product / Loki paths only — not required for Growth OS v1.
/home/anthony/klaravex/docs/prd-growth-os.md:228:- Gatekeeper rubric and agent behavior SoT remain in `revenue-agents/` (A), not in n8n or KLARAVEX-OS.
/home/anthony/klaravex/revenue-agents/charters/backlinks.md:20:- This charter and `revenue-agents/README.md`.
/home/anthony/klaravex/revenue-agents/charters/backlinks.md:23:- Own outbox history (`revenue-agents/outbox/backlinks/`) — do not re-prepare
/home/anthony/klaravex/revenue-agents/charters/backlinks.md:34:- One file per week: `revenue-agents/outbox/backlinks/YYYY-MM-DD-<slug>.md`
/home/anthony/klaravex/revenue-agents/charters/leads.md:17:- This charter and `revenue-agents/README.md`.
/home/anthony/klaravex/revenue-agents/charters/leads.md:18:- Own outbox history (`revenue-agents/outbox/leads/`) — never re-shortlist a
/home/anthony/klaravex/revenue-agents/charters/leads.md:39:- One file per day: `revenue-agents/outbox/leads/YYYY-MM-DD-<slug>.md`
/home/anthony/klaravex/revenue-agents/charters/gatekeeper.md:5:Adjudicate every ungated draft in the revenue-agent outboxes. Anthony runs four
/home/anthony/klaravex/revenue-agents/charters/gatekeeper.md:19:- `revenue-agents/outbox/socials/`
/home/anthony/klaravex/revenue-agents/charters/gatekeeper.md:20:- `revenue-agents/outbox/seo-blog/`
/home/anthony/klaravex/revenue-agents/charters/gatekeeper.md:21:- `revenue-agents/outbox/kb/`
/home/anthony/klaravex/revenue-agents/charters/gatekeeper.md:22:- `revenue-agents/outbox/leads/`
/home/anthony/klaravex/revenue-agents/charters/gatekeeper.md:23:- `revenue-agents/outbox/backlinks/`
/home/anthony/klaravex/revenue-agents/charters/gatekeeper.md:27:- `revenue-agents/outbox/ads/` — never gated.
/home/anthony/klaravex/revenue-agents/charters/gatekeeper.md:28:- `revenue-agents/outbox/freelance/` — never gated.
/home/anthony/klaravex/revenue-agents/charters/gatekeeper.md:41:- This charter and `revenue-agents/README.md`.
/home/anthony/klaravex/revenue-agents/charters/ads.md:18:- This charter and `revenue-agents/README.md`.
/home/anthony/klaravex/revenue-agents/charters/ads.md:19:- Own outbox history (`revenue-agents/outbox/ads/`) — read last week's
/home/anthony/klaravex/revenue-agents/charters/ads.md:24:  `revenue-agents/outbox/ads/inputs/` or `marketing/ad-campaigns/` (CSV or
/home/anthony/klaravex/revenue-agents/charters/ads.md:30:- One file per week: `revenue-agents/outbox/ads/YYYY-MM-DD-<slug>.md`
/home/anthony/klaravex/revenue-agents/charters/seo-blog.md:21:- This charter and `revenue-agents/README.md`.
/home/anthony/klaravex/revenue-agents/charters/seo-blog.md:22:- Own outbox history (`revenue-agents/outbox/seo-blog/`, including
/home/anthony/klaravex/revenue-agents/charters/seo-blog.md:29:  `revenue-agents/outbox/kb/` (avoid drafting the same topic the KB agent
/home/anthony/klaravex/revenue-agents/charters/seo-blog.md:37:- One file per day: `revenue-agents/outbox/seo-blog/YYYY-MM-DD-<slug>.md`
/home/anthony/klaravex/revenue-agents/charters/seo-blog.md:61:runtime pattern" in `revenue-agents/README.md`.) Save the asset file (or
/home/anthony/klaravex/revenue-agents/charters/freelance.md:20:- This charter and `revenue-agents/README.md`.
/home/anthony/klaravex/revenue-agents/charters/freelance.md:21:- Own outbox history (`revenue-agents/outbox/freelance/`) — build on prior
/home/anthony/klaravex/revenue-agents/charters/freelance.md:33:- One file per day: `revenue-agents/outbox/freelance/YYYY-MM-DD-<slug>.md`
/home/anthony/klaravex/revenue-agents/charters/kb.md:94:- This charter and `revenue-agents/README.md`.
/home/anthony/klaravex/revenue-agents/charters/kb.md:95:- Own outbox history (`revenue-agents/outbox/kb/`, including subdirectories) —
/home/anthony/klaravex/revenue-agents/charters/kb.md:98:- Recent SEO drafts in `revenue-agents/outbox/seo-blog/` — avoid drafting a
/home/anthony/klaravex/revenue-agents/charters/kb.md:106:- One file per session: `revenue-agents/outbox/kb/YYYY-MM-DD-<slug>.md`
/home/anthony/klaravex/revenue-agents/charters/kb.md:130:runtime pattern" in `revenue-agents/README.md`.) Save the asset file (or
/home/anthony/klaravex/revenue-agents/charters/socials.md:20:- This charter and `revenue-agents/README.md`.
/home/anthony/klaravex/revenue-agents/charters/socials.md:21:- Own outbox history (`revenue-agents/outbox/socials/`, including
/home/anthony/klaravex/revenue-agents/charters/socials.md:27:  `revenue-agents/outbox/seo-blog/` and `revenue-agents/outbox/kb/` (a fresh
/home/anthony/klaravex/revenue-agents/charters/socials.md:35:- One file per day: `revenue-agents/outbox/socials/YYYY-MM-DD-<slug>.md`
/home/anthony/klaravex/revenue-agents/charters/socials.md:99:    section in `revenue-agents/README.md` for the exact commands. Note:
/home/anthony/klaravex/app/models/lead.py:43:                                            # marketing/revenue-agents-audit-leads-ads-freelance.md)
/home/anthony/klaravex/infra/cron/fleet_publish_bridge.py:3:fleet_publish_bridge.py — bridge revenue-agent fleet drafts into production.
/home/anthony/klaravex/infra/cron/fleet_publish_bridge.py:5:Scans revenue-agents/outbox/{socials,seo-blog,kb}/ for markdown drafts whose
/home/anthony/klaravex/infra/cron/fleet_publish_bridge.py:63:        p = root / "revenue-agents" / "outbox"
/home/anthony/klaravex/infra/cron/fleet_publish_bridge.py:66:    raise SystemExit("FATAL: no revenue-agents/outbox found")
/home/anthony/klaravex/infra/cron/dnc_scrub.py:31:    python3 infra/cron/dnc_scrub.py --briefs-dir revenue-agents/outbox/cold-calls
/home/anthony/klaravex/infra/cron/dnc_scrub.py:223:    ap.add_argument("--briefs-dir", default="revenue-agents/outbox/cold-calls",
/home/anthony/klaravex/infra/migrations/046_fleet_bridge_log.sql:2:-- State table for the revenue-agent fleet publish bridge
/home/anthony/klaravex/infra/migrations/046_fleet_bridge_log.sql:5:-- The bridge scans revenue-agents/outbox/{socials,seo-blog,kb}/ for drafts
/home/anthony/klaravex/app/agents/bid_strategist.py:129:Cover letter rules (template v1, revenue-agents/outbox/freelance/2026-08-21-proposal-templates-v1.md):
/home/anthony/klaravex/app/services/lead_capture.py:19:marketing/revenue-agents-audit-leads-ads-freelance.md.
```

### crontab / OnCalendar nearby

```
/home/anthony/klaravex/drafts/dispatch-2026-06-18/T14.27.md:23:app.conf.beat_schedule = {
/home/anthony/klaravex/docs/runbooks/ad-platform-setup.md:141:4. Schedule the tick endpoint via cron (Azure Logic App or Hetzner crontab) so it fires every 6 hours
/home/anthony/klaravex/tools/install-signals-cron.sh:5:# Linux  → installs a user crontab entry
/home/anthony/klaravex/tools/install-signals-cron.sh:22:# out of the plist/crontab. See LOADER_SCRIPT below.
/home/anthony/klaravex/tools/install-signals-cron.sh:64:  # then runs the collector. Keeps secrets out of the plist/crontab.
/home/anthony/klaravex/tools/install-signals-cron.sh:135:    if crontab -l 2>/dev/null | grep -qF "$CRON_MARKER"; then
/home/anthony/klaravex/tools/install-signals-cron.sh:136:      crontab -l | grep -F "$CRON_MARKER" | sed 's/^/  /'
/home/anthony/klaravex/tools/install-signals-cron.sh:156:    crontab -l 2>/dev/null | grep -vF "$CRON_MARKER" > "$tmp" || true
/home/anthony/klaravex/tools/install-signals-cron.sh:157:    crontab "$tmp" && rm -f "$tmp"
/home/anthony/klaravex/tools/install-signals-cron.sh:176:    echo "Cron line that would be appended (via crontab -):"
/home/anthony/klaravex/tools/install-signals-cron.sh:215:  ( crontab -l 2>/dev/null | grep -vF "$CRON_MARKER" || true ) > "$tmp"
/home/anthony/klaravex/tools/install-signals-cron.sh:217:  crontab "$tmp" && rm -f "$tmp"
/home/anthony/klaravex/tools/install-signals-cron.sh:220:  echo "Verify: crontab -l | grep klaravex-signals"
/home/anthony/klaravex/marketing/revenue-agents-audit-leads-ads-freelance.md:26:- `outreach-followup-hourly` (crontab minute=15) live; multi-step cadence (phase19-007), Smartlead transport (2026-07-19 rewire), suppression-list check (phase4-005) all present.
/home/anthony/klaravex/agency-agents/security/security-incident-responder.md:242:    crontab -l -u "$user" 2>/dev/null | grep -v '^#' |
/home/anthony/klaravex/agency-agents/security/security-incident-responder.md:243:        sed "s/^/${user}: /" >> "$OUTDIR/crontabs.txt"
/home/anthony/klaravex/STATUS-AUDIT-2026-07-29.md:97:prospect_daily.sh copied to ~/klaravex/infra/cron/ but crontab not yet updated.
/home/anthony/klaravex/STATUS-AUDIT-2026-07-29.md:172:2. **Fix crontab** — 3 entries pointing to deleted /opt/.
/home/anthony/klaravex/infra/docker-services/loki-vault-mcp/DEPLOY.md:164:crontab -e
/home/anthony/klaravex/app/tasks/rarv_heartbeat.py:20:        "schedule": crontab(minute="*/30"),
/home/anthony/klaravex/app/tasks/celery_app.py:25:from celery.schedules import crontab
/home/anthony/klaravex/app/tasks/celery_app.py:202:    beat_schedule={
/home/anthony/klaravex/app/tasks/celery_app.py:211:            "schedule": crontab(hour=7, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:216:            "schedule": crontab(hour=10, minute=0, day_of_week="1"),
/home/anthony/klaravex/app/tasks/celery_app.py:222:            "schedule": crontab(hour=9, minute=0, day_of_month="1"),
/home/anthony/klaravex/app/tasks/celery_app.py:228:            "schedule": crontab(hour=9, minute=0, day_of_week="3"),
/home/anthony/klaravex/app/tasks/celery_app.py:234:            "schedule": crontab(hour=7, minute=0, day_of_week="1"),
/home/anthony/klaravex/app/tasks/celery_app.py:240:            "schedule": crontab(hour=6, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:246:            "schedule": crontab(hour=3, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:252:            "schedule": crontab(hour=23, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:258:            "schedule": crontab(hour=4, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:264:            "schedule": crontab(hour=8, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:270:            "schedule": crontab(minute="*/15"),
/home/anthony/klaravex/app/tasks/celery_app.py:276:            "schedule": crontab(hour=4, minute=30),
/home/anthony/klaravex/app/tasks/celery_app.py:282:            "schedule": crontab(hour=5, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:288:            "schedule": crontab(hour=10, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:295:            "schedule": crontab(hour=11, minute=0, day_of_week="1"),
/home/anthony/klaravex/app/tasks/celery_app.py:301:            "schedule": crontab(hour=12, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:307:            "schedule": crontab(minute=0, hour="0,6,12,18"),
/home/anthony/klaravex/app/tasks/celery_app.py:313:            "schedule": crontab(hour=8, minute=30, day_of_week="1"),
/home/anthony/klaravex/app/tasks/celery_app.py:319:            "schedule": crontab(hour=8, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:341:        # and Celery crontab has no per-entry timezone override, so these
/home/anthony/klaravex/app/tasks/celery_app.py:352:            "schedule": crontab(hour=15, minute=0),  # 09:00 ET
/home/anthony/klaravex/app/tasks/celery_app.py:363:            "schedule": crontab(hour=18, minute=0),  # 09:00 PT
/home/anthony/klaravex/app/tasks/celery_app.py:370:            "schedule": crontab(hour=9, minute=0, day_of_week="1-5"),
/home/anthony/klaravex/app/tasks/celery_app.py:376:            "schedule": crontab(minute="*/15"),
/home/anthony/klaravex/app/tasks/celery_app.py:381:            "schedule": crontab(minute="2,17,32,47"),
/home/anthony/klaravex/app/tasks/celery_app.py:387:            "schedule": crontab(hour=8, minute=0, day_of_week="1"),
/home/anthony/klaravex/app/tasks/celery_app.py:393:            "schedule": crontab(hour=2, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:400:            "schedule": crontab(hour=9, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:405:            "schedule": crontab(hour=11, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:410:            "schedule": crontab(hour=9, minute=30),
/home/anthony/klaravex/app/tasks/celery_app.py:415:            "schedule": crontab(hour=8, minute=15, day_of_week="1-5"),
/home/anthony/klaravex/app/tasks/celery_app.py:420:            "schedule": crontab(hour=10, minute=0),
/home/anthony/klaravex/app/tasks/celery_app.py:426:            "schedule": crontab(minute="0,30"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:14:from celery.schedules import crontab
/home/anthony/klaravex/app/tasks/celery_klaravex.py:152:    beat_schedule={
/home/anthony/klaravex/app/tasks/celery_klaravex.py:164:            "schedule": crontab(hour=7, minute=0),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:169:            "schedule": crontab(hour=10, minute=0, day_of_week="1"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:175:            "schedule": crontab(hour=8, minute=0, day_of_week="1-5"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:182:            "schedule": crontab(minute=0),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:188:            "schedule": crontab(minute=15),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:194:            "schedule": crontab(hour=9, minute=0, day_of_month="1"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:200:            "schedule": crontab(hour=9, minute=0, day_of_week="3"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:206:            "schedule": crontab(hour=7, minute=0, day_of_week="1"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:212:            "schedule": crontab(hour=6, minute=0),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:218:            "schedule": crontab(hour=3, minute=0),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:224:            "schedule": crontab(hour=23, minute=0),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:230:            "schedule": crontab(hour=4, minute=0),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:236:            "schedule": crontab(hour=8, minute=0),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:242:            "schedule": crontab(minute="*/15"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:248:            "schedule": crontab(hour=4, minute=30),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:254:            "schedule": crontab(hour=5, minute=0),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:260:            "schedule": crontab(hour=10, minute=0),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:267:            "schedule": crontab(hour=11, minute=0, day_of_week="1"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:273:            "schedule": crontab(hour=12, minute=0),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:279:            "schedule": crontab(minute=0, hour="0,6,12,18"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:285:            "schedule": crontab(hour=8, minute=30, day_of_week="1"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:291:            "schedule": crontab(hour=6, minute=30, day_of_week="1"),
/home/anthony/klaravex/app/tasks/celery_klaravex.py:298:            "schedule": crontab(hour=8, minute=0),
```

### charter stream names

```
/home/anthony/klaravex/SETUP.md:106:- Freelancer.com: `FREELANCER_USER_ID`, `FREELANCER_OAUTH_TOKEN`
/home/anthony/klaravex/SETUP.md:107:- Freelance watcher tuning: `FREELANCE_MAX_BIDS_PER_DAY`, `FREELANCE_MIN_BUDGET_USD`, `FREELANCE_MIN_FIT_SCORE`
/home/anthony/klaravex/SETUP.md:137:psql "$DATABASE_URL" -f migrations/2026-06-20-add-freelance-category.sql
/home/anthony/klaravex/TASKS.md:11:- [x] BRK-5: Freelance bid emails firing with no UI to action them (completed 2026-08-04)
/home/anthony/klaravex/TASKS.md:16:- [x] Memory-location audit (#19): loki-vault → klaravex-vault repo/path refs swept across infra/, app/, loki-agents/ (config defaults, note_submission models, journal agents, rarv_heartbeat, freelance_scout, beat_trigger, notes service, backstory generator, bulk-index, recording sink). Verified py_compile.
/home/anthony/klaravex/TASKS.md:37:- [ ] pipeline-socials-audit (#12): generate → quality gate → publish end-to-end; dry-run publish; no approval gate. (medium)
/home/anthony/klaravex/TASKS.md:38:- [ ] pipeline-freelancer-audit (#12): scout → bid → submit → convert end-to-end; dry-run bids; :8090/DeepSeek. (medium)
/home/anthony/klaravex/LAUNCH-READINESS-TASKS.md:71:- ⏸ L15 — [OUT OF SCOPE here — .de sites are managed by the separate .de loki agent team; see ../itexperts-berlin/DE-HANDOFF-FINDINGS.md] **klaravex.com: purge remaining "IT Experts Berlin" brand remnants.** Stale meta description on `/` ("Senior IT consultant… working exclusively in English" — on the German default page!), og:locale=en_US, JSON-LD LocalBusiness name "IT Experts Berlin" (contact pages), visible "Warum IT Experts Berlin" heading + "© 2026 Klaravex · IT Experts Berlin" footer, og image itexperts-berlin-og.png, old facebook/instagram links, og:site_name "…Freelance IT Consulting".
/home/anthony/klaravex/seo-ai-visibility-audit-2026-06-11.md:39:| 14 | **Stale itexperts-berlin metadata on klaravex.com**: og:site_name "Freelance IT Consulting", twitter:creator/site @ITExpertsBerlin, facebook publisher itexperts.berlin, twitter:image itexperts-berlin-og.png, meta description still "Senior IT consultant in Berlin… NIS2 compliance" (and uses the banned word). Google currently indexes .de with the OLD title "IT Consultant Berlin — … | IT Experts Berlin". | klaravex.com |
/home/anthony/klaravex/DECISIONS.md:120:Prospecting and freelance scoring depended on direct Anthropic SDK calls and began failing with 401 errors during partial credential rotation events. A single-provider dependency for LLM-driven scoring is a single point of failure for revenue-touching pipelines.
/home/anthony/klaravex/DECISIONS.md:126:- Improved availability for prospecting and freelance scoring pipelines.
/home/anthony/klaravex/DECISIONS.md:138:Approval workflows proliferated across six content streams (freelance bids, freelance matches, KB drafts, ops visibility, social publishing, dunning escalations). Each had its own surface, creating context-switching cost and inconsistent approval semantics.
/home/anthony/klaravex/SPEC.md:227:| `klaravex_freelance_matches` | T14.5 scoring output | 🟡 schema present, empty |
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:45:### 1.2 Freelancer Pipeline (`klaravex-freelancer-pipeline.json`)
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:47:**Purpose**: Platform scanning, bid strategy, and submission on Upwork/Freelancer.com  
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:51:P1: freelance-platform-scan-2h     →  app.tasks.freelance_tasks.run_platform_scan
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:52:P1: freelance-bid-strategy-30m     →  app.tasks.freelance_tasks.run_bid_strategy
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:53:P1: freelance-bid-submission-30m   →  app.tasks.freelance_tasks.run_bid_submission
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:56:**n8n Workflow**: `klaravex-freelancer-pipeline.json`  
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:57:**Endpoints**: `/run-freelance-scan`, `/run-bid-strategy`, `/run-bid-submission`
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:87:### 1.5 Socials Pipeline (`klaravex-socials-pipeline.json`)
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:99:**n8n Workflow**: `klaravex-socials-pipeline.json`  
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:140:    "freelance-scan": ["freelance-platform-scan-2h"],
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:141:    "bid-strategy": ["freelance-bid-strategy-30m"],
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:142:    "bid-submission": ["freelance-bid-submission-30m"],
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:167:    "freelance-platform-scan-2h": ("app.tasks.freelance_tasks.run_platform_scan", 7200, {}),
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:303:| 2 | freelance_bid_strategist | P1 | Analyzes projects, produces bid strategy |
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:304:| 3 | freelance_platform_client_converter | P1 | Converts platform messages to leads |
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:494:- [ ] **Freelancer**: Trigger `/run-freelance-scan` → verify opportunities logged
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:497:- [ ] **Socials**: Trigger `/run-social-drafts` → `/run-social-route` → `/run-brand-voice-check` → `/run-social-publish` → verify posts on LinkedIn/Twitter with Higgsfield visuals
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:536:| freelancer-pipeline | Scan | `/run-freelance-scan` | freelance-platform-scan-2h |
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:537:| freelancer-pipeline | Bid Strategy | `/run-bid-strategy` | freelance-bid-strategy-30m |
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:538:| freelancer-pipeline | Bid Submission | `/run-bid-submission` | freelance-bid-submission-30m |
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:545:| socials-pipeline | Drafts | `/run-social-drafts` | generate-us-social-drafts |
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:546:| socials-pipeline | Route | `/run-social-route` | route-qualified-social-posts |
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:547:| socials-pipeline | Brand Voice | `/run-brand-voice-check` | brand-voice-check |
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:548:| socials-pipeline | Publish | `/run-social-publish` | social-publish |
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:588:│   │   ├── freelance_tasks.py   ← Freelancer pipeline
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:608:│   ├── klaravex-freelancer-pipeline.json
/home/anthony/klaravex/KLARAVEX_PIPELINE_ARCHITECTURE.md:611:│   ├── klaravex-socials-pipeline.json
/home/anthony/klaravex/TOPOLOGY.html:129:  <text x="790" y="230" class="sm" text-anchor="middle">freelance_scout</text>
/home/anthony/klaravex/TOPOLOGY.html:291:    <li>freelance_scout</li>
/home/anthony/klaravex/COMPONENTS.md:71:| `freelance_watcher.py` | T14.5 — monitors freelance platforms for matching IT project bids |
/home/anthony/klaravex/orchestrator-core/config/tenants.yaml:4:# DE tenant here — US and German freelance are isolated into separate
/home/anthony/klaravex/go-to-market 2/upwork-profile.md:2:_Ready to paste. Create account at upwork.com → Sign up → I'm a Freelancer → then Agency._
/home/anthony/klaravex/go-to-market 2/upwork-profile.md:163:1. Go to upwork.com → click "Sign Up" → "I'm a freelancer"
/home/anthony/klaravex/PRD.md:78:### Delta 6 — Freelance watcher shipped (T14.5)
/home/anthony/klaravex/PRD.md:80:Fully implemented past Tier A scope. `infra/loki_handlers/freelance_bid.py`: 3-stage scout→score→submit pipeline across Freelancer.com + Freelancermap + manual email for Upwork/Guru/PPH. Claude/OpenRouter scoring, daily cap, skill pre-check, admin inbox report. Blocked on Anthony creds: `T14.14` (Freelancer.com token), `T14.15` (Freelancermap RSS), `T14.16` (ICP definition). Also blocked on `AC-VERIFY` gate (see §5.1).
/home/anthony/klaravex/PRD.md:88:`leads` table is the only populated table. `klaravex_freelance_matches`, `klaravex_kb_drafts`, `klaravex_kb_topics_covered`, `klaravex_tickets` (partially) — either not applied, empty, or not exercised. Migration debt to work down before T14.5 outbound + T14.27 KB writer can produce real business output.
/home/anthony/klaravex/PRD.md:147:**BRK-5: Freelance bid emails firing with no UI to action them (Phase 28)**
/home/anthony/klaravex/PRD.md:148:- Root cause: admin_inbox rendering removed the freelance cards but the `_send_manual_bid_email()` pipeline still runs for Upwork/Guru/PPH.
/home/anthony/klaravex/PRD.md:149:- Fix path not yet decided by Anthony: pause the pipeline vs. restore UI visibility. Do NOT autonomously choose — has revenue implications. Spec at `.loki/specs/2026-07-17-freelance-bid-notification-gap.md`.
/home/anthony/klaravex/PRD.md:325:- `klaravex_freelance_matches` — schema present, empty
/home/anthony/klaravex/PRD.md:425:Blocking gate: **AC-VERIFY** — 20-item verification checklist in `.loki/queue/awaiting-anthony-2026-07-13.json` (id `AC-VERIFY`). No outbound campaign (Google Ads, LinkedIn Ads, freelance bidding, social media publish, outreach sequences) may go live until GREEN. Per Anthony directive 2026-06-12T05:58: "do not send leads out if things are not working."
/home/anthony/klaravex/PRD.md:507:### 5.5 Freelance bidding (T14.5)
/home/anthony/klaravex/PRD.md:509:`infra/loki_handlers/freelance_bid.py` — fully implemented (obs 18650). Blocked on T14.14 (Freelancer.com token) + T14.15 (Freelancermap RSS URL) + T14.16 (ICP definition) + AC-VERIFY gate.
/home/anthony/klaravex/PRD.md:591:**Gate 10 — AC-VERIFY.** No outbound (Google Ads, LinkedIn, freelance, social, cold outreach) until all 20 items GREEN.
/home/anthony/klaravex/COMPARISON.md:4140: No junior gatekeepers 
/home/anthony/klaravex/test_freelancer_pipeline.py:3:Simple test script to verify the freelancer pipeline works correctly.
/home/anthony/klaravex/test_freelancer_pipeline.py:15:    freelance_min_fit_score = 55
/home/anthony/klaravex/site-relaunch/2026-06-07-live-deploy/previews/personal-site-design.html:889:        <p class="t-quote">I started using AI tools for my freelance work after my coaching session. Honestly saved me hours every week. Wish I'd done it sooner.</p>
/home/anthony/klaravex/drafts/4-impressum-dsgvo-disclosure-block.md:10:**Decided 2026-06-08.** klaravex.com operates under your German freelance/residency status. Implications now locked in below:
/home/anthony/klaravex/poc/wp-rebuild/01-kb-landing-NEW.html:290:      <p>Klara, our AI concierge, can help you right now — or route you to a senior engineer if it's complex. No call queue, no junior gatekeepers.</p>
/home/anthony/klaravex/verify_pipeline_config.py:3:Verification script to check freelancer pipeline configuration.
/home/anthony/klaravex/verify_pipeline_config.py:105:    print("=== Freelancer Pipeline Configuration Verification ===\n")
/home/anthony/klaravex/TOPOLOGY.md:171:| `freelance_scout` / `freelancermap_scout` | INSERT (loki_vault) | INSERT (note_submissions klaravex) | none | runs as Azure container | none | none | none | none | none |
/home/anthony/klaravex/TOPOLOGY.md:294:    ├─ Freelancer.com (`43mszfgio6aqwr4h6ydsvwpgem`)
/home/anthony/klaravex/TOPOLOGY.md:295:    ├─ Freelancermap (`725wp43zgok7lmfxgwymfqh6im`)
/home/anthony/klaravex/TOPOLOGY.md:336:5. **Env vars (re-verified 2026-08-16, supersedes 06-23 finding)**: `OPENROUTER_API_KEY` SET, `FREELANCER_API_TOKEN` + `FREELANCER_ACCESS_TOKEN` + `FREELANCER_OAUTH_TOKEN` SET (api+worker). `LINKEDIN_COMPANY_TOKEN` empty BUT non-issue — `services/social_publisher.py` falls back to the shared `LINKEDIN_PERSONAL_TOKEN` (07-19 Anthony directive). Still genuinely empty: `GOOGLE_API_KEY`, `FREELANCERMAP_RSS`.
/home/anthony/klaravex/scripts/watchdog/README.md:3:Host-cron on Hetzner USA (`hetzner-usa-watchdog`, Tailscale `100.66.236.56` / public `87.99.147.244`, 1P `52bk74s7stijglpdsnmz3u2q5u`) that catches silent worker pipeline failures. Discovered 2026-06-20 after a 9-day silent gap caused by a missing DB column (klaravex_freelance_projects.category — see migrations/).
/home/anthony/klaravex/scripts/watchdog/README.md:12:| freelance_projects | klaravex_freelance_projects | 2 days |
/home/anthony/klaravex/test_social_media_manager.py:15:    freelance_min_fit_score = 55
/home/anthony/klaravex/TOPOLOGY-v4.html:208:    <li>Misleading env-path text in a freelance-bidding failure email fixed (pointed at itexperts-berlin's env, corrected to klaravex's own).</li>
/home/anthony/klaravex/scripts/watchdog/system_health.py:55:    ("freelance_projects", "klaravex_freelance_projects", timedelta(days=2)),
/home/anthony/klaravex/CLAUDE.md:177:* **Strict Exclusions:** Defense, DIB, and CMMC/ITAR compliance are explicitly out of scope[cite: 1]. Maintain absolute separation between US LLC operations and German freelance advisory.
/home/anthony/klaravex/scripts/watchdog/watchdog.py:7:Pipelines: social_drafts (4d), freelance_projects (2d), prospected_leads (2d),
/home/anthony/klaravex/scripts/watchdog/watchdog.py:31:    ("freelance_projects", "klaravex_freelance_projects", timedelta(days=2)),
/home/anthony/klaravex/docs/architecture/ai-remote-session.md:26:- **Code-signing:** Required on both OSes or SmartScreen/Gatekeeper will block install for a 60+ year-old caller and the session dies on the spot.
/home/anthony/klaravex/docs/prd-growth-os.md:5:**Audience:** Engineering, CRO/Gatekeeper operators, exec escalations  
/home/anthony/klaravex/docs/prd-growth-os.md:23:Deliver an **all-in-one Growth OS** for the non-engineering revenue lifecycle: lead generation, socials, SEO/blog, knowledge base, backlinks, ads, freelance bids, gated publish prep, and accountability scorecards.
```

