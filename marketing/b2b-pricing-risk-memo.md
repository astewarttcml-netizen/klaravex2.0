# B2B Pricing Risk Memo — Premium Promise vs. Entry-Band Price

**Task:** `stratex-b2b-pricing-2026-08-17` (competitive-intel finding #3)
**Author:** Loki (host-session orchestrator)
**Date:** 2026-08-18
**Status:** INTERNAL RISK MEMO — pricing remains UNCHANGED (Anthony directive: "use my pricing")

---

## 1. Context

Competitive-intel finding #3 recommended **$150–200/user + a 10-user minimum**
to align premium-tier delivery with pricing. **This recommendation is NOT
adopted.** Anthony's directive (2026-08-17) is to keep the live tiers:

| Tier | Live price (authoritative) |
|---|---|
| Foundation | $49/user/mo |
| Assurance | $79/user/mo |
| Directive | $129/user/mo |

This memo reconciles the intel warning against those confirmed tiers **without
changing them**, and records the residual risk + optional mitigations for later.

## 2. The intel warning, restated precisely

Two separate concerns:

1. **Premium promise vs. entry-band price.** The `Directive` tier promises
   vCISO + framework readiness (HIPAA/SOC 2/ISO 27001) + board reporting + IR
   retainer — a bundle the market sells at **$200–350/user** (traditional vCISO)
   or **$3K–8K/mo flat** (per `pricing-proposal-2026-07-26.md`). Klaravex offers
   it at **$129/user**, ~35–50% below market. That is a defensible *positioning*
   strategy, but it creates delivery risk if the cost of the human compliance
   labor is not actually covered by the AI-backed margin.

2. **No user minimum.** The live pricing page surfaces **per-user prices with no
   minimum seat count**. A 1–2 person firm on Directive ($129–258/mo) cannot
   cover a real vCISO/compliance engagement. The prior proposal
   (`pricing-proposal-2026-07-26.md`) DID propose minimums (5 users on
   Foundation/Assurance, 10 users on Directive) but the intel flags that the
   live site does not reflect them.

## 3. Risk assessment

| Risk | Likelihood | Impact | Notes |
|---|---|---|---|
| Sub-5-seat firms buy Directive at $129 and over-consume compliance hours | Med | Med | Small directional firms are the cheapest-to-acquire, least-retaining segment |
| Premium promise under-delivered → review + churn risk | Low–Med | High | Reputational; matters acutely to the review-social-proof finding (#7) |
| "Cheapest vCISO in the market" perception cheapens the compliance offering | Med | Med | Compliance buyers don't shop on price; too low can read as non-serious |

**Net:** the AI cost advantage is real (per the proposal's 0.6× formula), so the
$49/$79 tiers are safely sustainable. The risk concentrates in **Directive at
low seat counts with no minimum**, not in the entry tier pricing itself.

## 4. Optional mitigations (do NOT apply now — for Anthony's later call)

1. **Reintroduce a minimum on Directive only** — e.g. "Directive from 5 users"
   (floor $645/mo) while keeping Foundation/Assurance minimum-free for
   acquisition. Smallest change, targets exactly the exposed tier.
2. **Scope-guard Directive delivery** — vCISO hours and readiness are
   proportional to seat count; publish a "what Directive covers" boundary so a
   3-user firm knows it gets quarterly posture review, not a full-time vCISO.
3. **Separate the one-time WISP / readiness work** from the $129 recurring
   (matches the `accounting-vertical-offer-spec.md` recommendation) so the
   recurring tier doesn't silently absorb $5K–15K readiness engagements.
4. **Monitor floor revenue** — flag any Directive client < 5 seats in the CRM
   for a manual qualification step before contract.

## 5. Decision requested

| # | Question | Options |
|---|---|---|
| 1 | Keep tiers exactly $49/$79/$129 with no minimum (status quo)? | Yes / Reintroduce Directive minimum |
| 2 | If a minimum, on which tier + what seat count? | Directive @ 5 (recommended) |
| 3 | Apply scope-guard copy to the Directive tier on the site? | Yes (I'll PATCH) / Hold |

No pricing change made. This memo is the record the task required; the live
tiers remain authoritative until you decide otherwise.
