# Klaravex pipeline watchdog

Host-cron on Hetzner USA (`hetzner-usa-watchdog`, Tailscale `100.66.236.56` / public `87.99.147.244`, 1P `52bk74s7stijglpdsnmz3u2q5u`) that catches silent worker pipeline failures. Discovered 2026-06-20 after a 9-day silent gap caused by a missing DB column (klaravex_freelance_projects.category — see migrations/).

> **Note:** prior versions of this README pointed at Hetzner CX22 `178.105.84.32` — that host is read-only since the 2026-07-05/06 Azure migration and 2026-07-01/02 rig+USA HA cutover. See [`../../runbooks/rig-usa-ha-stack-2026-07-01.md`](../../runbooks/rig-usa-ha-stack-2026-07-01.md).

## Pipelines watched

| Pipeline | Table | Staleness threshold |
|---|---|---|
| social_drafts | klaravex_social_drafts | 4 days |
| freelance_projects | klaravex_freelance_projects | 2 days |
| prospected_leads | klaravex_prospected_leads | 2 days |
| outreach_approvals | klaravex_outreach_approvals | 2 days |
| marketing_actions | klaravex_marketing_actions | 2 days |
| tickets | klaravex_tickets | 14 days |

## Files on Hetzner

- `/opt/klaravex-watchdog/watchdog.py` — the script (this file)
- `/opt/klaravex-watchdog/env` — mode 600, contains DB pass + VAPI_SHARED_SECRET
- `/opt/klaravex-watchdog/run.sh` — wrapper that loads env + redirects log
- `/var/log/klaravex-watchdog.log` — append-only error log (success path is silent)

## Cron

```
30 9 * * * /opt/klaravex-watchdog/run.sh
```

09:30 UTC = 11:30 CET — runs after the worker's prospect-leads-daily
(08:00 CET) + social-drafter (09:00 CET) had a chance to write.

## Alert path

POST to `https://api.klaravex.com/api/v1/vapi/escalate_to_anthony` with
the `x-vapi-secret` header. The handler sends Telegram + email + optionally
bridges a call. The watchdog uses severity=high for stale pipelines and
severity=normal for the weekly OK heartbeat (Mondays AM only).

## Promote to proper task

This was built as a host-cron because the worker repo on Hetzner isn't a
git repo and the worker image is baked from elsewhere. Proper home: add
`pipeline_watchdog` as a Celery task in `app/tasks/pipeline_watchdog.py`,
schedule it in `beat_schedule`, retire the cron.

---

## system_health.py — comprehensive 4-hourly check (added 2026-06-20)

`/opt/klaravex-watchdog/system_health.py` extends the original pipeline
watchdog with 4 dimensions:

1. **EXTERNAL** — Twilio, Stripe, Microsoft Graph, OpenAI, Resend, Vapi, Atera, Telegram bot
2. **SURFACES** — klaravex.com, klaravex.io, api/healthz, /admin/, chat endpoints
3. **VAPI** — phone-number assignment (catches `call.start.error-get-assistant` outages)
4. **PIPELINES** — DB-table staleness (the original 6 checks)

Cron: `0 */4 * * *` (every 4 hours).

Each run aggregates all issues into a SINGLE Telegram + email escalation
via `escalate_to_anthony`. Weekly green heartbeat on Mondays.

User-Agent header is set so the probes don't trip Cloudflare rule 1010
(several SaaS APIs were silently 403ing the watchdog otherwise).

### First-run findings (2026-06-20)

9 issues confirmed during the all-hands audit:

- `atera` returns 401 — API key may have rotated
- `telegram_bot` missing — TELEGRAM_BOT_TOKEN not set on Container App; all escalations are email-only
- `klaravex.io` returns HTML 200 instead of 301 — Plesk forwarding uses HTML redirect, not server-side
- `/api/v1/chat/start` returns 404 — session-init route does not exist; widget limps via fallback to /message
- Main Line +14243486010 has no assistantId — staging line +13237609918 has triage_en assigned for testing
- 3 pipelines 8d+ stale despite manual reruns succeeding (suspect rows landing in different tables than queried)
- `klaravex_prospected_leads` is lifetime empty

