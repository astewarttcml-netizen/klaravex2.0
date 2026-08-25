# Decisions & Inputs Needed From Anthony

**As of 2026-06-23.** Everything that could be executed autonomously is done (see `marketing/`). These items genuinely require your call before the work can go further. Ordered by leverage.

---

## 1. MDR delivery model — the highest-leverage decision
**From:** build-vs-buy memo §4 / §9 Q1.
**The call:** For the "24/7 detection and response" layer of Directive, do you want **tool-consolidation (Coro)** or **human-SOC depth (Huntress / Blackpoint)**?
**Why it gates everything:** The homepage and all three vCISO pages promise "someone is watching and will act." That promise is an SLA/liability commitment in regulated verticals. **Do not publish any "24/7" claim until this is decided.** A solo operator cannot *be* the response.

## 2. Readiness/vCISO platform — approve a pilot
**From:** build-vs-buy memo §3 / §8.
**The call:** Approve a **one-client Cynomi pilot** before any annual commitment? (Recommended.) Pilot validates real price, portfolio-view limits, HIPAA/FTC depth, and white-label.
**Needs you because:** it's spend + a vendor relationship. I can prep the evaluation criteria and demo questions; I can't sign or quote.

## 3. Homepage repositioning — approve the thesis
**From:** `homepage-repositioning-US-draft.md`.
**The call:** Adopt / adjust / reject this thesis: *"Security and compliance readiness, delivered — not a box of tools you run alone."* Copy follows from the thesis; approve the direction first.
**Needs you because:** it resets your core public positioning.

## 4. Public pricing-tier names — confirm or strip
**Applies to:** all vCISO pages, both cornerstone articles, the homepage draft.
**The call:** I named **Foundation / Assurance / Directive** publicly (per the brief's "publish tier names, gate Directive pricing"). Confirm that's what you want, or I'll remove the tier names from public copy. (Exact Directive pricing is already gated everywhere.)

## 5. Connect Ahrefs and/or Similarweb (your OAuth)
**From:** competitive brief §10.
**The call:** Connect at least one (buttons were surfaced earlier) so I can quantify keyword difficulty/traffic before you invest content budget. Until then, the content set is built on *observed* SERP gaps, not measured volume. The vCISO service pages and FTC/ISO clusters are high-confidence regardless; the broader content scaling decision should wait for data.

## 6. note_submissions logging — outstanding rows
**From:** project routing rule (CLAUDE.md).
**The call / FYI:** Every action in this session (competitor research, content drafts, vendor decision, scheduled monitor) is a **klaravex.com-surface action routing to Azure `klaravex-db`**. I have **no DB write path in this Cowork session**, so those `note_submissions` rows are **outstanding and yours to record** (or tell me the mechanism and I'll prepare the inserts). Per your rule, I did not cross-write and did not silently skip — I'm surfacing it.

## 7. Review-seeding — needs real clients
**From:** `review-seeding-playbook.md`.
**The call:** The process is ready. Execution needs you to pick clients and approve the ask. Is there a current client at a milestone we could ask first (Google Business Profile → Clutch → G2)?

## 8. Competitive monitor — live; optional pre-approval
**Status:** **Done and scheduled** — runs monthly, 1st at 9 AM, first run Jul 1, output to `marketing/competitive-monitor/`. Manage/cancel it in the **Scheduled** sidebar. Optional: click **Run now** once to pre-approve its web-search permissions so future runs don't pause.

---

### What I can do next without you
- Draft the 4 ISO 27001 supporting pieces in full (currently outlined).
- Turn the competitive brief's competitor profiles into **sales battlecards**.
- Prep the Cynomi/MDR evaluation scorecard and demo-question list for when you're ready to get quotes.
- Build a second self-assessment variant or a downloadable checklist asset.

Tell me which, or hand me decisions 1–4 and I'll keep moving.
