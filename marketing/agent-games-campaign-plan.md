# Campaign Brief — The Klaravex AI Marketing Race

**Brand surface:** klaravex.com (US) · **Owner:** Anthony Stewart · **v2 (rewritten 2026-06-10 to match built system)** · Supersedes v1 "Agent Games" draft.

**Ground truth (verified against `infra/migrations/015_marketing_competition.sql` + live https://portal.klaravex.com/race):**
- **2 teams:** Alpha (aggressive growth, paid-acquisition bias) vs Beta (patient, ROI/organic bias) — personas seeded in DB
- **Metric:** most **billed revenue** from attributed Klaravex client signups in 30 days (attribution via `attribution_team` on `klaravex_clients`, UTM paths `/?t=alpha` / `/?t=beta`)
- **Money:** $1,000/team on **Mercury virtual cards**, $50/day spend cap, webhook-tracked transactions
- **Governance:** approval-gated actions (`approval_required`/`approved_by`), guardrail-stop run status
- **Status:** **soft_launch is LIVE** — scoreboard at portal.klaravex.com/race, auto-refresh 60s, agents already acting
- Both consumer (personal.klaravex.com) and business funnels are in scope as race targets

**Strategic frame:** The asset already exists. The campaign's job is **distribution + conversion**: drive the right audience to /race, capture them, and convert race-watchers into Klaravex clients. The meta-story writes itself — *the marketing for the race is itself a race between AI marketers.*

---

## 1. Objectives

**Primary (SMART):** 10 Directive-tier discovery calls + measurable attributed revenue on the scoreboard (even one real client per team makes the stunt's thesis) within 45 days of public launch.
**Secondary:** 500 email subscribers to a weekly race digest · 1 earned-media pickup · own the "AI-native MSP" positioning before copycats.

**Audience, messaging pillars, and channel rationale carry over from v1 unchanged** (US SMB ops decision-makers in healthcare/legal/financial as buyers; HN/X/Reddit as amplifiers; governance-not-hype as the core message). What changes below is everything that touched format and mechanics.

---

## 2. The story (corrected)

Core message: *"Two AI marketing teams with opposite philosophies, real company cards, and hard spend caps are competing to land actual paying clients — in public. The same governed autonomy runs our clients' IT and security."*

- **Alpha vs Beta rivalry is the retention hook.** Opposite personalities = audience picks sides. Run polls, "who's winning and why" commentary, head-to-head weekly recaps.
- **Revenue is the honest metric.** Audience growth is vanity; "billed revenue" with CAC on the board is the credibility play no one else is doing.
- **Approval gates are a feature, not a footnote.** Public copy currently says "full autonomy" — change to "autonomous within governance: budgets, daily caps, approval gates on spend, every action logged." That's more accurate AND more persuasive to a security-anxious buyer. It's also the bridge to Directive tier.

---

## 3. Launch sequence (soft launch already running)

| Phase | When | Action |
|------|------|--------|
| **Soft launch (now)** | T-3 → T-0 | Fix /race conversion gaps (§4). Soak-test agent runs + scoreboard refresh. Teaser post on LinkedIn: "Something's been running quietly at portal.klaravex.com/race…" — soft-launch state is itself a teaser asset. |
| **Public launch** | T-0 | Flip teams to `live` (full $1,000 budgets visible). LinkedIn launch post + X thread (see launch content doc v2). Day-1 standings screenshot. |
| **Week 1** | | Team intro posts (Alpha day 2, Beta day 3 — their "manifestos," AI-labeled). Show HN / r/msp once first real spend + actions are on the board. Digest #1. |
| **Week 2** | | First setback story + governance post ("the spend I refused to approve"). Press pitches (angle: real money + revenue attribution + approval-gate governance — no one else publishes CAC for AI agents). Digest #2. |
| **Week 3** | | Mid-race deep dive w/ spend + CAC analysis (blog, SEO asset). Audience poll on a real pending approval. Retargeting on (pixel from day 1). Digest #3 + first explicit Directive CTA. |
| **Week 4** | | Daily countdown standings. Finale: winner, full P&L per team. Digest #4. |
| **Week 5** | | Gated post-mortem: **"Two AI marketers, $2,000, 30 days: full P&L, every approval, every dollar"** — THE lead magnet. Conversion post + 1:1 outreach to ICP-matching subscribers. Readiness engagements signable (E&O bound 2026-06-10). |

---

## 4. /race page conversion fixes (pre-launch punch list)

The page exists and looks good. It currently captures **zero** value from a visit. Fix before driving traffic:

1. **Email capture block** — "Get the weekly race digest: every move, every dollar, the approvals I refused." This is the campaign's compounding asset; without it every visitor bounces forever. (P0)
2. **Budget display bug/ambiguity** — cards show "Spent $0 / $100" while the headline promises $1,000. If $100 is the soft-launch cap, label it ("soft-launch cap — full $1,000 unlocks at public launch"); otherwise fix. Sharp-eyed HN readers will screenshot this. (P0)
3. **"Full autonomy" → governed-autonomy wording** per §2. (P0)
4. **Rules/disclosure link** — short public rulebook: spend rules, approval gates, AI-labeling pledge, failure policy. Trust infrastructure for press. (P1)
5. **UTM on outbound links** — race-page links to klaravex.com / personal.klaravex.com should carry `utm_source=race` so race-driven conversions are measurable (separate from team attribution). (P1)
6. **Directive bridge CTA** — one section: "This governance model runs our clients' IT + security → book a 30-min briefing" + Calendly. (P1)
7. **"89% of our support load"** — keep only if substantiable from operating history; otherwise soften. Same FTC-substantiation discipline as the main site. (P1)

---

## 5. Metrics

| KPI | Target | Via |
|-----|--------|-----|
| Attributed revenue on scoreboard | >$0 per team (thesis proof) | `klaravex_clients.attribution_team` |
| Directive discovery calls | 10 in 45 days | Calendly + UTM |
| Digest subscribers / ICP-qualified | 500 / 100 | Form + weekly review |
| /race unique visitors | 5,000 | Analytics |
| Earned media | 1+ | Manual |
| Post-mortem downloads | 200 | Gated form |

Watch ICP ratio weekly; re-aim copy mid-flight if amplifier traffic isn't producing buyer signups.

---

## 6. Risks (delta from v1)

1. **Race shows $0 revenue for weeks.** Likely — sales cycles are longer than 30 days for B2B. Mitigate: scoreboard celebrates leading indicators too (booked calls, signups, pipeline) with revenue as the win condition; consumer side (personal.klaravex.com) can land faster wins. Frame honestly: "if neither team lands a client, that's a finding, and we publish it."
2. **Meta/LinkedIn ToS on agent-run campaigns.** Approval-gated proposals + human-owned ad accounts + human final execution of platform actions. The schema supports this; the public rulebook must state it.
3. **Mercury card misuse/runaway spend.** $50/day caps + category approvals + webhook monitoring already built. Add an alert on any `declined`/unusual MCC.
4. **Live-feed leakage.** Agents researching "potential clients" publicly — ensure the feed never displays prospect names/PII. Generic action labels only (current feed is fine; keep it that way by policy).
5. **Wrong-audience virality / claim substantiation / copycats** — unchanged from v1.

E&O is bound (2026-06-10) — readiness engagements signable. "Compliance" wording violations on klaravex.com main site still need remediation before launch traffic (separate WP fix).

---

## 7. Next steps

1. Apply /race punch list §4 (P0 items minimum) — requires portal deploy authorization.
2. Fix main-site "compliance" wording + "$X/user/month" placeholder — WP edit authorization.
3. Set T-0 date; teaser post at T-3.
4. Launch content pack v2 (separate doc) — ready to post.
