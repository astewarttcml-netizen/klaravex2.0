# B2B Voice Flow — Architecture Spec

**Owner:** Anthony · **Date:** 2026-06-11 · **Status:** v0.1 draft for B2B build scoping

The consumer voice flow (Klara on +1-424-348-6010, $79 per-incident, payment + transfer to Windows/Apple/Mobile/SmartHome/Identity Recovery/Live Troubleshoot specialists) is in production. The B2B side currently exists only as a fallback branch inside Klara's prompt — if a caller says "business," she collects name/company/callback/summary and calls `escalate_to_anthony`. There is no B2B squad, no programmatic intake, no tier-aware behavior, no RMM integration, no SLA routing.

This spec defines what has to exist before the first signed B2B client takes their first support call. The goal is reuse: most of the substrate (Vapi, Anthropic, Deepgram, ElevenLabs, the helper app, the relay, vision LLM, NATO email collection, dropped-call recovery, escalate, log_session_outcome) already exists from consumer. The B2B-specific work is new prompts, a customer lookup, tier-aware routing, RMM ticket creation, and a different payment model.

Each item below is tagged **REUSABLE** (lift as-is from consumer), **REUSABLE-with-new-prompt** (same component, new behavior), **NEW** (build for B2B), or **RESEARCH** (Anthony decides before build).

---

## 1. Caller identification + routing

**RESEARCH — Separate phone number vs. shared.** Recommend a dedicated +1 number for B2B (e.g., a vanity DID Anthony picks) so caller-branch logic lives at the phone-number level rather than inside Klara's prompt. Sharing +1-424-348-6010 forces every consumer call through "are you calling about a personal device or your business?" — extra latency, more transfer failures, and Klara's consumer persona leaks into B2B calls. A separate number is also brand-cleaner on the klaravex.com B2B landing page and on email signatures. Cost is ~$2/mo per Vapi DID. **Anthony decides this before build kickoff.**

**NEW — Caller lookup at `call.start`.** When the B2B number rings, the entry assistant fires a `lookup_b2b_caller(phone_number)` tool before greeting. The lookup returns either:
- **Known caller:** `company_name`, `tier` (Foundation/Assurance/Directive), `assigned_engineer` (Anthony in v1), `sla_response_minutes`, `known_endpoints[]`, `active_incidents[]`, `last_3_tickets[]`. The agent greets by name, references the company, and skips identity collection.
- **Unknown caller:** Route to sales-intake flow — collect company, role, headcount, current MSP/IT setup, what prompted the call. This is a prospect, not a customer.

This is the single biggest behavioral difference from consumer: consumer always collects everything fresh because every caller is anonymous. B2B is account-aware from second one. **REUSABLE** infrastructure (Vapi call-start hook, tool-call endpoint at `api.klaravex.com`) — only the lookup logic and the customer table are NEW.

---

## 2. B2B voice agents (squad members)

Four specialist agents plus the triage entry, mirroring the consumer squad pattern.

**REUSABLE-with-new-prompt — Klaravex B2B Triage** (entry). Equivalent of Klara. Identifies whether the call is: routine support, new project / scope expansion, security incident, billing/account, or vCISO/compliance question. Tools: `lookup_b2b_caller`, `transferCall`, `escalate_to_anthony`, `log_session_outcome`.

**NEW prompt, REUSABLE tools — Klaravex B2B Engineer.** Handles M365, Azure, Google Workspace, AWS, endpoint issues. Assumes the endpoint is managed (RMM agent already installed — no per-call install dance). Tools: `create_ticket`, `start_remote_session` (skips download step on managed endpoints), `lookup_endpoint_inventory`, `escalate_to_anthony`.

