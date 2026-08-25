# Revenue Agents Audit — Socials + Blogs Streams

Date: 2026-08-21 · Scope: social_media, linkedin_drafts_sweep, social_report,
seo_content, beat_trigger, celery beat, infra/cron content pipelines, n8n
social workflows. Repo-only audit; no production systems touched.

---

## 1. Current cadence map (as of this audit, including edits below)

### Celery beat (`app/tasks/celery_app.py`, timezone Europe/Berlin)

| Beat entry | Task | Schedule | Status |
|---|---|---|---|
| `generate-social-drafts-et` | `social_media.generate_weekly_social_drafts` (market=us, business track) | daily 15:00 Berlin ≈ 09:00 ET | LIVE — P3 approval queue |
| `generate-social-drafts-pt` | same task, **market=us, track=consumer** (NEW, this audit) | daily 18:00 Berlin ≈ 09:00 PT | LIVE — P3 approval queue |
| `route-qualified-social-posts` | sweeps won leads → social bundle | every 15 min | LIVE (no won leads → no-op) |
| `seo-content-daily` | `seo_content` → SeoContentWriterAgent → klaravex.com WP draft | daily 06:30 | LIVE — P3 approval |
| `social-report-daily` | `social_report.send_social_report` email digest | daily 08:00 | LIVE via beat (the n8n trigger name `social-report-daily` is in DISABLED_TRIGGERS, but the beat entry fires it directly — see gap G6) |
| `linkedin-drafts-sweep-daily` | LinkedIn outreach drafts for 14-day non-repliers | daily 12:00 | LIVE |

### beat_trigger.py (n8n → HTTP trigger path)

- `generate-eu-social-drafts` / `generate-us-social-drafts`: in
  `DISABLED_TRIGGERS` (2026-07-19) — n8n still POSTs (workflows in
  `loki-agents/n8n-workflows/*.json` are `active: true`, cron `0 9 * * 1-5`
  and `0 15 * * 1-5`) but the handler returns `skipped/disabled`. Celery beat
  is the single source of truth. Correct.
- `social-report-daily`, `generate-report-daily`, `pipeline-reporter-weekly`,
  weekly reports: disabled at trigger gate (business-stage rationale) — but
  several have live celery-beat entries that bypass the gate (G6).
- EU market path: `generate_weekly_social_drafts` hard-forces `market="us"`
  (SEC4 override) regardless of caller. Confirmed intact.

### infra/cron (rig, outside Celery)

| Cron | What | Cadence |
|---|---|---|
| `daily_seo_blog.py` | 2 auto-published posts/day: klaravex.com (business pool, 30 topics) + **personal.klaravex.com (consumer pool, 30 topics)** — AI voice/quality gate, no human approval | daily 06:00 |
| `backlink_builder.py` | HARO drafts + **Medium/dev.to syndication** of last-48h gate-passed blog posts + web-2.0 profiles | daily 07:00 |
| `social-generate-now.py` / `social_drafts_weekly.sh` | manual/on-demand triggers of the same draft task | on demand |

So: blogs already had a consumer track (daily_seo_blog). **Social did not** —
that was the gap; now closed (see §3).

---

## 2. Gap assessment

**G1 — personal.klaravex.com had no social content track.** The 2x/day US
social cadence generated only B2B content (LinkedIn/Twitter/FB/Reddit,
klaravex.com CTA). Fixed in-repo (§3): consumer topic strategist prompt,
consumer platform set (facebook/instagram/tiktok/reddit), consumer fallback
topics, `track` kwarg, and the PT beat slot now carries the consumer track.
Daily SEO consumer drafts: **no change needed** — `infra/cron/daily_seo_blog.py`
already publishes one consumer post/day to personal.klaravex.com. Deliberately
did NOT add consumer keywords to `app/tasks/seo_content.py`, because that
task's publish path (`website_deploy`) targets the klaravex.com WordPress
only — consumer keywords there would publish consumer posts to the B2B site.

