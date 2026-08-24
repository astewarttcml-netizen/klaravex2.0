# B2B Voice Squad — Design (v1.0, 2026-06-11)

Mirrors the consumer specialist squad for business callers. Two new Vapi
assistants + three backend tools + one schema addition. Reuses: the
transfer pattern, NATO email protocol, payment-link delivery machinery
(repurposed for booking links), the 5 engineer agents, and the existing
client/ticket tables.

## Architecture

```
                       +1 (424) 348-6010
                              │
                        triage_en (Klara)
                              │ Step 0: "personal or business?"
              ┌───────────────┴────────────────┐
         PERSONAL                          BUSINESS (new Step 0-B)
       (existing consumer            "Are you an existing Klaravex client
        squad, unchanged)             with a customer number, or looking
                                      to work with us?"
                                   ┌──────────┴───────────┐
                               NEW CLIENT             EXISTING CLIENT
                                   │                       │
                         transfer_to_specialist    "Enter your 6-digit
                           biz_intake               customer number on
                                   │                 your keypad"
                          collect → book →                 │
                          AI pre-brief          transfer_to_specialist
                                                    biz_engineer
                                                           │
                                                lookup_client(code) →
                                                file-aware advice via
                                                the 5 engineer brains
```

## Assistant 1 — `biz_intake` (new business customers)
Prompt: `biz-intake.md`. Job: qualify + capture + book, never solve.
1. Collect (in order, conversationally): company name, caller name + role,
   employee/seat count, current IT setup (none / break-fix / another MSP),
   top 1-2 pain points, urgency, phone (From number, confirm), email
   (**NATO protocol — same as consumer**).
2. Tool `create_b2b_lead` → writes lead row, returns lead_id; backend pages
   on-call team digest (Telegram + email) immediately.
3. Tool `send_booking_link` → emails/texts the Calendly discovery link
   (STATIC link — no Calendly API needed; reuses payment-link delivery).
   Klara stays on the line: "Tell me when you see it… The email has a
   button to pick any time on our team's calendar."
4. After booking (or if caller books later): backend `calendly_webhook`
   (already exists) fires the **AI project team pre-brief**: the dispatcher
   gives the intake summary to the relevant engineer agents
   (managed_security / microsoft_365 / regulatory_readiness / ai_adoption /
   strategic_advisory by keyword), each drafts their section, merged
   "Project Pre-Brief" lands in the approval queue → on approve,
   pre-meeting email goes to the team + the prospect. (EngineerAgent already
   works exactly this way: draft → approval → deliver.)
   Fallback while Calendly token is blocked (T0.3): pre-brief generates at
   lead-creation time instead of booking time.

## Assistant 2 — `biz_engineer` (existing business clients)
Prompt: `biz-engineer.md`. Job: authenticated, file-aware advice.
1. **Auth — 6-digit customer code via DTMF.** "Please type your six-digit
   customer number on your phone's keypad." (Vapi DTMF capture; spoken
   digits accepted as fallback with digit-by-digit readback.)
2. Tool `lookup_client(customer_code, caller_phone)` returns the bundle:
   company, plan tier, named seats, open tickets, last 5 resolved tickets,
   environment summary. **Trust levels:**
   - Code + caller-ID matches a number on file → FULL: discuss file
     specifics, open tickets, environment details.
   - Code valid but caller-ID unknown → VERIFY: caller must state company
     name + the email domain on file. Then ADVISORY level: discuss guidance
     and open a ticket, but never read back stored contact data, seat
     names, or environment specifics ("I can note that on the account").
   - 3 failed codes → stop auth attempts, offer the new-client path or a
     callback, log `auth_failed` event.
3. Advice: tool `advise_client(question, pillar)` bridges the live call to
   the matching engineer agent (the same 5 brains), grounded in the
   client's file + KB RAG. Routing by topic mirrors consumer rules:
   security/firewall/backup → managed_security · M365/email/Teams/Azure →
   microsoft_365 · compliance/insurance/HIPAA/SOC2 → regulatory_readiness ·
   AI/automation → ai_adoption · strategy/budget/roadmap →
   strategic_advisory (default).
4. Actions available by voice: `open_ticket` (P2/P3), `escalate_to_anthony`
   (P1 — real incident: breach, outage, money moving), `send_booking_link`
   (review call with our team). **Hard rule: advice + tickets only. No
   changes are executed from a phone call** — anything requiring action
   becomes a ticket that goes through the normal approval flow.

## Backend work (→ TASKS.md Phase 12)
- `customer_code CHAR(6)` on `klaravex_clients`: generated (no leading 0,
  no sequential), unique; surfaced in the portal header + welcome email.
- New Vapi tools (all behind `x-vapi-secret`, per H4):
  `POST /api/v1/vapi/create_b2b_lead` · `POST /api/v1/vapi/lookup_client`
  (rate-limit: 5 lookups/min per call_sid) · `POST /api/v1/vapi/advise_client`
  · `send_booking_link` = thin wrapper on the existing link-delivery lib.
- triage_en Step 0 business branch: replace "take a message and end call"
  with the two-question fork + transfers (prompt edit, version 3.1).
- Two new Vapi assistants created in dashboard, IDs added to
  `vapi_assistants.json`; `transfer_to_specialist` destinations updated.

## Decisions (2026-06-11)
1. **Code distribution: BOTH** — auto-email every existing client their
   code at launch AND surface it in the portal header + welcome email.
2. **biz_engineer voice: DISTINCT** senior voice (not Klara's), same
   honesty rule ("I'm the AI engineer on your account").
3. **Booking link: https://calendly.com/klaravex/klaravex-onboarding**
   (live, verified). Pre-brief fires at lead time now; moves to the
   calendly_webhook booking event when the Calendly token (T0.3) lands.
```