**NEW — Klaravex B2B Security.** Handles incidents, suspected breach, phishing/scam reports, audit-prep questions short of full vCISO scope. Tools: `create_ticket` (severity defaults to "high"), `escalate_to_anthony` (always rings Anthony's mobile if `suspected_breach=true`), `schedule_calendly` (for follow-up forensics call), `log_session_outcome`.

**NEW — Klaravex B2B vCISO.** Directive-tier callers asking HIPAA / SOC 2 / ISO 27001 (US) or NIS2 / GDPR (EU) readiness questions. Tools: `create_ticket`, `schedule_calendly` (block-hour vCISO session), `lookup_readiness_engagement_status` (where is this client in their roadmap), `escalate_to_anthony`. Foundation/Assurance callers reaching this agent are politely redirected to a paid vCIO Calendly slot.

**NEW — Klaravex B2B Account.** Billing, scope changes, contract questions, address/contact updates. Tools: `lookup_subscription`, `create_ticket` (category=billing), `escalate_to_anthony` (any actual contract change requires Anthony — agent never modifies billing directly), `log_session_outcome`.

---

## 3. Tier-aware behavior

Tiers are already defined in `CLAUDE.md`: Foundation (~$75–100/user/mo), Assurance (~$100–150), Directive (~$150–250). Behavior diffs the voice flow must enforce:

- **Foundation** — Faster triage (no deep diagnosis on call), no vCISO access. Compliance/readiness questions get politely redirected to a paid block-hour Calendly. SLA: next-business-day. No outbound proactive calling from Loki.
- **Assurance** — Standard SLA (4-hour business-hour response). Routine engineer support included. vCISO access by paid block-hour only. Proactive outbound on critical RMM alerts.
- **Directive** — Priority routing, immediate vCISO access during business hours, 2-hour SLA, option to schedule live screen-share with Anthony if AI can't resolve. Proactive outbound on high+critical RMM alerts. "Lead with Directive tier" (per `CLAUDE.md`) means sales-intake flow defaults to pitching Directive.

**NEW — `attach_to_active_subscription` tool** replaces Klara's `send_payment_link`. B2B callers are on monthly subscription, so each incident is attached to their billing tier for monthly reporting (incident count, time spent, SLA met/missed) rather than charged per-incident. Per-incident charges only fire for explicitly out-of-scope work (data recovery, after-hours emergency for a Foundation client, etc.) — handled by Account agent escalating to Anthony, not by the voice flow autonomously.

**RESEARCH — Out-of-scope detection.** What counts as "out of scope" needs concrete rules before the AI can flag it. Anthony to define in service-tier scope doc before B2B launch. For v1, the AI never autonomously charges anything — every billable-incident-over-tier flags `escalate_to_anthony` instead.

---

## 4. AI-controlled remote session integration

The remote-session substrate from `docs/architecture/ai-remote-session.md` (helper app, relay, vision LLM, action-confirmation gate) is fully **REUSABLE**. B2B-specific differences:

- **REUSABLE-with-new-config — Helper distribution.** Pre-installed on managed endpoints via the RMM's agent push, not downloaded per-call. The customer never sees the download/permission dance. Session starts when Klaravex B2B Engineer fires `start_remote_session(endpoint_id)` against an already-onboarded device.
- **REUSABLE-with-new-prompt — Vision LLM context.** Same Claude Opus 4.7 multimodal endpoint, same 1–2 fps cadence, but the system prompt is enriched with: managed-endpoint inventory, last 30 days of tickets for this device, customer's standard software baseline, known approved patches/scripts. Better predictions, fewer "what is this app?" moments.
- **NEW — Softer confirmation gate for pre-approved actions.** On a managed endpoint, applying a patch already on the customer's approved-patches list does NOT require per-click voice confirmation — it requires only that the engineer agent verbally announces the action. Free-form actions (anything not in the approved list) still hit the full predict→speak→confirm→execute gate from §3 of the remote-session spec. The approved-actions list is per-customer and lives in the RMM.
- **REUSABLE — Audit logs.** Same per-session log format, but for B2B the logs roll up into the customer's monthly report attached to their billing tier.

---

## 5. Ticket creation + RMM integration

Per the Atera lifecycle decision ([docs/decisions/2026-06-11-atera-lifecycle.md](../decisions/2026-06-11-atera-lifecycle.md)), Atera is being **cancelled** and RMM selection deferred until the first B2B LOI triggers a structured 1-week bake-off (NinjaOne / Syncro / Action1). The voice flow must therefore be RMM-agnostic at the integration layer.

**NEW — `create_ticket` tool.** Every B2B call creates exactly one ticket. Inputs: `company_id`, `caller_name`, `summary`, `severity` (derived from caller language + tier — Directive + "breach" = critical; Foundation + "slow computer" = normal), `assigned_engineer` (Anthony in v1), `voice_call_recording_url`, `originating_agent` (which squad member). The tool posts to whichever RMM is the system-of-record once selected.

**RESEARCH — RMM vendor.** Current RMM is none (Atera cancelled per decision above). At first B2B LOI, run the documented bake-off. Voice-flow integration is a thin adapter — same `create_ticket` tool signature, different HTTP target per vendor. Do not build vendor-specific tool variants.

**NEW — Loki proactive outbound on RMM alerts.** Loki polls the selected RMM (or receives webhooks where available) for critical/high alerts on Directive- and Assurance-tier endpoints. On a triggering alert, Loki places an outbound call to the customer's primary contact, identifies the alert, and offers triage. This is the AI-native MSP differentiator called out in `CLAUDE.md` as "Phase 6 / second B2B client." Out of scope for v1 if it delays first-customer launch; in scope as soon as the first Directive client is onboarded.

---

## 6. Escalation to human (Anthony)

**REUSABLE-with-new-behavior — `escalate_to_anthony` tool.** Same tool name, same notification rails (SMS, email, mobile ring), but with severity- and tier-aware behavior:

- **Critical severity** (suspected breach, data loss, business-stopping outage) — Rings Anthony's mobile immediately regardless of tier or hour.
- **High severity** — SMS + email within 1 hour during business hours; SMS only after-hours for Directive tier; email-only after-hours for Assurance and Foundation.
- **Normal severity** — Email, batched into the next morning digest for Foundation; same-day email for Assurance and Directive.

**Tier-aware SLA** baked into the escalation:
- Directive: 2-hour response guaranteed (business + after-hours).
- Assurance: 4-hour business-hour response.
- Foundation: next-business-day response.

**NEW — Calendly slot offer.** For Directive callers wanting a live vCISO session, the vCISO agent offers a Calendly link via SMS to the caller's phone before ending the call. Reuses the `schedule_calendly` tool the consumer flow already exposes for Live Troubleshoot bookings.

**RESEARCH — Contractor engineer routing.** `CLAUDE.md` is explicit that contractor engineers do not yet exist. Routing logic for "Anthony unavailable + Directive critical" must therefore terminate at Anthony's mobile + email in v1. When Anthony hires the first contractor, revisit. Do NOT design for a hypothetical roster.

---

## 7. REUSABLE vs NEW — component summary

| Component | Status | Notes |
|---|---|---|
| Vapi voice platform | REUSABLE | Same account, same billing |
| Anthropic Claude Sonnet 4.6 (voice agent LLM) | REUSABLE | Same vendor, same key |
| Deepgram transcriber | REUSABLE | No change |
| ElevenLabs TTS | REUSABLE | New voice persona acceptable but not required for v1 |
| Inbound DID (phone number) | NEW | Separate +1 number recommended (§1 RESEARCH) |
| Customer lookup (`lookup_b2b_caller`) | NEW | B2B-specific table + tool |
| Entry / triage agent prompt | REUSABLE-with-new-prompt | "Klaravex B2B Triage" replaces Klara persona |
| Specialist agent prompts (Engineer, Security, vCISO, Account) | NEW | 4 new prompts, mirror consumer pattern |
| NATO-phonetic email collection | REUSABLE | Same micro-flow, used in sales-intake branch |
| Dropped-call recovery | REUSABLE | Same callback logic |
| `transferCall` between squad members | REUSABLE | Vapi-native, no change |
| `escalate_to_anthony` tool | REUSABLE-with-new-prompt | New severity + tier branching in prompt logic |
| `log_session_outcome` tool | REUSABLE | Schema unchanged; new tier/company fields populated |
| Payment tool (`send_payment_link`) | REPLACED by NEW `attach_to_active_subscription` | B2B is subscription-based |
| Calendly scheduling tool | REUSABLE | Same tool, new use case (vCISO blocks) |
| Helper app (binary) | REUSABLE | Same Win/macOS build |
| Relay server | REUSABLE | Same Hetzner CX22 instance |
| Vision LLM (Claude Opus 4.7) | REUSABLE-with-new-prompt | Same model, enriched system prompt for managed endpoints |
| Action-confirmation gate | REUSABLE-with-new-config | Softer for pre-approved managed-endpoint actions |
| Code-signing certs (Sectigo EV + Apple Dev) | REUSABLE | Same cert covers both flows |
| RMM agent push for helper install | NEW | Depends on RMM selection (RESEARCH) |
| `create_ticket` tool | NEW | RMM-agnostic adapter |
| RMM vendor + integration adapter | NEW (RESEARCH) | NinjaOne / Syncro / Action1 bake-off at first LOI |
| Loki proactive outbound on RMM alerts | NEW | Phase 6 — defer if it delays v1 |
| Tier-aware SLA logic | NEW | Prompt-level + escalation-tool branching |
| Sales-intake flow (unknown-caller branch) | NEW | Prospect qualification, hand off to Anthony |
| Audit-log rollup into monthly customer report | NEW | Reporting pipeline, not voice-flow itself |

**Count: 14 REUSABLE / REUSABLE-with-new-prompt entries, 11 NEW entries, 3 RESEARCH gates (separate DID, out-of-scope detection rules, RMM vendor selection).** The substrate carries most of the load; the B2B-specific build is concentrated in prompts, the customer lookup, the RMM adapter, and the subscription-attachment tool.
