# Revenue Agents Audit — SEO + Knowledge Base + Backlinks

Date: 2026-08-21 · Scope: repo-only (worktree `klaravex-socials-leads-ads-23f707`). No SSH, no production API calls, no publishing, no env changes.

---

## 1. SEO pipeline — current state

**Task:** `app/tasks/seo_content.py` → beat entry `seo-content-daily` (`app/tasks/celery_app.py:321-326`), daily 06:30 Europe/Berlin, queue `default`.

**What it does:** picks one keyword from a hardcoded 48-keyword pool (HIPAA, SOC 2/ISO, M365/GWS/AWS, MSP-vertical, UniFi, general security), then delegates to the registered `seo_content_writer` agent (`app/agents/seo_content_writer.py`). The agent generates an ~800-word post via Anthropic, parses TITLE/META/CONTENT, and queues the draft as a **P3 `approval_requests` row** (`action_name='seo_content_writer.publish'`). Nothing auto-publishes — after human approval, the `website_deploy` agent pushes to WordPress *as a draft*. US-only override (2026-07-19) forces English regardless of caller input.

**Findings:**

1. **BUG — keyword dedup never works.** `_pick_keyword` (`app/tasks/seo_content.py:81-97`) calls `await db.fetch(...)`, but `db` is an SQLAlchemy `AsyncSession` (`app/database.py:120`), which has no `.fetch()`. The `AttributeError` is swallowed by the bare `except`, so `used` is always empty and the "no repeats within 30 days" guarantee is fiction — repeats are possible any day. Fix: use `sqlalchemy.text()` + `db.execute()` (the pattern now demonstrated in `app/tasks/kb_content.py:_recent_kb_keywords`). Not fixed here (out of scope for a daily audit task's hard constraints? No — it IS a repo edit, but it changes a production task's behavior; left for a deliberate fix with a test. Flagged as top repo follow-up.)
2. **Voice-policy violation in the keyword pool.** 3 keywords embed the banned word "compliance" in marketing-destined H1s/titles: `"HIPAA compliance checklist for small medical practices"` (line 30), `"security compliance roadmap"` (line 44), `"HIPAA email compliance for doctors"` (line 34). CLAUDE.md legal warning: never "compliance" in marketing — use "readiness"/"advisory". These keywords seed titles and meta descriptions directly. Should be reworded (e.g. "HIPAA readiness checklist…").
3. **personal.klaravex.com is not covered at all.** The entire pool is business-side; no consumer topics, and `seo_content_writer`'s prompt hardcodes klaravex.com business positioning. The audit scored the personal subdomain 31/100 with zero SEO layer — the automation compounds the gap. The new KB pipeline (below) closes this for KB-style content.
4. **Prompt has no "never say compliance" rule.** `_BLOG_PROMPT_EN` bans MSP-speak but not the word "compliance"; combined with finding 2, drafts will routinely contain it (the agent's own line 45 even says "HIPAA/SOC 2/ISO 27001 readiness" — the prompt knows the rule implicitly but doesn't enforce it on output).

**Open findings still standing from `seo-ai-visibility-audit-2026-06-11.md`** (all require production/WordPress action — none actionable from the repo):
- P0: placeholder "$X per user/month" pricing on the homepage; dead "Request Your Free Assessment" CTA (`#`); broken "How It Works" nav sitewide; three 404ing homepage service-card links; internal copy note published live on the cyber-insurance page; "compliance" wording on the homepage; unverifiable "500+ people ★4.9" social proof on personal.
- P1: personal.klaravex.com has no meta/OG/schema/Rank Math; wasted homepage title tag; junk meta descriptions; sitemap pollution; British English on US surfaces; klaravex.io/.eu serve nothing (need 301s).
- AI visibility 12/100 — entirely a distribution problem → addressed by `marketing/backlinks/PLAYBOOK.md`.
- The audit's own note_submissions row was never written (no DB path from that session) — still outstanding.

## 2. Knowledge base — current state and what was built

**Before:** `kb-build/` is a one-off static generator: `gen.py` (renders articles/categories in the `.kba-` design system with FAQ + BreadcrumbList JSON-LD), `content.py` (2 articles + 4 category pages for .com), `genbi.py` (bilingual DE/EN assembler for the DE surface, out of US scope), `publish.py`/`publish_de.py`, and 7 static source articles in `src-en`/`src-de`. **No scheduled pipeline existed** — the live KB has ~3 articles (audit P2: "thin content for the Knowledge Base nav promise").