**G2 — Medium / dev.to syndication.** Code path EXISTS and is live-ready:
`infra/cron/backlink_builder.py`.
- `MEDIUM_INTEGRATION_TOKEN` → read at `backlink_builder.py:38`; used for
  api.medium.com posting with canonical URL. Syndicates BOTH business and
  consumer (`personal`) posts.
- `DEVTO_API_KEY` → read at `backlink_builder.py:40`; business posts only
  (consumer posts intentionally excluded from dev.to).
- Both env vars belong in **`/opt/klaravex/worker/.env` on the rig** — that is
  what `backlink_builder.sh:6` sources before exec'ing the Python. Without
  them the syndication steps silently skip (guarded `if MEDIUM_TOKEN` /
  `if DEVTO_API_KEY`). No repo change needed; only the two tokens.
- Caveat for Anthony: Medium deprecated its public API for new integration
  tokens in 2023-2025 — verify a token can still be minted from the Medium
  account settings; if not, syndication needs an alternative (manual import
  URL flow or a headless-publish approach).

**G3 — Voice-policy violations found and fixed** (§3): stale EU defaults in
`CampaignBrief.from_input` (audience "across Germany and the EU", region
"Germany / EU") leaked into every prompt's CAMPAIGN CONTEXT block for any
caller that didn't pass a region — including `route_qualified_social_posts`.
Agent `description` also said "SMBs across Germany and the EU". Fixed to US.

**G4 — Voice-policy: compliant surfaces (no change).**
- All 8 `PLATFORM_PROMPTS` + topic generator: explicit bans on personal
  names, "Loki", first-person singular, infra vendors; concrete-numbers rule
  enforced via `KLARAVEX_REAL_STATS` approved-stats block; CTA required.
- `seo_content_writer.py`, `daily_seo_blog.py` WRITER_SYSTEM, and
  `backlink_builder.py` HARO prompt all carry the voice rules.
- Reddit prompt deliberately permits "I"/"our team" framing (documented
  in-code as the one exception — "we" reads as PR on Reddit). Left as-is;
  it is a deliberate, annotated product decision. Flagged for Anthony to
  ratify (§4).

**G5 — Pricing inconsistency (NOT fixed — needs Anthony ruling).**
`KLARAVEX_REAL_STATS` in `social_media_manager.py` quotes Foundation
$100 / Assurance $165 / Directive $250 per user/mo. Project CLAUDE.md says
$49 / $79 / $129; global CLAUDE.md says ~$75–100 / ~$100–150 / ~$150–250;
`marketing/pricing-proposal-2026-07-26.md` exists. Every social draft quotes
whatever is in this dict. Did not change numbers without a ruling.

**G6 — Scheduler double-bookkeeping.** `DISABLED_TRIGGERS` gates the n8n
path only; `social-report-daily`, `generate-report-daily` (etc.) still fire
from celery beat directly. If the DISABLED_TRIGGERS business-stage rationale
("premature reporting") is meant to hold, the beat entries also need gating;
if not, the DISABLED_TRIGGERS comment is stale. Left untouched — ambiguous.

**G7 — Latent code issues (noted, one fixed).**
- Fixed: `generate_platform_topics` contained a cost-tracking block
  referencing `context`/`self` inside a `@classmethod` — a NameError silently
  swallowed by `except Exception: pass` on every run. Removed during the
  refactor to `_run_topic_generation`.
- Not fixed (same pattern): `_generate_one_draft` (social_media_manager.py,
  ~line 1345 post-edit) also calls `track_response(context.db, ...)` with no
  `context` in scope — LLM cost tracking for per-platform draft calls has
  never recorded. Needs a real fix (thread context through), not a drive-by.
- `social_report.py` `platform_labels` is referenced in the plain-text branch
  outside its defining scope when `total_posts == 0` path is skipped
  (annotated `# type: ignore[name-defined]`) — works today, fragile.

---

## 3. Edits made (file:line, post-edit line numbers approximate)

