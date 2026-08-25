# visitBerlin — Conversational Booking Assistant

**Status:** Early-stage concept · Pre-RFP  
**Opened:** 2026-07-20  
**Client:** visitBerlin (Berlin Tourismus & Kongress GmbH)  
**Klaravex contact:** Klaravex LLC  
**Relationship:** Adjacent to the Knowledge Manager engagement (separate contract)

---

## What this is

A public-facing conversational assistant embedded on visitBerlin.de that lets tourists discover Berlin experiences, ask questions, and complete bookings without leaving the chat interface.

This is **not** the internal Knowledge Manager (staff-facing, employee document retrieval). This is an outward-facing product that touches end consumers.

---

## Core user journeys (initial scope)

| # | Journey | Entry point | End state |
|---|---------|------------|-----------|
| 1 | Discover | "What's on this weekend in Mitte?" | Curated event/attraction list with CTAs |
| 2 | Book | "I want two tickets to the Pergamon Museum on Saturday" | Confirmed reservation + booking ref |
| 3 | Confirm & manage | "Can I change my booking to Sunday?" | Updated booking or cancellation |
| 4 | Escalate | Complex query or payment failure | Handoff to human agent with context |

---

## Key open questions (blockers before spec can close)

1. **Integration depth** — does the chatbot wrap visitBerlin's existing booking system (API calls to the current ticketing platform), or does Klaravex build a net-new booking flow? This is the biggest scope and cost driver.
2. **Which booking inventory?** — visitBerlin operates attractions, convention bureau, and partner experiences. What's in scope for booking (owned venues only, or partner inventory too)?
3. **Payment handling** — in-chat payment (Stripe/PayPal embedded), or redirect to existing checkout?
4. **Languages** — German + English minimum. Others?
5. **Escalation target** — what's the human agent channel? Existing call centre, a new live-chat tier, or email queue?
6. **Data ownership** — does visitBerlin own the booking/session data, or does it flow through a third-party ticketing platform? Affects GDPR obligations.
7. **Channel** — website widget only, or also WhatsApp / Messenger / Telegram?
8. **Relationship to KM** — can the bot draw answers from the internal Knowledge Manager's indexed content, or must it be a clean separation (different data governance regime for public vs. internal)?

---

## Folder structure

```
visitberlin-chatbot-booking/
├── README.md               ← this file
├── spec/
│   └── concept-brief.md    ← initial concept, user stories, success metrics
├── architecture/           ← to be populated after open questions resolve
└── research/               ← competitor chatbots, ticketing API options, etc.
```

---

## Next steps

- [ ] Discovery call with visitBerlin to close open questions 1–8 above
- [ ] Identify the existing ticketing platform / booking system in use
- [ ] Competitive review: how do peer tourism boards (NYC Tourism, Visit London, Vienna Tourist Board) handle conversational booking?
- [ ] Draft concept brief (`spec/concept-brief.md`) once Q1 (integration depth) is answered
