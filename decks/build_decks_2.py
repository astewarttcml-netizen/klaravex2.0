#!/usr/bin/env python3
"""Investor + technical audience decks (2026-08-24). Reuses helpers."""
import importlib.util, sys
spec = importlib.util.spec_from_file_location(
    "base", "/home/anthony/klaravex/decks-2026-08-24/build_decks.py")
# Import helpers without re-running deck builds: read file, exec up to marker.
src = open("/home/anthony/klaravex/decks-2026-08-24/build_decks.py").read()
helpers = src.split("# ---------------------------------------------------------------- Deck 1")[0]
ns = {}
exec(helpers, ns)
new_deck = ns["new_deck"]; title_slide = ns["title_slide"]
bullets_slide = ns["bullets_slide"]; stat_slide = ns["stat_slide"]
flow_slide = ns["flow_slide"]; cta_slide = ns["cta_slide"]
Presentation = ns["Presentation"]
OUT = "/home/anthony/klaravex/decks-2026-08-24/"

# ------------------------------------------------------------ Investor deck
prs = new_deck()
title_slide(prs, "Klaravex LLC — investor overview",
            "The AI-first managed IT company",
            "Managed IT and security for US SMBs where AI resolves 89% of issues "
            "instantly and senior judgment handles the rest — at margins a "
            "labor-based MSP cannot reach.", dark=True)
bullets_slide(prs, "The problem", [
    ("SMBs are priced out of real IT security", "Compliance-grade IT (HIPAA, SOC 2, ISO 27001 readiness) is enterprise-priced because it is delivered with enterprise headcount."),
    ("The MSP model is structurally conflicted", "Per-ticket billing rewards a full queue; vendor commissions shape recommendations; the people reporting on environment health are the ones responsible for it."),
    ("Consumers have nowhere honest to go", "A house call costs more than the device; urgency-driven scam 'help' preys on the vulnerable."),
])
bullets_slide(prs, "The product answer — two surfaces, one engine", [
    ("klaravex.com (B2B)", "AI-first managed IT & security. Flat fee per user ($75–250 across three tiers), 2-hour senior response with service credits, zero vendor commissions. Leads with the premium Directive tier: compliance readiness + MDR + vCISO."),
    ("personal.klaravex.com (consumer)", "Klaravex AI, always labeled as AI. $29 sessions, plans from $29/month, free scam & hack recovery. Remote-only economics."),
    ("One AI engine underneath", "Voice, SMS, chat, and email converge on the same AI coordinator, guardrails, and escalation policy."),
])
stat_slide(prs, "Unit economics of AI-first delivery", [
    ("89%", "of support volume resolved by AI at near-zero marginal cost"),
    ("11%", "senior-judgment work — the only labor in the loop"),
    ("$75–250", "per user per month, flat — recurring, predictable"),
    ("24/7", "coverage in every time zone with no night-shift payroll"),
], footer="Every point of AI resolution is gross margin a labor-based MSP has to buy with headcount.")
bullets_slide(prs, "The moat: the company runs on its own product", [
    ("Autonomous engineering loop", "A closed reason–act–review–verify cycle ships features against a versioned PRD with quality gates, council review, and trust tracking."),
    ("Growth OS", "Autonomous revenue streams — leads, outreach, content, SEO — on independent schedulers with human-gated publishing. Revenue cadence survives even if the ops layer dies."),
    ("Operator console", "The entire company — delivery, pipeline, finances, agent fleet — on one screen with honest status. Built for one operator today; the multi-tenant version is the future product."),
    ("Radical-transparency brand", "AI always labeled, no fake reviews, public agent experiments. Trust as a durable differentiator in a low-trust market."),
])
bullets_slide(prs, "Go-to-market", [
    ("Founder-led wedge", "Warm B2B network from years of hands-on engagements (foundations, legal aid, professional services) — free written assessments as the opener."),
    ("Verticals with compliance pain", "Small law firms, accounting practices, medical offices — where the Directive tier is bought, not sold."),
    ("Autonomous top-of-funnel", "Growth OS streams generate leads, proposals, and content on cadence — with a public AI-agent scoreboard experiment as proof of governance."),
    ("Consumer as brand + volume", "Free scam recovery builds goodwill and word of mouth in exactly the demographic that buys the Family plan."),
])
bullets_slide(prs, "Where investment goes", [
    ("Scale the AI operations layer", "Dedicated inference infrastructure as ARR crosses the committed scaling trigger."),
    ("Cut over Growth OS streams", "From shadow mode to full autonomous cadence with human gates."),
    ("Productize the operator console", "Single-operator today → multi-tenant operating console as a second product line."),
    ("[Traction + financials]", "Placeholder — current MRR, pipeline, and 12-month plan to be added from live scorecards before any external send."),
], footer="This deck contains no fabricated traction numbers; bracketed sections need real figures before it leaves the building.")
cta_slide(prs, "AI-first services, honestly delivered",
          ["Anthony Stewart — Klaravex LLC (Wyoming)",
           "hello@klaravex.com · (833) 990-2069"],
          "klaravex.com")
