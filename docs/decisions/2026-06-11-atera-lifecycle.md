# Decision: Atera RMM lifecycle (revised 2026-06-12)

> **REVISION 2026-06-12 (G33):** This doc previously recommended Option 4 (SWITCH —
> cancel Atera). That recommendation is **REVERSED**. Atera **STAYS**. The trigger
> for the reversal is Atera's release of **Robin** (formerly "IT Autopilot") — an
> autonomous AI IT technician that closes ~80% of tier-1 endpoint tickets without
> a human. Robin is exactly the "AI connects to and fixes the machine" product the
> consumer flow was being built from scratch for, and it is shipping today on the
> B2B managed-endpoint surface where Atera's agent is already deployed. The original
> premise ("Atera killed the Splashtop SOS API → Atera delivers $0/mo") predated
> Robin and is no longer accurate for the B2B side. The consumer side ($79 one-off,
> no pre-deployed agent) is genuinely outside Atera's reach and is covered by
> a separate decision doc — see `2026-06-12-consumer-ai-remote-transport.md` (G32).
>
> The four-option analysis below is retained for the historical record; the
> updated recommendation is in the section "Revised recommendation (2026-06-12)".

## Context

Atera is the all-in-one RMM (Remote Monitoring & Management) platform Klaravex pays ~$149/month (~$1,800/year) for, intended to cover both consumer-side remote support (via Splashtop SOS bridge) and B2B endpoint monitoring/patching/scripting. As of 2026-06-11, Atera has removed the `/api/v3/splashtop-sos-session` endpoint — direct verification of the API token Custom Access scope picker shows no Splashtop/SOS/Remote-Session scope is available, which means the **consumer** voice flow's only Atera dependency is now dead.

What changed on 2026-06-12: Atera's **Robin** (autonomous AI tier-1 closure) is the B2B product that justifies the platform on its own, independent of consumer Splashtop. The B2B value proposition is no longer "$0/mo until first B2B client" — it is "the autonomous-AI MSP the rest of the brand is built on, already running, $149/mo flat."

## Four options analyzed (original, retained for history)

### Option 1: KEEP — pay $149/mo, status quo
- Monthly cost: $149
- Value delivered: $0/mo until first B2B client signs and is onboarded
- Risk: opportunity cost of ~$1,800/yr on a tool earning nothing for the next 3-6+ months; if first B2B revenue slips to month 9, that is ~$1,350 of pure burn
- Upside: agent is ready to deploy immediately when first B2B client signs — no re-procurement friction, no day-of-sale delay
- Hidden costs: continued time spent maintaining Atera config (alert templates, script library, customer/contact records) that may need to be redone anyway if Atera changes pricing or scope before B2B activation; mental tax of seeing a $149 line item monthly with no attached revenue

