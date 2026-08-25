# Klaravex — MDR/EDR White-Label Partner Analysis
**Saved:** 2026-06-03 · Source: 05-Managed-Security-Lines doc · Decision: use Huntress as backbone

## Decision
1. **Sign with Huntress** as security backbone — lowest entry cost, channel-first, covers EDR + ITDR + SAT + 24/7 SOC in one vendor
2. **Microsoft Defender for Business** as EDR engine for M365-heavy clients (often already licensed in M365 Business Premium) — layer Huntress MDR on top
3. **Blackpoint Cyber** as upgrade option for clients who need most aggressive response
4. **Loki sits in front of all of it** — client-facing triage, plain-English alerts, escalation = Klaravex differentiator

## Vendor comparison

| Vendor | MSP cost | What it is | Verdict |
|--------|----------|------------|---------|
| **Huntress** | ~$2.50–3.50/endpoint/mo (~$1.95 at volume); 50-unit minimum (pool across clients) | Channel-first, 24/7 human SOC included, EDR + ITDR + SAT + SIEM | ⭐ Primary pick |
| **Blackpoint Cyber** | ~$8–15/endpoint/mo | Fastest/most aggressive response, pairs with Defender | ✅ Premium upgrade option |
| **Microsoft Defender for Business** | ~$3/user/mo (often in M365 BP already) | EDR layer only — no human SOC | ✅ EDR engine for M365 clients |
| **ConnectWise MDR** | Varies | MDR on top of Defender/Bitdefender/SentinelOne | ◽ Viable, more platform lock-in |
| **SentinelOne** | Enterprise pricing | Excellent EDR but direct-to-enterprise, bad channel economics | ❌ Skip for now |

## Margin math
- Huntress cost: ~$3/endpoint/mo
- Bundle into Assurance plan at ~$15/user effective
- Strong recurring margin, still under market premium band ($225–350)
- Security lines drive Foundation→Assurance upgrades without adding labor

## Service tier mapping
- Foundation: no MDR/EDR (add-on at $15/user/mo)
- Assurance: Huntress MDR + EDR + SAT + email security included
- Directive: everything in Assurance + compliance readiness + vCISO

## Next action
Sign up at huntress.com/partners — free to join, pay per endpoint when clients onboard.