| File | Change |
|---|---|
| `app/agents/social_media_manager.py:790` | Agent description: "SMBs across Germany and the EU" → US business track + consumer track wording |
| `app/agents/social_media_manager.py:756,762` | `CampaignBrief.from_input` defaults: audience → "across the United States", region → "United States" |
| `app/agents/social_media_manager.py:365,428,541` | twitter/facebook/tiktok prompt CTA lines now allow personal.klaravex.com when campaign context targets consumers |
| `app/agents/social_media_manager.py:713–800` (new) | Consumer track: `_CONSUMER_PLATFORMS`, `_TOPIC_GENERATOR_PROMPT_CONSUMER` (5 consumer pillars: scam defense, privacy reset, home tech, family IT desk, AI for regular people; full voice-policy block), `_FALLBACK_TOPICS_CONSUMER` |
| `app/agents/social_media_manager.py:generate_platform_topics` | New `track: str = "business"` param; consumer branch; shared LLM/parse/fallback extracted to `_run_topic_generation`; dead broken cost-tracking block removed |
| `app/tasks/social_media.py:6–16` | Module docstring cadence header corrected (beat is source of truth, ET=business / PT=consumer) |
| `app/tasks/social_media.py:generate_weekly_social_drafts` | New `track` kwarg (validated, defaults business), passed through to `_generate_weekly_drafts` |
| `app/tasks/social_media.py:_generate_weekly_drafts` | Passes `track` to topic generation; consumer track injects campaign-brief fields (consumer audience, personal.klaravex.com CTA) into the agent payload |
| `app/tasks/celery_app.py:generate-social-drafts-pt` | PT slot kwargs → `{"market": "us", "track": "consumer"}` with comment; ET slot unchanged (business). Keeps exactly 2x/day. Revert = delete the `track` kwarg |
| `marketing/revenue-agents-audit-socials-blogs.md` | This report |

All edited Python files pass `py_compile`; consumer prompt `.format()`
verified against its placeholders. No schedule count changed; everything
still lands in the existing P3 approval queue — nothing auto-publishes.

Note: per the repo memory policy, the `note_submissions` rows for these
repo edits (route: Azure klaravex-db, klaravex.com surface) must be written
by the host session — this audit ran under a no-production-writes constraint.

---

## 4. Anthony-required actions (ordered)

1. **Ratify or revert the PT-slot consumer track** (`celery_app.py`,
   `generate-social-drafts-pt`). As shipped: 09:00 ET = business post,
   09:00 PT = consumer post (2x/day total, unchanged volume). Alternative:
   keep both slots business and add a third consumer slot — one-line change,
   but breaks the "exactly 2x/day" directive, so it needs your call.
2. **Resolve the pricing single-source-of-truth conflict** (G5):
   `KLARAVEX_REAL_STATS` ($100/$165/$250) vs project CLAUDE.md ($49/$79/$129)
   vs pricing-proposal-2026-07-26.md. Social posts quote these numbers daily.
3. **Mint and deploy syndication tokens** (production action, out of repo
   scope): add `MEDIUM_INTEGRATION_TOKEN` and `DEVTO_API_KEY` to
   `/opt/klaravex/worker/.env` on the rig (sourced by
   `infra/cron/backlink_builder.sh`). First verify Medium still issues
   integration tokens (G2 caveat); dev.to API keys are freely available in
   dev.to settings.
4. **Decide on the reporting-task double-gate** (G6): either add
   `social-report-daily` / `generate-report-daily` gating to celery beat to
   match DISABLED_TRIGGERS intent, or update the DISABLED_TRIGGERS comment —
   currently the two schedulers disagree about whether these should run.
5. **Ratify the Reddit first-person exception** in the reddit platform
   prompt (documented in-code; conflicts with the letter of the global voice
   policy, deliberate per platform culture) — and, separately, approve a
   proper fix for the dead per-draft LLM cost tracking in
   `_generate_one_draft` (G7).