### Option 2: PAUSE — call Atera, ask to suspend without losing config/data
- Monthly cost: $0 (if Atera supports this — research-needed; suspension/hibernation is not advertised on Atera's pricing page)
- Value delivered: $0/mo
- Risk: Atera's standard SMB MSP plans historically do NOT offer formal "pause" — the most likely outcome of the call is a downgrade offer or a churn-save discount, not a true freeze; config data retention period after downgrade is unclear
- Action required: call Atera billing/retention team, explicitly ask for (a) account suspension terms, (b) data retention window, (c) reactivation pricing guarantee
- Reversal trigger: B2B client #1 signs LOI

### Option 3: CANCEL — full cancellation, reactivate via fresh signup later
- Monthly cost: $0
- Value delivered: $0/mo
- One-time cost when re-signing: ~$0 setup fee, but 2-5 days of re-configuration work (alert rules, script library, customer records, Splashtop wiring if/when restored, API token regeneration, integrations)
- Risk: Atera's per-technician pricing may rise between now and reactivation (industry-wide RMM pricing trended up 5-10%/yr through 2025); current sub-$150/tech rate may not be available later; consumer Splashtop SOS endpoint may stay removed, reducing future value
- Reversal trigger: B2B client #1 signs LOI

### Option 4: SWITCH — cancel Atera, evaluate alternatives when B2B pipeline materializes

Cancel Atera now; defer RMM selection until a B2B prospect is in active LOI/contract conversation. At that point, run a structured 1-week eval against current market (NinjaOne / Syncro / Action1 / Pulseway / N-able / Datto). Approximate 2026 pricing ranged from "free for first 200 endpoints" (Action1) to "~$139/tech/mo unlimited endpoints" (Syncro) to per-endpoint plans at the others.

## Original recommendation (2026-06-11, now superseded)

**Option 4: SWITCH** — cancel Atera, evaluate alternatives when B2B pipeline materializes. Rationale at the time: Atera delivered $0 of value and the realistic timeline to first B2B revenue was 3-6+ months; better to hold the $1,800/yr as runway.

## Revised recommendation (2026-06-12): Option 1 — KEEP

**KEEP Atera at $149/mo. Reverse the cancellation. Enroll Robin as soon as the per-seat add-on is available.**

### Why the math flipped

Robin is now the B2B AI tier-1 product:
- Investigates endpoint tickets autonomously (reads alerts, agent telemetry, ticket history).
- Decides on a remediation from a library of pre-approved actions.
- Executes the action directly on the endpoint via the Atera agent (service restarts, patch installs, registry edits, script invocations from the enabled script library, cache flushes, network resets).
- Verifies the outcome (post-action telemetry, ticket auto-close criteria).
- Closes the ticket with a written summary or escalates to Anthony if confidence is low.

Atera reports ~80% of tier-1 incidents close autonomously in customer pilots. Even if Klaravex experiences 50–60% in early production, that is the difference between "Anthony pages out at 2am for a stuck print spooler" and "Loki/Robin handles it before Anthony wakes up." That is the AI-native MSP differentiator the whole brand is positioned around.

This collapses two cost lines that were previously double-counted:
- Old plan: Atera @ $149/mo as B2B RMM **plus** a custom from-scratch "AI fixes B2B endpoints" build (~6-9 months engineering, ongoing maintenance, no IP moat unless we go deep on training).
- New plan: Atera + Robin as B2B RMM-with-autonomy, plus a much smaller from-scratch build that targets ONLY the consumer screen-control flow (G34 RustDesk controller — narrowly scoped, $79 one-off use case).

### Value delivered now (not $0)

Even without B2B revenue today, KEEP is no longer "burning $1,800/yr for nothing":
- Robin demos directly to B2B prospects — every pre-sales conversation can show autonomous tier-1 closure on the prospect's own test endpoint within minutes. That is a closing tool, not a back-office tool.
- Patch management and endpoint visibility on Anthony's own machines and the Klaravex LLC / future GmbH workstations is real value Klaravex needs anyway for SOC 2 / ISO 27001 readiness work. Atera serves double duty as Klaravex's own RMM and the demo environment.
- Atera ticketing + alerting + reporting is the audit surface that compliance buyers (HIPAA, SOC 2, ISO 27001) ask to see during readiness engagements. Showing up empty-handed costs deals.

### Why not Option 2 (PAUSE)

Pausing forfeits the Robin demo surface. If Anthony is about to put Klaravex in front of B2B prospects in the next 1-3 months, a paused account is not a demo account.

### Why not SWITCH-to-Syncro / Action1

Both are still cheaper at first-client scale, but neither has shipped an in-platform autonomous AI tier-1 closer at parity with Robin. Action1's roadmap mentions AI patch advisories; Syncro's is "coming." Robin is shipping. The cheaper RMMs save ~$1,000-1,500/yr but cost the AI-MSP positioning, which is the entire wedge.

If Robin later turns out to be marketing more than substance (see Open questions below), SWITCH is still a clean reversal at any time — Atera does not have multi-year contract lock-in at this tier.

### Reversal trigger for this revised decision

Re-open this decision if any of the following:
- Robin per-seat add-on pricing comes back >$30/endpoint/mo (would cannibalize Foundation tier margin at scale).
- 3-month production sample shows Robin autonomous-close rate <40% (well below the 80% claim, and below the threshold where Anthony's hours saved justifies the add-on).
- A direct B2B competitor (NinjaOne, Datto, Pulseway, Action1) ships a comparable autonomous-AI feature at materially lower cost.

## Companion decisions

- **B2B AI transport — adopt Robin vs. Loki-drives-Atera-API:** `docs/decisions/2026-06-12-b2b-ai-transport-path.md` (G33 deliverable 2).
- **Consumer screen-control transport — RustDesk self-hosted vs from-scratch vs agent-RDP:** `docs/decisions/2026-06-12-consumer-ai-remote-transport.md` (G32 deliverable).

## Action items (Loki-executable)

- [x] Reverse cancellation: cancellation NOT to be filed; Atera subscription continues at $149/mo.
- [ ] Anthony: contact Atera AM, request to be added to Robin private beta / GA waitlist; confirm per-seat add-on pricing.
- [ ] Loki: when Robin GA pricing is published, update Klaravex unit-economics in `SUMMARY.md` with Robin's $/endpoint/mo against Foundation/Assurance/Directive seat economics.
- [ ] Loki: prepare Robin-driven demo script for the next 3 B2B prospect calls (1-page, talking points + "let me show you Robin close a ticket in real time on YOUR test box" hook).

## Open questions for Anthony (revised set)

- Has the Atera AM confirmed Robin is generally available on the current SMB MSP plan, or is it gated behind a higher tier / private beta?
- What is Robin's actual per-endpoint or per-seat add-on price?
- Is Robin's action library limited to pre-approved categories, or can Klaravex authorize custom scripts to expand its autonomy ceiling?
- Does Robin's autonomy create any new liability exposure that the bound Cowbell cyber policy doesn't already contemplate (specifically: AI acting on a customer's endpoint without a human in the loop)?
- Should Klaravex name Atera + Robin in the MSA / SOW templates as the standard RMM stack, or stay vendor-neutral in client paperwork in case of a future switch?