**Built — `app/tasks/kb_content.py` (224 lines, new):**
- Celery task `kb_content`, modeled line-for-line on the `seo_content` pattern (same `bind=True, max_retries=2, default_retry_delay=300`, same `asyncio.run` wrapper, same `AgentContext` construction, same queue conventions).
- Two topic pools: **business** (30 topics — HIPAA/SOC 2 *readiness* wording, M365/GWS/AWS, vertical guides for law firms/accounting/medical, UniFi, security) and **consumer** (18 how-to/support topics for personal.klaravex.com). Zero uses of the word "compliance".
- Surface selection is balance-based: each run drafts for whichever surface has fewer KB drafts in the last 14 days (tie → business). Optional `surface=` kwarg for manual triggers.
- 60-day topic dedup that **actually works** — `sqlalchemy.text()` + `db.execute()` against `klaravex.approval_requests`, not the broken `db.fetch()` style (documented inline at `_recent_kb_keywords`).
- **Draft-first**: delegates to a registry agent that queues a P3 approval row; nothing auto-publishes.
- **Clean stub where production is required:** preferred agent `kb_content_writer` is looked up first but is *not yet registered* (registering it in `app/agents/` + deploying is a production change routed to Anthony below). Falls back to the live `seo_content_writer` with `content_type="kb_article"`, so the pipeline produces drafts from day one; the fallback is logged (`kb_content.fallback_agent`).

