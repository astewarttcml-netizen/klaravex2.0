# 89% AI-Resolution Claim — Substantiation / Retire Memo

**Task:** `stratex-89pct-claim-2026-08-17` (competitive-intel finding #5)
**Author:** Loki (host-session orchestrator)
**Date:** 2026-08-18
**Status:** RECOMMENDATION — pending Anthony decision (no site change made yet)

---

## 1. The claim as it exists today

The live `klaravex.com` homepage (and every downstream page, plus the
`personal` consumer surface and the `.de` German variant) repeats a precise,
quantitative resolution statistic:

> **"89% of IT issues resolved by AI"**
> (also rendered as "89% resolved. 11% escalated.", "89% by AI",
> and in German "89% der Anfragen")

Verified live 2026-08-18 via `curl https://klaravex.com/` — the figure appears
**10+ times** on the production homepage with **no source, no methodology, no
sample size, and no footnote**. Prior audits already flagged this:

- `.private/site-audit-design-2026-06-23.md:73` — *"Hero stats are unsourced…
  The 89% figure is repeated 7 times on the homepage alone — needs a footnote
  or it reads as marketing fabrication."*
- `seo-ai-visibility-audit-2026-06-11.md:166` — *"89% claim substantiation: keep
  a methodology note (even one line, 'measured across resolved sessions,
  trailing 90 days') — insurers, reviewers, and the FTC all like substantiation."*

## 2. Why this is a real risk, not a nitpick

- **Klaravex LLC is a 2026-founded company.** There is no multi-year ticket
  corpus that could defensibly produce a precise 89.0% figure. A precise number
  this early invites the exact question compliance-minded buyers ask:
  *"89% out of how many tickets, over what window?"*
- **The purchasers are compliance-driven verticals** — CPA firms (IRS WISP),
  medical offices (HIPAA), law firms. These buyers are trained to distrust
  unsourced metrics, and the FTC standard for advertising substantiation
  requires that a marketer have a reasonable basis *before* making the claim.
- **Answer-engine / AI search extraction** reproduces the number verbatim.
  If the number is ever challenged or softened later, the unsourced "89%"
  will already be baked into every LLM's crawler summary of the company.

## 3. Why we should NOT fabricate a methodology

The tempting fix is to invent a backing number ("measured across 1,247 resolved
sessions, trailing 90 days"). **Do not do this.** There is no ticket-system
telemetry in the repo that would make that number true, and manufacturing a
precise sample would be a fabrication on a user-facing compliance surface.
This violates the same substantiation principle we are trying to satisfy.
If real telemetry does exist (e.g. in the Atera/Zendesk/HubSpot backend), it
must come from Anthony and be pulled from the actual system — not authored here.

## 4. Recommendation (pick ONE — pending Anthony)

**Recommended: Option B (soften to a defensible, still-differentiated claim).**

- **Option A — Retire the number entirely.** Replace precision with capability.
- **Option B — Soften to a range + shift the emphasis off the number.**
  Lead with the *outcome* ("no ticket queue", "seconds not days") and demote
  the percentage to a defensible qualitative range ("the large majority").
- **Option C — Substantiate for real.** Only valid if Anthony can export actual
  AI-resolution telemetry (ticket count, AI-resolved count, trailing window)
  from the live helpdesk. If that data exists, we document the methodology on a
  `/results/` or `/how-it-works/` page and add a one-line footnote to the hero.

## 5. Replacement copy (voice-policy clean, US-only "we" voice)

If Option B is chosen, here is ready-to-paste copy that keeps the AI-first
differentiator without the unsourced precise figure:

**Hero (B2B):**
> "Most incoming IT issues are resolved in seconds — not days — by our AI
> support layer, with a US senior engineer on standby for everything it can't."

**Stat strip (replaces "89% · 24/7 · 2hr · $0"):**
> "AI-first triage · 24/7 coverage · 2-hour senior-engineer escalation ·
> $0 vendor commissions"

**Inline (where "89% resolved. 11% escalated." appears):**
> "The large majority of first-line issues are resolved on the spot by our AI
> support layer; the rest go straight to a senior engineer with full history
> already attached."

**German variant (if the .de surface is ever revisited):**
> "Die große Mehrheit eingehender Anfragen wird sofort gelöst — der Rest geht
> sofort an eine erfahrene Ingenieurin oder einen erfahrenen Ingenieur."

*(No "89%", no fabricated sample size, consistent with the established
"expert-led, AI-accelerated, humans accountable" positioning.)*

## 6. Decision requested

| # | Question | Options |
|---|---|---|
| 1 | Does real AI-resolution telemetry exist in the helpdesk backend? | Yes (export it, we substantiate) / No (Option A or B) |
| 2 | If no telemetry → soften (B) or retire (A)? | B recommended |
| 3 | Authorize the copy edit on the live WP site? | Yes (I'll PATCH + grep-verify) / Hold |

No site change has been made. The claim remains live and unsourced pending this
decision.
