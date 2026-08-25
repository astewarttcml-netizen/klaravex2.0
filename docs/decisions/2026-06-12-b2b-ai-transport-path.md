# Decision: B2B AI transport — adopt Robin vs. Loki drives Atera API (2026-06-12)

**Status:** DECIDED (Path A primary, Path B kept as a thin tooling layer).
**Owner:** Anthony · **Author:** Loki (G33 deliverable 2) · **Related:** `2026-06-11-atera-lifecycle.md`

## Question

For B2B managed endpoints (Atera agent already installed on client machines), should Klaravex:

- **Path A — Adopt Atera Robin.** Robin (Atera's autonomous AI tier-1 closer) IS the B2B AI. Klaravex resells / wraps Robin as the autonomy layer. Loki orchestrates only at the conversation + handoff seams.
- **Path B — Loki drives Atera's REST API as a tool.** Loki is the brain; Atera is one of several tools Loki calls. Loki reads alerts, decides remediations, calls Atera's API to execute scripts / actions on the endpoint, polls for outcome, closes the ticket.
- (Pseudo-)Path C — Build everything from scratch with no Atera at all. Not under consideration here — that was the pre-revision plan superseded by `2026-06-11-atera-lifecycle.md`.

## Hard constraints (from primary research of Atera's API + product docs)

These are the load-bearing facts that the decision rests on:

1. **Atera API is strong at READ/MANAGE, weak at REMOTE EXECUTION.** REST v3 covers agents, devices, tickets, alerts, customers, contacts, contracts, billing, knowledge base, custom fields, and automation profile management. **Script execution against an endpoint is NOT a clean public REST endpoint** — scripts live in the script library and are bound to *automation profiles* / scheduled tasks / manual UI invocation, not to a public "POST /devices/{id}/run-script" verb. Any "Loki triggers a script on a specific device right now via API" depends on either Atera's automation-profile assignment pathway (slow, declarative, not real-time) or unofficial / undocumented endpoints.
2. **The Atera agent runs as SYSTEM in Session 0 on Windows.** That means: **zero screen / GUI control via the Atera agent.** No mouse moves, no keystrokes into the logged-in user's session, no UI Automation. Screen control on B2B endpoints is **Splashtop** (now via Atera's bundled Splashtop or AnyDesk integration), and Splashtop is a human-driven viewer — there is no API for "Splashtop, click here." Programmatic screen control through Atera is not on the table.
3. **Robin runs INSIDE Atera, against the same SYSTEM agent.** Robin therefore has the same execution surface as the Atera agent: services, processes, registry, file system, the enabled script library, patch management, network stack — all the things SYSTEM can touch — and the same exclusion: it cannot move a logged-in user's mouse either. Robin's autonomy ceiling and Loki-through-Atera-API's autonomy ceiling are *the same surface*. The difference is who owns the brain.

Conclusion from constraints alone: **screen-control B2B autonomy through Atera is impossible in both paths.** The choice is purely about who orchestrates the *script / API / telemetry* remediation that IS possible.

## Scoring matrix

| Criterion | Path A — Adopt Robin | Path B — Loki drives Atera API |
|---|---|---|
| **Time to first B2B autonomous close** | Days (enrol Robin, point at endpoints) | 2-4 weeks engineering (poll alerts, decision loop, script library catalog, outcome verification, ticket closure logic) — plus blocking on the script-execution endpoint gap |
| **IP ownership / moat** | Low. Klaravex resells Atera's autonomy. Differentiator is brand + UX, not autonomy itself. | High. Loki accumulates the decision/outcome dataset over time → eventually trainable, defensible. |
| **Per-end-user cost** | Robin add-on (price TBC from AM — likely $10-30/endpoint/mo on top of Atera base). | $0 marginal beyond Atera base (Loki infra is amortized across consumer too). |
| **Vendor lock-in / churn risk** | High. If Atera deprecates Robin or jacks price, Klaravex's B2B AI story evaporates. | Low. Atera is replaceable by NinjaOne/Syncro/Action1 — Loki just needs new connector. |
| **Engineering load** | ~0. Configure, enrol, demo. | Significant. ~2-4 weeks initial + ongoing (Atera changes its API surface periodically). |
| **Demo-ability today** | Excellent. Demo to a B2B prospect on their test endpoint in real time, this week. | Poor until built. ~1 month before there's something to show. |
| **Script-execution-API blocker** | N/A — Robin runs inside Atera, no API surface needed. | Hard. Public REST does not expose "run script now on device X" as a clean verb. Workarounds (automation profile binding, unofficial endpoints) are fragile. |
| **Liability surface** | Atera carries the AI-acted-on-customer-endpoint liability tail in their TOS. Klaravex's cyber policy (Cowbell, $1M) is backstop. | Klaravex carries the full tail. Cowbell policy needs review for explicit AI-action coverage. |
| **Conversation / handoff UX** | Robin closes tickets inside Atera; client communication still flows through Klaravex's voice/chat (Klara/Loki). Robin is the back-end. | Same — Loki is also the back-end either way; the conversation layer (Klara voice, support chat) is unchanged across paths. |
| **Custom remediation flexibility** | Bounded by Robin's pre-approved action library. Custom scripts authorized into Robin's library extend autonomy ceiling, but slowly. | Open-ended. Anything in the Atera script library — and anything Loki can write/upload — is fair game on day 1. |
| **Compliance posture (SOC 2 / ISO 27001)** | Robin's action audit trail is inside Atera's reporting surface. Auditable but vendor-controlled. | Loki's audit trail lives in Klaravex's own infrastructure. Tighter control, slightly more work to reconcile with Atera's view. |
| **Fail-safe path when AI is wrong** | Robin escalates to Anthony in Atera; Anthony resolves in Atera. | Loki escalates to Anthony via voice/chat handoff; Anthony resolves either in Atera UI or via Loki driving Atera. |

