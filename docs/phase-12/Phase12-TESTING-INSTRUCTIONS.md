# Phase 12 — B2B Voice Squad + VIP — Testing Instructions

Six end-to-end + three VIP scenarios. Every scenario must pass before Phase 12 is signed off as live.

## Setup

- Vapi staging assistants required: `triage_en` (with v3.1 business fork + VIP silent gate), `biz_intake`, `biz_engineer`, plus existing consumer specialists (`windows_expert`, `apple_expert`, `mobile_expert`, `smart_home_network`, `identity_recovery`, `live_troubleshoot`).
- VIP backend endpoint `POST /api/v1/vapi/vip_access` deployed (PH12.V12).
- `klaravex_vip_directory` table seeded with at least one test number (Anthony's mobile).
- Test caller phones: a "consumer-disguise" number not in VIP directory, plus Anthony's mobile (in VIP directory).

## Scenario 1 — Consumer → triage → consumer engineer

**Purpose**: regression test for v3.0 consumer path. Confirms the business fork didn't break consumers.

**Caller script**: dial +1 (424) 348-6010 from a non-VIP number. When greeted, say: "Hi, my home WiFi keeps dropping out — every few minutes I have to reboot the router." Wait through diagnostic questions, answer naturally.

**Expected agent behavior**:
1. `triage_en` answers with standard consumer greeting (no business detection signal in the opener)
2. Asks consent + collects email + first name
3. Identifies issue category "Smart Home / Network"
4. Says transfer phrase: "Okay {first_name}, I'm bringing in our SmartHome specialist now…"
5. Calls `transfer_to_specialist` → `smart_home_network`
6. Specialist receives transcript context, picks up troubleshooting from where triage left off

**Pass criteria**:
- No business path triggered (no biz_intake transfer)
- Email + first name appear in specialist transcript
- One transfer event in call log, no double-transfers
- Total caller-talk time before specialist pickup ≤ 90s

**Cleanup**: end call, delete test record from any logs.

---

## Scenario 2 — B2B caller → triage detects business signal → routes to `biz_intake`

**Purpose**: confirm v3.1 business fork triggers on business signals.

**Caller script**: dial +1 (424) 348-6010 from a non-VIP number. When greeted, say: "Hi, I'm calling for our company — we're a 30-person medical practice and our M365 keeps locking out the front-desk PCs."

**Trigger signals**: "our company", "30-person", "medical practice", "M365" — multiple business indicators.

**Expected agent behavior**:
1. `triage_en` detects business signal within first 1-2 turns
2. Says transition phrase: something like "It sounds like you're calling for your business — let me hand you to our business team."
3. Calls `transfer_to_specialist` → `biz_intake`
4. `biz_intake` greets with the "Klara with Klaravex business services" opener
5. Collects company name, size, vertical, current pain

**Pass criteria**:
- Business fork triggered (transfer to `biz_intake`, NOT a consumer specialist)
- Transfer happens ≤ 3 turns from caller statement
- `biz_intake` opener includes "business" or "company" language (not generic consumer)

---

## Scenario 3 — B2B caller → `biz_intake` qualifies → hands off to `biz_engineer`

**Purpose**: confirm `biz_intake` → `biz_engineer` handoff is functional for qualified leads.

**Caller script**: continue from Scenario 2 — answer `biz_intake`'s qualification questions affirmatively: "Yes I'm the decision-maker", "Our budget is around $5k/month", "We're looking for HIPAA-aware IT support and we need to start within 30 days."

**Expected agent behavior**:
1. `biz_intake` confirms decision-maker, budget, urgency, vertical fit
2. Says transition phrase: "Great — let me bring in our engineer to talk through the technical fit."
3. Calls `transfer_to_specialist` → `biz_engineer`
4. `biz_engineer` opens with "I see we're talking about HIPAA, M365, medical practice — let's confirm the stack…" or similar

**Pass criteria**:
- Handoff to `biz_engineer` happens after qualification (not before)
- `biz_engineer` shows awareness of the captured context (HIPAA, M365, 30-person) within first turn
- Total time from initial answer to `biz_engineer` pickup ≤ 4 minutes

---

## Scenario 4 — B2B caller → `biz_intake` disqualifies → graceful exit

**Purpose**: confirm `biz_intake` handles unqualified callers without dumping them on `biz_engineer`.

**Caller script**: dial +1 (424) 348-6010 from a non-VIP number. Say: "Hi, I'm calling for a marketing agency — we have 2 people, we just need someone to set up our email." Answer follow-ups consistent with "tiny team, no compliance need, looking for $50/month".

**Trigger disqualification**: company size <5, no compliance/regulated vertical, sub-Foundation budget.

**Expected agent behavior**:
1. `biz_intake` collects company info
2. Recognizes mismatch with Foundation/Assurance/Directive tier minimums
3. Says graceful exit phrase: "We focus on regulated SMBs starting around $75/user/month — I want to make sure your time isn't wasted. May I suggest a few alternatives?"
4. Either offers a referral list, books a discovery call anyway with caveat, OR cleanly ends the call

**Pass criteria**:
- `biz_intake` does NOT transfer to `biz_engineer`
- Exit happens within 3 minutes
- Caller doesn't feel rejected harshly — language stays warm
- No promise of future contact unless caller asks for one

---

## Scenario 5 — B2B caller → `biz_engineer` scopes → schedules follow-up

**Purpose**: confirm full pipeline to booked meeting.

**Caller script**: continue from Scenario 3 (qualified B2B caller now talking to `biz_engineer`). Answer questions about: current MSP, ticket volume, M365 license tier, network gear, primary IT pain. End with: "Yeah, let's set up a 30-min call with Anthony to walk through next steps."

**Expected agent behavior**:
1. `biz_engineer` captures tech context (M365 SKU, Atera vs no RMM, on-prem vs cloud, regulatory framing)
2. Confirms readiness to book
3. Calls `send_booking_link` (sends Calendly link to caller's email or SMS)
4. Confirms: "I've sent the booking link to {email}. Anthony will have the project brief from this call before you meet."

**Pass criteria**:
- `send_booking_link` tool fires with correct email
- Calendly link arrives in caller's inbox/SMS within 30s
- Vapi call summary contains the scoping notes (company, tech stack, primary pain, decision-maker, budget)
- Loki opens a B2B lead row in `klaravex_b2b_leads` (or equivalent) populated from the call summary

---

## Scenario 6 — VIP caller → silent VIP block routes around triage → direct to Anthony's queue

**Purpose**: VIP gate works end-to-end. Covers PH12.V13.

**Caller script**: dial +1 (424) 348-6010 from Anthony's mobile (registered VIP number in `klaravex_vip_directory`).

**Expected agent behavior**:
1. Call connects
2. `triage_en` calls `vapi_vip_access` function with `from_number_e164` = Anthony's mobile
3. Backend `/api/v1/vapi/vip_access` returns `{is_vip: true, route_to_assistant: "vip_handler", context: {name: "Anthony", ...}}`
4. `triage_en` SILENTLY transfers to `vip_handler` — **does not speak greeting**
5. Caller hears either: nothing for ≤ 2s, OR a single "Connecting you now" phrase, then VIP handler picks up

**Pass criteria**:
- `triage_en` does NOT say the standard consumer greeting
- Time from call connect to VIP handler pickup ≤ 3 seconds
- Vapi function call log shows `vapi_vip_access` was invoked with correct phone
- VIP handler greets Anthony by name (uses the `context.name` field from the VIP backend response)
- Standard call recording is captured (don't suppress logging — only the greeting)

---

## VIP-specific scenarios (PH12.V14)

### Scenario 7 — VIP recognized → silent transfer

**Same as Scenario 6** but with a second registered VIP number (a backup VIP — e.g., a co-founder or trusted partner). Verifies that the VIP directory is more than one row.

**Caller script**: dial from second-registered VIP number.

**Pass criteria**: same as Scenario 6.

---

### Scenario 8 — VIP not recognized (number changed) → fallback to standard flow

**Purpose**: confirm graceful degradation when a "real" VIP calls from a phone that isn't yet in the directory.

**Caller script**: dial +1 (424) 348-6010 from a number that is NOT in `klaravex_vip_directory` but who IS otherwise a VIP (e.g., Anthony's burner / spouse's phone). Say: "Hi, this is Anthony — I'm calling from my backup number."

**Expected agent behavior**:
1. `triage_en` calls `vapi_vip_access` with unregistered number
2. Backend returns `{is_vip: false}`
3. `triage_en` falls back to standard consumer greeting
4. Caller can self-identify; triage routes them as it would any consumer

**Pass criteria**:
- Caller is NOT stuck in silence (fallback to consumer greeting happens)
- Caller is NOT auto-promoted to VIP based on stated name (would be a security hole — must require directory match)
- Triage routes them through standard consumer flow once self-identification is complete

---

### Scenario 9 — VIP backend timeout → fail-open to standard flow

**Purpose**: confirm safety when the VIP backend is down. This is the MUST-PASS gate for going live.

**Setup**: temporarily stop the API service hosting `/api/v1/vapi/vip_access` (or block port via iptables on dev environment). Use a registered VIP number for the call.

**Caller script**: dial from a VIP-registered number while the backend endpoint is unreachable.

**Expected agent behavior**:
1. `triage_en` calls `vapi_vip_access`
2. Function times out (Vapi's `timeoutSeconds: 5` per the function definition)
3. `triage_en` treats timeout as `is_vip = false` → falls back to standard consumer greeting
4. Metric `vip_lookup.timeout` increments

**Pass criteria**:
- Caller is NOT stuck in silence
- Caller is NOT leaked into a VIP-only handler (must NOT fail-closed in a way that hands non-VIP callers VIP context)
- Metric counter shows the timeout
- Standard consumer flow continues normally

---

## Post-test cleanup

After each scenario:
- Delete any test rows from `klaravex_b2b_leads`, `klaravex_freelance_matches`, or other operational tables (use the test-data cleanup script if present).
- Mark the test phone number's recent call records as `test_call=true` in Vapi metadata.
- Confirm no Stripe/Calendly side-effects (no real test booking lingering on Anthony's calendar).

## Sign-off

Each scenario gets a row in `.loki/state/phase12-test-results.json`:

```json
{
  "scenario": 1,
  "name": "consumer-passthrough",
  "tested_at": "ISO-8601",
  "tester": "claude-host-session | anthony | ...",
  "pass": true,
  "notes": "..."
}
```

All nine scenarios must show `pass: true` before Phase 12 is marked complete in `pending.json`.
