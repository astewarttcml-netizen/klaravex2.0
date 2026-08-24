"""Pillar 2 — Regulatory Readiness Engineer.

Owns the **Regulatory Readiness** pillar on klaravex.com end-to-end:
HIPAA · SOC 2 · ISO 27001 · multi-state US privacy · GDPR DPA · NIS2 advisory.

ABSOLUTE: this is READINESS ADVISORY only. Klaravex does not certify, audit,
or attest. Never use the word 'compliance' as a promise — use 'readiness',
'preparation', or 'advisory'.
"""
from .base import EngineerAgent


class RegulatoryReadinessEngineer(EngineerAgent):
    name = "engineer_regulatory_readiness"
    display_name = "Regulatory Readiness Engineer"
    pillar = "regulatory_readiness"
    website_anchor = "https://klaravex.com/services#regulatory-readiness"

    expertise = (
        "HIPAA Security Rule (45 CFR §164.30x) gap analysis and remediation "
        "support, SOC 2 Type II readiness across CC1–CC9, ISO 27001 ISMS "
        "scaffold and Statement of Applicability, multi-state US privacy "
        "advisory (CCPA · CDPA · VCDPA · CTDPA), GDPR DPA drafting for US-LLC "
        "data processor engagements, NIS2 scope screening, policy and "
        "procedure development, risk register maintenance, cyber-insurance "
        "questionnaire response, attestation evidence collection."
    )

    system_prompt = (
        "You own the **Regulatory Readiness** pillar at Klaravex. From "
        "klaravex.com: 'Readiness-native, not readiness-adjacent. We speak "
        "HIPAA, SOC 2, and ISO 27001 as primary languages — not afterthoughts "
        "bolted onto a helpdesk practice.' Your pillar is what unlocks "
        "Directive-tier engagements and protects the firm from scope creep "
        "into assessment/certification.\n\n"
        "PRIMARY SCOPE: HIPAA Security Rule gap analysis, SOC 2 CC1–CC9 "
        "preparation, ISO 27001 ISMS + SoA, multi-state US privacy, GDPR DPA "
        "for US-LLC processor work, NIS2 scope screening, policy + procedure "
        "drafting, risk register, attestation evidence.\n\n"
        "T-SHAPED — you also wear multiple hats and BACK UP these pillars: "
        "Strategic Advisory (board-level risk summaries, cyber-insurance "
        "questionnaires), Managed Security (the technical safeguard layer). "
        "Pull in the pillar owner by name when you need their specialty.\n\n"
        "ABSOLUTE RULES:\n"
        "  - Klaravex provides READINESS ADVISORY only. We do NOT issue or "
        "assert certifications. Use 'readiness', 'preparation', or 'advisory'. "
        "Never 'compliance' as a promise.\n"
        "  - Every gap analysis must cite the specific control number "
        "(45 CFR §164.30x for HIPAA; CC1.x–CC9.x for SOC 2; A.x.y for ISO).\n"
        "  - Every recommended control must include: (1) the citation, "
        "(2) the current gap, (3) the recommended remediation, (4) the "
        "evidence the client must retain.\n"
        "  - For breach-related questions, recommend Anthony review before "
        "any communication leaves the firm. Never give the client legal advice."
    )

    specialty_keywords = [
        "hipaa", "phi", "baa", "business associate", "security rule",
        "privacy rule", "ocr", "breach notification",
        "soc 2", "soc2", "trust services", "cc1", "cc2", "cc3", "cc4",
        "cc5", "cc6", "cc7", "cc8", "cc9", "carve-out",
        "iso 27001", "iso27001", "isms", "annex a", "statement of applicability",
        "soa", "internal audit", "policy", "procedure", "control",
        "risk register", "risk assessment", "audit", "attestation",
        "evidence", "auditor", "qsa", "compliance", "readiness",
        "cyber insurance", "questionnaire", "underwriter",
        "ccpa", "cdpa", "vcdpa", "ctdpa", "state privacy",
        "gdpr", "dpa", "data processing agreement", "nis2",
    ]
    secondary_keywords = [
        "conditional access", "entra", "intune", "defender",
        "purview", "audit log",
        "firewall", "vpn", "tls", "encryption", "segmentation",
        "siem", "log retention",
        "board", "qbr", "ir plan", "vendor questionnaire",
    ]
    default_skus = [
        "hipaa-gap", "iso27001-readiness", "attestation-prep",
        "cir-small", "cir-medium", "cir-large", "it-audit",
    ]
    documentation_targets = [
        "HIPAA Security Rule gap analysis template",
        "HIPAA BAA template (Klaravex as Business Associate)",
        "SOC 2 CC1–CC9 control crosswalk to Klaravex services",
        "ISO 27001 ISMS scope statement template",
        "ISO 27001 Statement of Applicability template (Annex A)",
        "Multi-state US privacy scope screening tool (CCPA/CDPA/VCDPA/CTDPA)",
        "GDPR DPA — US-LLC processor template (klaravex.com side)",
        "GDPR DPA — EU processor template",
        "NIS2 scope screening checklist (essential vs important)",
        "Cyber-insurance questionnaire response library",
        "Information security policy set (12 policies covering CC1–CC9)",
        "Risk register template + recurring review cadence",
        "Attestation evidence collection runbook",
        "Breach response escalation matrix (engineer → Anthony → counsel)",
        "Readiness-only engagement scope disclaimer (every SOW)",
    ]
    backup_pillars = ["strategic_advisory", "managed_security"]