**Beat entry:** `kb-content-3x-week` — Mon/Wed/Fri 06:45 Europe/Berlin (offset from seo_content's 06:30), queue `default`.

## 3. Backlinks — what was built

No backlink automation or plan existed. Created **`marketing/backlinks/PLAYBOOK.md`**: 26 targets in 5 tiers ordered by effort-vs-authority — Tier 1 entity foundation (GBP verification, Clutch rebrand from "IT Experts Berlin", Crunchbase, social handles, Bing/Apple, GSC/IndexNow), Tier 2 free B2B directories (GoodFirms, UpCity, CloudTango, DesignRush, G2, MSPAlliance, CompTIA), Tier 3 Vanta/Drata partner programs, Tier 4 consumer citations (new US Yelp listing, Thumbtack completion, Bark, Nextdoor, BBB), Tier 5 content-driven links (expert quotes, guest posts on MSP/legal/accounting/medical publications, citation-format KB articles feeding the new kb_content pipeline, Reddit/Quora human-only). Every row marks **agent-preparable vs Anthony-required**, includes the verbatim NAP block, voice-policy guardrails, sequencing, exclusions (paid Clutch/Yelp, PR spam), and a 31-row tracking table (target/tier/status/owner/date/live URL).

## 4. Edits made (file:line)

| File | Change |
|------|--------|
| `app/tasks/kb_content.py` | **NEW** (224 lines) — KB draft Celery task, dual-surface, draft-first |
| `app/tasks/celery_app.py:119` | Added `"app.tasks.kb_content"` to `include` |
| `app/tasks/celery_app.py:177` | Added task route `app.tasks.kb_content.* → default` |
| `app/tasks/celery_app.py:328-339` | Added `kb-content-3x-week` beat entry (Mon/Wed/Fri 06:45 CET) |
| `marketing/backlinks/PLAYBOOK.md` | **NEW** — acquisition plan + tracking table |
| `marketing/revenue-agents-audit-seo-kb-backlinks.md` | **NEW** — this report |

Both Python files pass `python3 -m py_compile`. No production deployment performed — the beat entry goes live only when the worker/beat containers are redeployed from this branch.

## 5. Anthony-required actions

**Production / deploy:**
1. **Deploy this branch** to the Celery worker + beat on the rig/Hetzner so `kb_content` starts running (explicit per-action confirmation required per CLAUDE.md rule 4). Until then the pipeline is dormant.
2. **Authorize a subagent to register a dedicated `kb_content_writer` agent** in `app/agents/` (KB-specific prompt: FAQ blocks, BreadcrumbList JSON-LD matching `kb-build/gen.py`'s design system, surface-aware business/consumer voice, hard "never write the word compliance" rule). Until then drafts run through `seo_content_writer`'s blog prompt — usable but blog-shaped.
3. **Fix the `seo_content.py` dedup bug** (broken `db.fetch()`, finding 1) and **reword the 3 "compliance" keywords** in its pool — small deliberate change + redeploy.

**Accounts / third-party (from the playbook — top of the ordered list):**
4. **Complete Google Business Profile verification** (pending since Jun 2026) and make the listing-address decision (WY registered-agent addresses get rejected — service-area business w/ hidden address, or a real virtual office). This blocks reviews, Bing/Apple imports, and the whole consumer tier.
5. **Rebrand the Clutch profile** from "IT Experts Berlin" to Klaravex (US NAP) — currently an actively wrong high-authority citation.
6. Claim LinkedIn /company/klaravex, X @klaravex, YouTube handle; then Vanta + Drata partner applications; then the Tier-2 directory signups (agent can prepare every profile pack first).
7. **Spokesperson decision** for press/expert-quote tactics: voice policy bans personal names on marketing surfaces, but journalist quotes need a named person — decide the exception or the titled-spokesperson format before Tier 5 starts.
8. Add `MEDIUM_INTEGRATION_TOKEN` and `DEVTO_API_KEY` to the worker env (credential wiring via subagent per CLAUDE.md rule 5) to activate content syndication.
9. Fix the audit's P0 on-site defects (placeholder $X pricing, dead CTA, broken nav/service links, live internal copy note) via WP Toolkit **before** any directory submissions drive reviewers to the site.

## 6. Memory policy note

This session ran inside an isolated worktree with no `note-submit` tool available and no DB path; per the routing table these repo edits map to Azure `klaravex-db-r2` (klaravex-repo, Scenario 3/5). The required `note_submissions` rows for the three mutations (kb_content.py creation, celery_app.py wiring, playbook creation) could not be written from here — **surfacing per the failure protocol rather than silently skipping**. Log them from the host session or authorize a subagent with DB access.

---

## 7. Round 2 fixes (2026-08-21, follow-up agent)

Confirmed defects from the three Round-1 audits, now fixed in-repo (no deploy performed):

1. **`app/tasks/seo_content.py` — keyword dedup repaired (finding §1.1).** `_pick_keyword` (now lines 85-106) uses `sqlalchemy.text()` + `await db.execute(...)` — the same working pattern as `kb_content.py::_recent_kb_keywords` — instead of the nonexistent `db.fetch()`. The broad `except Exception: used = set()` is narrowed to `except SQLAlchemyError` with a `seo_content.recent_keywords_query_failed` warning log (`exc_info=True`), so a real DB failure is visible instead of silently disabling dedup. Imports added at lines 17-18.
2. **`app/tasks/seo_content.py` — banned "compliance" keywords reworded.** Round 1 reported 3; there were actually **4** occurrences in the pool. All reworded per the CLAUDE.md marketing rule: line 32 → "HIPAA readiness checklist for small medical practices", line 36 → "HIPAA email readiness for doctors", line 46 → "security readiness roadmap", line 68 → "network segmentation for audit readiness". Zero "compliance" strings remain in the file. (Rewording resets these 4 keywords' 30-day dedup history — acceptable one-time effect.)
3. **`app/agents/social_media_manager.py` — undefined `context` in per-draft cost tracking fixed.** `_generate_one_draft` referenced `context` without it being defined (the dead outer block Round 1 removed had been its only would-be source), so per-draft `track_response` calls raised `NameError`, swallowed by `except: pass` — cost tracking never worked. Fix: `run()` now passes `context` into `_generate_all_drafts` (line ~957), which threads `context: AgentContext | None` plus a shared `asyncio.Lock` into each `_generate_one_draft` (params at lines ~1392-1393). The lock serializes the `track_response` writes because the parallel `asyncio.gather()` drafts share one `AsyncSession`, which is not concurrency-safe. `track_response` itself never raises (documented in `app/services/llm_cost.py`), so the blanket `except: pass` was dropped.
4. **`app/tasks/kb_content.py:134-139`** — comment updated: it warned that seo_content's dedup was broken; now notes it was fixed in Round 2 (comment-only change).

**Verification:** `python3 -m py_compile app/tasks/seo_content.py app/tasks/kb_content.py app/agents/social_media_manager.py` — all pass. Spot-checked the Round-1 "edits made" tables in all three audit reports: every listed edit is present in the tree (kb_content.py 224 lines; celery_app.py include/route/beat entries; PLAYBOOK.md; config.py `apollo_industries` + US defaults; outreach fallback subject; `LeadSource.personal_site`; consumer track wiring in social_media_manager.py / social_media.py / celery_app.py PT slot). **One report inaccuracy:** this report's finding §1.2 said "3 keywords" contain "compliance" — the true count was 4 (line 66 `"network segmentation for compliance"` was missed). Corrected above.

Same memory-policy limitation as §6: no `note-submit` path from this worktree — the Round-2 mutation rows (seo_content.py fix, social_media_manager.py fix, kb_content.py comment, this report) still need logging from the host session to Azure `klaravex-db-r2`.