prs.save(OUT + "00-investor-overview.pptx")

# ------------------------------------------------------------ Technical deck
prs = new_deck()
title_slide(prs, "INTERNAL / TECHNICAL — Klaravex platform",
            "Architecture deep dive",
            "How the production monolith, the Growth OS strangler-fig, and the "
            "operator console fit together — crash domains, control planes, and "
            "the policy layer that binds every actor.", dark=True)
bullets_slide(prs, "Production monolith: four concentric layers", [
    ("1 — Marketing/edge", "Bun + React + TypeScript public site with the chat widget, served via Bun.serve()."),
    ("2 — Infra runtime", "FastAPI handlers and integrations: voice, SMS, billing, mail via Graph, remote sessions, freelance-bid pipeline, admin console/portal, dunning, migration tooling."),
    ("3 — Autonomous ops loop", "Closed RARV-C cycle (Reason–Act–Review–Verify–Converge): artifact manifests, static analysis + pytest gates, council votes, trust trajectory, continuity log."),
    ("4 — Knowledge & policy", "The hard policy contract every actor reads first: memory policy, note_submissions logging, Pattern 32 routing."),
])
flow_slide(prs, "Event-driven, handler-per-surface", [
    ("Inbound edge", "Webhooks: voice, SMS, billing, mail, freelance platforms, remote-session events, WhatsApp."),
    ("Dispatcher", "Six engineer pillars in a registry; each scores tickets via matches_ticket() — no substring routing."),
    ("Guardrails", "Shared input/output filters on every AI surface; dual-secret escalation so one env regression can't break the path."),
    ("Outbound", "Deliberately narrowed: cold outreach only via the outreach platform, transactional mail only via Graph."),
    ("Human loop", "Admin inbox + dark-theme portal: bids, denials, webhook failures, approvals."),
], footer="Migrations apply only through a gated internal endpoint with path-traversal validation.")
bullets_slide(prs, "Data & session architecture", [
    ("Pattern 32 routing", "Surface TLD determines the database target (US → Azure Postgres). Unmapped surfaces hard-fail; a pre-flight gate enforces it at session start."),
    ("Chat session model", "Widget obtains a session token from /chat/start; the agent persists history per token with tool-calling (payments, leads, escalation) on top."),
    ("Memory discipline", "Every mutation logs a note_submissions row at action time — the audit trail is the product's nervous system."),
])
flow_slide(prs, "Growth OS: strangler-fig layers", [
    ("A — Charters + outbox", "Revenue-agent behavior as versioned charters; drafts land in a local outbox (source of truth)."),
    ("B — n8n glue", "Optional orchestration; calls the Growth API, never owns rubrics."),
    ("C — Growth API + timers", "FastAPI control plane (:4210), systemd timers per stream, charter executor running Claude in background threads. Independent of Celery beat."),
    ("D — KLARAVEX-OS", "Next.js operator cockpit (:4100) — talks to C exclusively for growth."),
], footer="Phase 2 shadow today. Cutover order: leads → freelance/ads → gated publish chain → gatekeeper. Phase 4 is a deliberate beat-kill test.")
bullets_slide(prs, "Crash domains & failure design", [
    ("Three isolated domains", "Product runtime (monolith) · Growth cadence (systemd) · Operator console (Next.js/Postgres). Any one can die without taking the others."),
    ("HA topology", "Primary rig + US watchdog VM: streaming Postgres standby, failure detector off-primary, hot-standby service instances, edge proxy."),
    ("Honest degradation", "Consoles show real connector status; silent failure is treated as failure (scorecards, watchdog escalation)."),
    ("Rollback as a first-class path", "Per-stream rollback: disable timer, re-enable legacy schedule, keep the new outbox as forensic replay."),
])
bullets_slide(prs, "Security posture", [
    ("Secrets", "1Password-injected environments; credential wiring logged by variable name, never value."),
    ("Web surface", "CSP with explicit script/connect allowlists, security-header parity across sites, origin allowlists + rate limits on public AI endpoints."),
    ("AI safety rails", "Input/output guardrails, GDPR consent gates, message-length caps, labeled-AI policy enforced at two boundaries."),
    ("Change control", "Gated migrations, pre-deploy rollback points, post-deploy verification, host-key hard-stops on SSH."),
])
cta_slide(prs, "Questions welcome — the code is the spec",
          ["klaravex (production) · Klaravex2.0 (Growth OS) · klaravex-os (cockpit)",
           "Architecture docs: ARCHITECTURE.md · MIGRATION.md · TOPOLOGY.md"],
          "internal / technical audience")
prs.save(OUT + "05-technical-architecture.pptx")

print("done")
for f in ["00-investor-overview", "05-technical-architecture"]:
    p = Presentation(OUT + f + ".pptx")
    print(f, "slides:", len(p.slides._sldIdLst))
