# Concept Brief — visitBerlin Conversational Booking Assistant

**Version:** 0.1 (pre-discovery — assumptions marked ⚠)  
**Date:** 2026-07-20  
**Status:** DRAFT — open questions must be resolved before this brief is baselined

---

## Problem statement

visitBerlin.de surfaces rich event and attraction content, but the path from "I'm interested" to "I have a booking" requires the visitor to navigate multiple pages, locate the correct ticketing partner, and complete a checkout in a separate system. Drop-off is high at each handoff. A conversational layer collapses discovery, recommendation, and transaction into a single interface the visitor never leaves.

---

## Proposed solution

An AI-powered chat widget on visitBerlin.de that handles:

1. **Natural-language discovery** — understands intent ("family-friendly", "rainy day", "free", "near Alexanderplatz") and returns ranked recommendations from visitBerlin's content catalogue.
2. **In-chat booking** — collects date, time, party size, and payment, then calls the booking API to create a reservation without the visitor leaving the chat.
3. **Booking management** — lets visitors retrieve, modify, or cancel existing reservations by reference number or email.
4. **Escalation with context** — when the bot can't resolve a request, it hands off to a human agent with the full conversation and booking context attached.

---

## Target users

| Persona | Description |
|---------|-------------|
| **International tourist** | Pre-trip planner, English-speaking, mobile-first. Wants fast answers and frictionless booking. |
| **Berlin day-tripper** | German-speaking, spontaneous. Asks "what's on tonight?" and books on the spot. |
| **Conference delegate** | Arrives for a congress at the Berlin Congress Center; wants curated local extras. |

---

## Success metrics (draft — to be confirmed with visitBerlin)

| Metric | Baseline (current) | Target (12 months post-launch) |
|--------|-------------------|---------------------------------|
| Booking conversion rate (visitors who start a discovery intent) | ⚠ unknown | +15 pp vs. current site flow |
| Average booking journey time | ⚠ unknown | < 3 minutes in-chat |
| Escalation rate | — | < 12% of sessions |
| CSAT (post-booking survey) | ⚠ unknown | ≥ 4.2 / 5.0 |
| Languages handled without escalation | 1 (implied German site) | German + English day-1 |

---

## Assumptions (⚠ unverified — must be confirmed in discovery)

- visitBerlin operates or has API access to a ticketing system that supports programmatic reservation creation and payment capture.
- visitBerlin owns the consumer booking data (not locked in a third-party ticketing SaaS with no API).
- Payment can be handled via a redirect or embedded iframe (Stripe/PayPal) rather than requiring full PCI DSS card-data handling inside the chatbot backend.
- The existing visitBerlin content catalogue (events, attractions, partner experiences) is accessible via a structured API or feed (e.g. JSON/XML export, CMS API).
- visitBerlin's legal/DPO team will accept a GDPR-compliant session log for the chat interactions (no chat content retained past session end unless user consents).

---

## Proposed technical approach (pre-discovery sketch)

```
Visitor browser
    │  WebSocket / SSE
    ▼
Chat widget (JS — visitBerlin.de)
    │  HTTPS
    ▼
Klaravex Bot API  (FastAPI, Azure Germany-West-Central ⚠ or visitBerlin's preferred cloud)
    ├── NLU / intent router  →  Azure OpenAI (gpt-4o)
    ├── Content retrieval    →  visitBerlin Events/Attractions API  (⚠ to be identified)
    ├── Booking engine       →  visitBerlin Ticketing API  (⚠ to be identified)
    ├── Payment              →  Stripe Payment Intents or visitBerlin payment provider  (⚠)
    ├── Session store        →  Redis (ephemeral, no PII at rest beyond session TTL)
    └── Escalation bridge    →  visitBerlin contact centre / live-chat platform  (⚠)
```

**Relationship to KM:** treated as a clean separation by default (different data governance for public vs. internal content). If visitBerlin wants the bot to draw on KM-indexed FAQs or partner documentation, that requires a cross-system access agreement — open question 8 in README.

---

## Scope options to present in discovery

| Option | Description | Complexity |
|--------|-------------|-----------|
| **A — Wrapper** | Bot wraps visitBerlin's existing booking system via API; no new booking logic built | Low — depends on API quality |
| **B — Hybrid** | Bot handles discovery and pre-booking; redirects to existing checkout for payment | Medium — reduces payment complexity |
| **C — Full stack** | Bot owns the full journey including in-chat payment | High — full PCI/GDPR scope |

Recommend pitching Option B as the default MVP, with Option C as a Phase 2 upsell once volume justifies the compliance overhead.

---

## Open questions tracker

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Integration depth (wrapper vs. new flow)? | visitBerlin | ⚠ Open |
| 2 | Which booking inventory is in scope? | visitBerlin | ⚠ Open |
| 3 | Payment handling approach? | visitBerlin + Klaravex | ⚠ Open |
| 4 | Languages required at launch? | visitBerlin | ⚠ Open |
| 5 | Escalation target channel? | visitBerlin | ⚠ Open |
| 6 | Data ownership / ticketing platform? | visitBerlin | ⚠ Open |
| 7 | Channels beyond website widget? | visitBerlin | ⚠ Open |
| 8 | KM content reuse permitted? | visitBerlin DPO | ⚠ Open |
