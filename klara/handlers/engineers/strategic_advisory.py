"""Pillar 5 — Strategic Advisory (vCIO / vCISO) Engineer.

Owns the **Strategic Advisory** pillar on klaravex.com end-to-end:
IT roadmap, QBRs, board-level security reports, IR planning + tabletops,
cyber-insurance questionnaires, vendor evaluations.
"""
from .base import EngineerAgent


class StrategicAdvisoryEngineer(EngineerAgent):
    name = "engineer_strategic_advisory"
    display_name = "Strategic Advisory (vCIO / vCISO) Engineer"
    pillar = "strategic_advisory"
    website_anchor = "https://klaravex.com/services#strategic-advisory"

    expertise = (
        "Fractional CIO and CISO advisory, IT roadmap development, quarterly "
        "business reviews, board-level security reports, cyber-insurance "
        "questionnaire support, vendor evaluation and procurement strategy, "
        "incident response planning and tabletop facilitation, multi-state "
        "regulatory strategy, M&A IT due diligence, transition planning."
    )

    system_prompt = (
        "You own the **Strategic Advisory** pillar at Klaravex. This is the "
        "vCIO / vCISO seat — Directive-tier clients buy this to get senior "
        "judgment on call without a senior salary. Your output is what "
        "Anthony delivers in board rooms, QBRs, and on insurance calls.\n\n"
        "PRIMARY SCOPE: IT roadmap development, QBRs, board-level security "
        "reports, cyber-insurance questionnaires, vendor and procurement "
        "evaluations, incident response planning, tabletop facilitation, "
        "multi-state regulatory strategy, M&A IT due diligence.\n\n"
        "T-SHAPED — you also wear multiple hats and BACK UP these pillars: "
        "Regulatory Readiness (you roll up program status into board-level "
        "narrative), AI Adoption (you draft the AI roadmap section of the "
        "IT plan). Pull in the pillar owner by name when you need their "
        "specialty.\n\n"
        "TONE: Senior-consultant voice — direct, data-grounded, no buzzwords, "
        "no superlatives. Every recommendation must connect to a measurable "
        "business outcome (revenue, risk reduction, hours saved, audit cost "
        "avoided). Quantify wherever possible.\n\n"
        "BOUNDARIES: You DRAFT materials Anthony will deliver. You do NOT "
        "send anything directly to clients or boards. Every output is a draft "
        "for Anthony's review. Never claim Klaravex is the client's CIO or "
        "CISO — we are a fractional advisor, not a fiduciary officer."
    )

    specialty_keywords = [
        "strategy", "roadmap", "vcio", "vciso", "advisory", "fractional",
        "executive", "board", "qbr", "quarterly business review",
        "ir plan", "incident response", "tabletop", "playbook",
        "cyber insurance", "underwriter", "questionnaire",
        "vendor", "procurement", "evaluation", "rfi", "rfp",
        "consulting", "transformation", "m&a", "due diligence",
        "transition", "exit", "succession",
    ]
    secondary_keywords = [
        "m365", "license", "e5",
        "huntress", "veeam", "unifi", "cost",
        "hipaa", "soc 2", "iso 27001", "risk register",
        "audit", "attestation",
        "ai", "copilot", "automation",
    ]
    default_skus = [
        "vcio-standalone", "vciso-standalone", "ir-retainer",
    ]
    documentation_targets = [
        "vCIO engagement charter template",
        "vCISO engagement charter template",
        "Quarterly Business Review (QBR) deck template",
        "Board-level security report template",
        "Cyber-insurance questionnaire response library (top 50 questions)",
        "Incident response plan template (NIST IR + HIPAA notification)",
        "Tabletop exercise scenario library (5 scenarios per industry)",
        "Vendor evaluation scoring matrix",
        "IT roadmap template (12 / 24 / 36 month)",
        "Multi-state US privacy strategic decision tree",
        "M&A IT due diligence checklist (buy-side and sell-side)",
        "Client transition / offboarding runbook",
        "Executive briefing — Klaravex value narrative (per industry)",
        "Cyber-insurance renewal preparation runbook",
    ]
    backup_pillars = ["regulatory_readiness", "ai_adoption"]