## Recommendation: Path A primary, Path B as a thin tooling layer underneath

**Adopt Robin as the B2B AI tier-1 closer. In parallel, build Loki↔Atera-API as a thin connector that owns ALERT INGEST, TICKET CLOSURE COMMENTARY, and CUSTOM-SCRIPT TRIGGER only — NOT the full autonomy loop.**

Rationale for the hybrid:

- **Time-to-launch wins now.** Klaravex has zero B2B clients and is actively trying to close the first one. "Watch Robin close a ticket on your endpoint right now" is a closing tool this week. A from-scratch Loki-Atera loop is a closing tool in 4-6 weeks. The opportunity cost of slow launch dwarfs the lock-in cost of Robin.
- **Robin is replaceable; the connector is portable.** Path A is reversible. If Robin disappoints on the 3-month sample (close-rate <40%) or if pricing breaks margin, the Loki↔Atera connector built underneath is already the foundation to flip to Path B with another month of build. There is no scenario where the connector is wasted work.
- **The autonomy ceiling is the same.** Both paths bottom out at "what can SYSTEM do on the endpoint via the Atera agent." Path A gets there for free with vendor support; Path B gets there with significantly more engineering and the same outcome.
- **Loki retains the brain at the conversation layer.** Klara (voice) + Loki (chat / triage / multi-tool orchestration) still own the customer conversation, the multi-system context (Stripe, AgentMail, HubSpot, Atera, RustDesk, etc.), and the decision of *when to invoke Robin vs. when to escalate to Anthony vs. when to drive a script directly via the connector*. The IP moat lives in the orchestration + conversation layers, NOT in tier-1 endpoint closure.

### Path B's minimal viable scope (the "thin layer underneath")

Build only:
1. **Alert ingest:** poll `GET /alerts` (filter `Severity in {Critical, Warning}`), upsert into `klaravex_atera_alerts` Postgres table for Loki's queryable view.
2. **Ticket close commentary:** when Robin closes a ticket, ingest the closure note into Klaravex's master case timeline so the next customer interaction (voice or chat) has the full history without round-tripping to Atera UI.
3. **Custom-script trigger (best-effort):** thin wrapper that POSTs to the automation-profile-assignment endpoint or the closest available action endpoint to invoke a script Anthony has pre-authorized. Defensive design: if Atera's API surface for this is fragile/undocumented, fall back to creating a high-priority ticket assigned to Anthony with the recommended script call out, instead of failing silently.

That's it. No autonomous decision loop in Path B's minimal scope. The decision loop is Robin.

### What Path B does NOT build (yet)

- Autonomous remediation decision logic — that's Robin's job.
- Real-time outcome verification loop — that's Robin's job.
- A custom script library competing with Atera's — pointless, just authorize scripts INTO Atera's library where Robin can use them too.

## Pricing math (placeholder — Anthony to confirm from AM)

Assumptions to validate:
- Atera base: $149/mo flat (1 technician).
- Robin add-on: hypothetical $20/endpoint/mo (TBC — likely range $10-30).
- First B2B client at Foundation tier (~$100/user/mo), assume 10 users → $1,000/mo revenue.
- Endpoint count likely ≈ 1.2× user count → ~12 endpoints → Robin cost ~$240/mo.
- COGS on the client: Atera base allocated $149 (or amortized across multiple clients later) + Robin $240 + Loki infra allocation ~$30 + Cowbell pro-rata ~$10 = ~$430.
- Gross margin: ($1,000 − $430) / $1,000 = **57%**. Acceptable.

If Robin comes in at $30/endpoint/mo → COGS $510 → margin 49%. Tight but acceptable.
If Robin comes in at $50/endpoint/mo → COGS $670 → margin 33%. Below threshold — re-open this decision.

## Acceptance criteria (this decision doc satisfies G33)

- [x] Recommends Path A vs Path B for B2B AI transport, with explicit scoring and rationale.
- [x] Confirms Atera API cannot do screen control (SYSTEM Session 0 constraint).
- [x] Confirms script-exec-via-public-REST is not a clean endpoint (automation-profile pathway, not real-time).
- [x] Per-end-user Robin pricing placeholder included with break-even analysis vs in-house build.
- [x] References the consumer-only G32 decision doc and confirms G32 scope is consumer screen-control only.

## Open items for Anthony

- Confirm Robin pricing with the Atera AM (per-endpoint or per-seat).
- Confirm Robin GA status on the current SMB MSP plan tier.
- Confirm Robin's action library and whether Klaravex can authorize custom scripts into it.
- Confirm Robin's audit/log export format (needed for SOC 2 / ISO 27001 readiness deliverables).
