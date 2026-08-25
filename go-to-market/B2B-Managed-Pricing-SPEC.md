# Klaravex B2B "Managed" Pricing — Build Spec (US + EU)
Implements the Finance/synthesis recommendation. Replace the $24/mo "Home Membership"
on the BUSINESS sites (klaravex.com + klaravex.com) with per-seat managed plans + a floor.

## Tiers (USD on .com / EUR on .de — same numbers)
| Tier | Price | Best for | Includes |
|---|---|---|---|
| **Essential** | $29 / seat / mo | 1–4 seats (micro) | 24/7 Klara AI support + monitoring, client portal, fair-use ~3 tickets/seat/mo, email security basics |
| **Managed ⭐ (ANCHOR)** | **$49 / seat / mo** | 5–25 seats (most buy this) | Everything in Essential + security monitoring & patching, onboarding/provisioning, monthly senior-engineer review, priority escalation, written reporting |
| **Secure+** | $79 / seat / mo | regulated / 25+ seats | Everything + compliance reporting (HIPAA/SOC2/GDPR), dedicated engineer hours, tighter SLA, audit support |
| **Minimum commitment** | **$245 / mo floor** | — | every B2B account bills ≥ $245/mo so no account is margin-negative |

## Rules
- **Per-seat + monthly floor** = predictable MRR, natural expansion, protects against tiny unprofitable accounts.
- **Fair-use caps** (e.g., ~3 tickets/seat/mo on Essential) protect gross margin from heavy users; overage rolls to next tier or per-incident.
- **Anchor = Managed**; price Secure+ visibly higher so Managed reads as the obvious choice.
- **Every one-time / incident buyer is offered the plan at point of sale**: "This incident is free on a $49/seat Managed plan." Track one-time→recurring conversion %.
- 2-hour human SLA with **service credit** if missed (existing promise) — keep, it's a trust closer.
- Annual option: 2 months free (drives cash + cuts churn).

## EU notes (.de)
- Same numbers in €. Lead the page with **EU data residency + GDPR** next to the price.
- Bilingual DE/EN (already wired). Tone: experts-led, AI assists.

## Implementation
- Replace the pricing section on klaravex.com + klaravex.com business homepages + /pricing.
- Wire Stripe products/prices (per-seat subscription + $245 floor as a minimum). Use Stripe Checkout/Billing.
- Add to the portal: plan, seat count, usage (tickets used vs fair-use), upgrade CTA.
