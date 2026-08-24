"""
A5 archetype — B2B fixed-fee assessment workflow (WORKFLOWS.md §A5).

Cyber-Insurance Readiness is the lead magnet: lowest barrier, fastest
turnaround, direct path to Foundation/Assurance/Directive upsell.

Public surface
--------------
a5_kickoff(sku: str, checkout_session: dict) -> dict
    Triggered by checkout.session.completed for any A5 assessment SKU.
    Idempotent — safe to call multiple times for the same Stripe session.
    Returns {"ticket_id": str|None, "sku": str, "followups_scheduled": int,
             "triage": str}

CIR-specific helpers (also callable standalone)
-----------------------------------------------
run_cir_gap_analysis(ticket_id: str, intake: dict) -> dict
    Execute the checklist-based cyber-insurance gap analysis against the
    provided intake answers.  Returns {"gaps": list[str], "score": int,
    "tier_recommendation": str, "report_text": str}.

build_remediation_roadmap(gaps: list[str]) -> list[dict]
    Convert a list of gap names into a prioritised remediation plan.

generate_cir_report(ticket_id: str, intake: dict, gaps: list[str],
                    roadmap: list[dict]) -> str
    Assemble the full plain-text gap report + remediation roadmap that gets
    delivered to the client.

upsell_recommendation(score: int, intake: dict) -> dict
    Map the CIR score to a managed-service tier (Foundation/Assurance/
    Directive) with a concrete justification paragraph.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import stripe

from .db import get_pool
from .email import send_email
from . import tickets as tickets_lib

log = logging.getLogger("klaravex.assessment_workflow")

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")

# ---------------------------------------------------------------------------
# Per-SKU configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _A5SkuConfig:
    """Everything Klara AI needs to drive a specific A5 assessment SKU end-to-end.

    Fields
    ------
    display_name        Human-readable product name.
    price_usd           List price in whole dollars (display only).
    intake_fields       Ordered list of field names on the intake form.
    turnaround_days     Delivery SLA in business days (per WORKFLOWS.md §A5.5).
    deliverable         One-line deliverable description.
    anthony_role        What Anthony does at minimum in this workflow.
    intake_path         Portal intake form path relative to PORTAL_BASE_URL.
    escalation_note     Extra copy in the confirmation email.
    followup_schedule   Sequence of {offset_hours, template} dicts.
    """
    display_name: str
    price_usd: int
    intake_fields: tuple[str, ...]
    turnaround_days: int
    deliverable: str
    anthony_role: str
    intake_path: str
    escalation_note: str = ""
    followup_schedule: tuple[dict[str, Any], ...] = field(default_factory=tuple)


# A5.6 follow-up schedule — shared across all CIR tiers.
_CIR_FOLLOWUPS: tuple[dict[str, Any], ...] = (
    {"offset_hours": 24 * 7,  "template": "a5_remediation_call_offer"},
    {"offset_hours": 24 * 30, "template": "a5_upsell_directive"},
    {"offset_hours": 24 * 60, "template": "a5_insurance_renewal_countdown"},
    {"offset_hours": 24 * 90, "template": "a5_case_study_request"},
)

_STANDARD_A5_FOLLOWUPS: tuple[dict[str, Any], ...] = (
    {"offset_hours": 24 * 7,  "template": "a5_remediation_call_offer"},
    {"offset_hours": 24 * 30, "template": "a5_upsell_directive"},
    {"offset_hours": 24 * 90, "template": "a5_case_study_request"},
)

A5_SKU_CONFIG: dict[str, _A5SkuConfig] = {
    # ------------------------------------------------------------------
    # Cyber-Insurance Readiness — the lead magnet (WORKFLOWS.md §A5 / PRD)
    # Three size tiers: small (<50 seats), medium (50-250), large (250+)
    # ------------------------------------------------------------------
    "cir-small": _A5SkuConfig(
        display_name="Cyber-Insurance Readiness Assessment (Small Business)",
        price_usd=297,
        intake_fields=(
            "current_insurer",          # carrier name or "none"
            "renewal_date",             # MM/YYYY or "not insured"
            "current_policy_limits",    # e.g. "$1M/$1M" or "unknown"
            "industry",                 # healthcare / legal / finance / other
            "employee_count",           # number of seats
            "primary_environment",      # M365 / GWorkspace / AWS / on-prem / mix
            "existing_controls",        # free text or checkbox list
            "has_incident_response_plan",  # yes / no / draft
            "recent_incidents",         # brief description or "none"
        ),
        turnaround_days=5,
        deliverable=(
            "Gap report (MFA, EDR, backup, IR plan, email security) + "
            "prioritised remediation roadmap + managed-service recommendation — "
            "delivered within 5 business days"
        ),
        anthony_role=(
            "Review automated gap analysis; sign final report; "
            "deliver readout call to client"
        ),
        intake_path="/intake/cir-small",
        escalation_note=(
            "We will reach out within 1 business day to confirm scope and "
            "schedule the optional stakeholder call before delivering your report."
        ),
        followup_schedule=_CIR_FOLLOWUPS,
    ),

    "cir-medium": _A5SkuConfig(
        display_name="Cyber-Insurance Readiness Assessment (Mid-Market)",
        price_usd=597,
        intake_fields=(
            "current_insurer",
            "renewal_date",
            "current_policy_limits",
            "industry",
            "employee_count",
            "primary_environment",
            "existing_controls",
            "has_incident_response_plan",
            "recent_incidents",
            "current_questionnaire_upload",  # upload portal field
        ),
        turnaround_days=5,
        deliverable=(
            "Gap report + remediation roadmap + insurer-specific questionnaire "
            "pre-fill guidance — delivered within 5 business days"
        ),
        anthony_role=(
            "Review and sign gap report; deliver readout call; "
            "optionally join insurer call as vCISO"
        ),
        intake_path="/intake/cir-medium",
        escalation_note=(
            "Please upload your insurer's current questionnaire in the intake "
            "form so we can pre-fill it with your controls inventory."
        ),
        followup_schedule=_CIR_FOLLOWUPS,
    ),

    "cir-large": _A5SkuConfig(
        display_name="Cyber-Insurance Readiness Assessment (Enterprise)",
        price_usd=1197,
        intake_fields=(
            "current_insurer",
            "renewal_date",
            "current_policy_limits",
            "industry",
            "employee_count",
            "primary_environment",
            "existing_controls",
            "has_incident_response_plan",
            "recent_incidents",
            "current_questionnaire_upload",
            "stakeholder_contacts",     # names + roles for interview scheduling
        ),
        turnaround_days=5,
        deliverable=(
            "Full gap report + remediation roadmap + insurer questionnaire "
            "pre-fill + up to 3 stakeholder interviews — delivered within 5 business days"
        ),
        anthony_role=(
            "Deliver up to 3 stakeholder interviews; review and sign report; "
            "deliver executive readout; join insurer renewal call on request"
        ),
        intake_path="/intake/cir-large",
        escalation_note=(
            "We will contact your designated stakeholders within 1 business "
            "day to schedule brief interviews (30 min each, optional but recommended)."
        ),
        followup_schedule=_CIR_FOLLOWUPS,
    ),

    # ------------------------------------------------------------------
    # Other A5 products — wired for kickoff; gap-analysis automation TBD
    # ------------------------------------------------------------------
    "it-audit": _A5SkuConfig(
        display_name="IT Security Audit",
        price_usd=997,
        intake_fields=(
            "environment_inventory",    # M365 tenant ID, AWS account, network
            "employee_count",
            "business_context",         # what the client does, primary risk concern
            "escalation_contact",
        ),
        turnaround_days=7,
        deliverable="IT security audit report + prioritised remediation roadmap",
        anthony_role="Deliver stakeholder interviews; review and sign audit report",
        intake_path="/intake/it-audit",
        followup_schedule=_STANDARD_A5_FOLLOWUPS,
    ),

    "hipaa-gap": _A5SkuConfig(
        display_name="HIPAA Gap Analysis",
        price_usd=1497,
        intake_fields=(
            "phi_workflows",            # how PHI is created, stored, transmitted
            "baa_list",                 # current signed BAAs
            "existing_risk_analysis",   # date of last RA or "none"
            "designated_security_officer",  # name + title
            "primary_environment",
        ),
        turnaround_days=10,
        deliverable="HIPAA gap analysis report + risk register + remediation roadmap",
        anthony_role="Deliver interviews; review and sign report with HIPAA-qualified oversight",
        intake_path="/intake/hipaa-gap",
        escalation_note=(
            "A BAA between Klaravex LLC and your organisation is required before "
            "we can access any PHI-adjacent systems. Klara AI will send you the BAA "
            "template for e-signature immediately after intake."
        ),
        followup_schedule=_STANDARD_A5_FOLLOWUPS,
    ),

    "iso27001-readiness": _A5SkuConfig(
        display_name="ISO 27001 Readiness Assessment",
        price_usd=2497,
        intake_fields=(
            "current_isms_state",       # "none" / "documented" / "partly implemented"
            "target_cert_date",
            "scope_statement",          # draft or URL
            "applicable_controls",      # Annex A controls list or "full scope"
            "primary_environment",
        ),
        turnaround_days=30,
        deliverable=(
            "Initial ISO 27001 readiness assessment + ISMS gap report + "
            "30-day implementation roadmap"
        ),
        anthony_role="Deliver all stakeholder interviews; review and sign every deliverable",
        intake_path="/intake/iso27001-readiness",
        followup_schedule=_STANDARD_A5_FOLLOWUPS,
    ),

    "soc2-readiness": _A5SkuConfig(
        display_name="SOC 2 Readiness Assessment",
        price_usd=2497,
        intake_fields=(
            "target_framework",         # Type I / Type II
            "current_controls",
            "target_audit_date",
            "auditor_name",             # if already selected
            "primary_environment",
        ),
        turnaround_days=30,
        deliverable=(
            "SOC 2 readiness gap report + control mapping + "
            "auditor-ready evidence checklist"
        ),
        anthony_role="Deliver stakeholder interviews; review and sign deliverables",
        intake_path="/intake/soc2-readiness",
        followup_schedule=_STANDARD_A5_FOLLOWUPS,
    ),

    "attestation-prep": _A5SkuConfig(
        display_name="Compliance Attestation Preparation",
        price_usd=1997,
        intake_fields=(
            "target_framework",         # SOC 2 / ISO 27001 / HIPAA
            "current_controls",
            "target_audit_date",
            "primary_environment",
            "escalation_contact",
        ),
        turnaround_days=45,
        deliverable=(
            "Framework-specific readiness report + evidence collection guide + "
            "auditor-ready control documentation"
        ),
        anthony_role="Deliver interviews; review all deliverables before client handoff",
        intake_path="/intake/attestation-prep",
        followup_schedule=_STANDARD_A5_FOLLOWUPS,
    ),
}

# SKU aliases — normalise variant names from Stripe checkout
_A5_SKU_ALIASES: dict[str, str] = {
    "cyber-insurance-readiness":        "cir-small",
    "cyber-insurance-readiness-small":  "cir-small",
    "cyber-insurance-readiness-medium": "cir-medium",
    "cyber-insurance-readiness-large":  "cir-large",
    "cir":                              "cir-small",
    "it-security-audit":                "it-audit",
    "hipaa-gap-analysis":               "hipaa-gap",
}

# ---------------------------------------------------------------------------
# CIR gap-analysis checklist
# ---------------------------------------------------------------------------

# Each control is: (key, display_name, weight, passing_values)
# weight: 1 = standard, 2 = critical, 3 = insurer-required
_CIR_CONTROLS: list[tuple[str, str, int, frozenset[str]]] = [
    ("mfa_email",          "MFA on email (M365/Google Workspace)",       3,
     frozenset({"yes", "enabled", "true", "all users"})),
    ("mfa_admin",          "MFA enforced for all admin accounts",        3,
     frozenset({"yes", "enabled", "true", "all admins"})),
    ("mfa_vpn_remote",     "MFA on VPN / remote access",                 2,
     frozenset({"yes", "enabled", "true"})),
    ("edr_deployed",       "Endpoint Detection & Response (EDR) on all endpoints", 3,
     frozenset({"yes", "all endpoints", "full deployment"})),
    ("backup_tested",      "Offsite backups tested within last 90 days", 3,
     frozenset({"yes", "tested", "verified"})),
    ("backup_immutable",   "Immutable or air-gapped backup copy exists", 2,
     frozenset({"yes", "immutable", "air-gapped"})),
    ("ir_plan",            "Written Incident Response plan exists",       2,
     frozenset({"yes", "documented", "formal"})),
    ("ir_tested",          "IR plan tabletop-tested within last 12 months", 1,
     frozenset({"yes", "tested", "tabletop"})),
    ("email_security",     "Email security gateway / DMARC p=reject",   2,
     frozenset({"yes", "enabled", "dmarc reject"})),
    ("patch_cadence",      "Patch cadence ≤ 30 days for critical patches", 2,
     frozenset({"yes", "monthly", "automated"})),
    ("privileged_access",  "Privileged Access Management (PAM) / no shared admin creds", 1,
     frozenset({"yes", "pam", "unique creds"})),
    ("sat_annual",         "Security Awareness Training at least annually", 1,
     frozenset({"yes", "annual", "quarterly"})),
    ("cyber_policy",       "Active cyber-insurance policy in force",     1,
     frozenset({"yes", "active", "bound"})),
    ("vendor_mfa",         "MFA required for third-party vendor access",  2,
     frozenset({"yes", "required", "enforced"})),
]

# Maximum achievable score (sum of all weights × 2 for pass/fail scaling)
_MAX_SCORE = sum(w for _, _, w, _ in _CIR_CONTROLS)


def _evaluate_control(
    key: str,
    passing_values: frozenset[str],
    intake: dict[str, Any],
) -> bool:
    """Return True if the intake answer satisfies the control."""
    raw = intake.get(key, "") or ""
    return raw.strip().lower() in passing_values


def run_cir_gap_analysis(ticket_id: str, intake: dict[str, Any]) -> dict[str, Any]:
    """Run the CIR checklist against the provided intake answers.

    Does NOT hit the database — pure computation.  Callers should persist
    the result via tickets_lib.append_event().

    Returns
    -------
    {
        "ticket_id":          str,
        "gaps":               list[str],         # control keys that failed
        "passed":             list[str],          # control keys that passed
        "score":              int,                # 0–100
        "raw_score":          int,                # weighted sum of passed controls
        "max_score":          int,
        "tier_recommendation":str,               # "Foundation"|"Assurance"|"Directive"
        "report_text":        str,               # full plain-text section for the report
    }
    """
    gaps: list[str] = []
    passed: list[str] = []
    raw_score = 0

    for key, label, weight, passing_vals in _CIR_CONTROLS:
        if _evaluate_control(key, passing_vals, intake):
            passed.append(key)
            raw_score += weight
        else:
            gaps.append(key)

    score = round((raw_score / _MAX_SCORE) * 100) if _MAX_SCORE else 0
    tier = upsell_recommendation(score, intake)["tier"]

    # Build the report section
    lines: list[str] = [
        "=== Cyber-Insurance Readiness Gap Analysis ===",
        f"Assessment ID:  {ticket_id}",
        f"Overall Score:  {score}/100  ({raw_score}/{_MAX_SCORE} weighted points)",
        f"Tier:           {tier}",
        "",
        "--- CONTROLS ASSESSMENT ---",
    ]
    for key, label, weight, _ in _CIR_CONTROLS:
        status = "PASS" if key in passed else "FAIL"
        criticality = {1: "standard", 2: "important", 3: "critical"}[weight]
        lines.append(f"  [{status}]  {label}  ({criticality})")

    lines += [
        "",
        f"Gaps identified: {len(gaps)}",
        f"Controls passing: {len(passed)} / {len(_CIR_CONTROLS)}",
        "",
        "Note: This automated analysis is a first-pass checklist based on "
        "your intake responses. Anthony will review, enrich with any "
        "stakeholder interview data, and sign the final report.",
    ]

    return {
        "ticket_id":           ticket_id,
        "gaps":                gaps,
        "passed":              passed,
        "score":               score,
        "raw_score":           raw_score,
        "max_score":           _MAX_SCORE,
        "tier_recommendation": tier,
        "report_text":         "\n".join(lines),
    }


def build_remediation_roadmap(gaps: list[str]) -> list[dict[str, Any]]:
    """Convert a list of failed control keys into a prioritised remediation plan.

    Returns a list of roadmap items, each:
    {
        "priority":     int  (1=critical, 2=important, 3=standard)
        "control":      str  (key)
        "label":        str  (display name)
        "action":       str  (concrete next step)
        "effort":       str  ("hours"|"days"|"weeks")
        "klaravex_can_help": bool
    }
    sorted by priority ascending (1 first).
    """
    _actions: dict[str, dict[str, Any]] = {
        "mfa_email": {
            "label":    "MFA on email",
            "action":   "Enable Conditional Access MFA for all users in M365 Entra ID "
                        "(or equivalent in Google Workspace). Enforce via named policy — "
                        "not just per-user MFA toggle.",
            "effort":   "hours",
            "priority": 1,
            "klaravex_can_help": True,
        },
        "mfa_admin": {
            "label":    "MFA for admin accounts",
            "action":   "Enable Privileged Identity Management (PIM) or equivalent. "
                        "All Global Admin, Exchange Admin, and GA-equivalent roles "
                        "must require MFA and use dedicated admin accounts.",
            "effort":   "hours",
            "priority": 1,
            "klaravex_can_help": True,
        },
        "mfa_vpn_remote": {
            "label":    "MFA on VPN / remote access",
            "action":   "Configure MFA on all VPN concentrators and RDP gateways. "
                        "Disable direct RDP exposure to the internet.",
            "effort":   "days",
            "priority": 1,
            "klaravex_can_help": True,
        },
        "edr_deployed": {
            "label":    "EDR on all endpoints",
            "action":   "Deploy Huntress or Microsoft Defender for Endpoint (P2) "
                        "to all Windows/macOS endpoints. Confirm MDM enrollment "
                        "covers 100% of managed devices.",
            "effort":   "days",
            "priority": 1,
            "klaravex_can_help": True,
        },
        "backup_tested": {
            "label":    "Backup restore testing",
            "action":   "Schedule quarterly restore test from backup. "
                        "Document results in a restore-test log (insurers require evidence).",
            "effort":   "hours",
            "priority": 1,
            "klaravex_can_help": True,
        },
        "backup_immutable": {
            "label":    "Immutable / air-gapped backup",
            "action":   "Add an offsite immutable copy (AWS S3 Object Lock, "
                        "Backblaze B2 with object lock, or tape). "
                        "Segregate from primary backup job credentials.",
            "effort":   "days",
            "priority": 1,
            "klaravex_can_help": True,
        },
        "ir_plan": {
            "label":    "Written Incident Response plan",
            "action":   "Draft a one-page IR plan covering: detection, containment, "
                        "eradication, recovery, and post-incident review. "
                        "Include named contacts (internal + external — legal, PR, insurer).",
            "effort":   "days",
            "priority": 1,
            "klaravex_can_help": True,
        },
        "ir_tested": {
            "label":    "IR plan tabletop exercise",
            "action":   "Schedule a 90-minute tabletop exercise with key stakeholders. "
                        "Klaravex can facilitate. Document the run and findings.",
            "effort":   "days",
            "priority": 2,
            "klaravex_can_help": True,
        },
        "email_security": {
            "label":    "Email security / DMARC p=reject",
            "action":   "Publish SPF, DKIM, and DMARC records. "
                        "Set DMARC policy to p=reject (or p=quarantine as interim). "
                        "Enable M365 Defender anti-phishing / Safe Links / Safe Attachments.",
            "effort":   "hours",
            "priority": 1,
            "klaravex_can_help": True,
        },
        "patch_cadence": {
            "label":    "Patch cadence ≤ 30 days",
            "action":   "Enable Windows Update for Business or Intune Update Rings "
                        "to enforce critical patches within 14 days, standard within 30. "
                        "Enable macOS MDM auto-update.",
            "effort":   "days",
            "priority": 1,
            "klaravex_can_help": True,
        },
        "privileged_access": {
            "label":    "Privileged Access Management",
            "action":   "Eliminate shared admin credentials. Each admin gets a "
                        "dedicated privileged account used only for admin tasks. "
                        "Implement PIM / JIT access for M365 or AWS.",
            "effort":   "days",
            "priority": 2,
            "klaravex_can_help": True,
        },
        "sat_annual": {
            "label":    "Security Awareness Training",
            "action":   "Enrol all staff in a security awareness training platform "
                        "(KnowBe4, usecure, or equivalent). "
                        "Run 1-2 phishing simulations per month. "
                        "Insurers require evidence of completion.",
            "effort":   "days",
            "priority": 2,
            "klaravex_can_help": True,
        },
        "cyber_policy": {
            "label":    "Active cyber-insurance policy",
            "action":   "Obtain or renew a standalone cyber-insurance policy with "
                        "at least $1M aggregate / $2,500 deductible. "
                        "Ensure coverage includes ransomware, BEC, and data breach.",
            "effort":   "weeks",
            "priority": 2,
            "klaravex_can_help": False,
        },
        "vendor_mfa": {
            "label":    "MFA for third-party vendor access",
            "action":   "Require all vendors with environment access to use MFA. "
                        "Review and revoke stale vendor permissions. "
                        "Use Entra ID External Identities or equivalent.",
            "effort":   "days",
            "priority": 1,
            "klaravex_can_help": True,
        },
    }

    roadmap: list[dict[str, Any]] = []
    for key in gaps:
        item = _actions.get(key)
        if item:
            roadmap.append({"control": key, **item})
        else:
            roadmap.append({
                "control": key,
                "label":   key,
                "action":  "Review this control with your security team.",
                "effort":  "unknown",
                "priority": 3,
                "klaravex_can_help": False,
            })

    roadmap.sort(key=lambda x: x["priority"])
    return roadmap


def generate_cir_report(
    ticket_id: str,
    intake: dict[str, Any],
    gaps: list[str],
    roadmap: list[dict[str, Any]],
) -> str:
    """Assemble the full plain-text CIR gap report + remediation roadmap.

    This is the draft Anthony reviews before signing and delivering to the client.
    """
    org = intake.get("company_name") or intake.get("customer_name") or "Your Organisation"
    industry = intake.get("industry") or "—"
    insurer = intake.get("current_insurer") or "—"
    renewal = intake.get("renewal_date") or "—"
    limits = intake.get("current_policy_limits") or "—"
    env = intake.get("primary_environment") or "—"

    lines: list[str] = [
        "=" * 68,
        "CYBER-INSURANCE READINESS REPORT",
        f"Prepared by Klaravex LLC  |  support@klaravex.com  |  klaravex.com",
        "=" * 68,
        "",
        f"Organisation:      {org}",
        f"Industry:          {industry}",
        f"Primary env:       {env}",
        f"Current insurer:   {insurer}",
        f"Renewal date:      {renewal}",
        f"Policy limits:     {limits}",
        f"Assessment ID:     {ticket_id}",
        "",
        "-" * 68,
        "EXECUTIVE SUMMARY",
        "-" * 68,
        "",
    ]

    gap_count = len(gaps)
    if gap_count == 0:
        lines.append(
            "This assessment identified no critical gaps. Your organisation "
            "meets the baseline controls required by most standard cyber-insurance "
            "questionnaires. See the roadmap section for enhancement opportunities."
        )
    elif gap_count <= 3:
        lines.append(
            f"This assessment identified {gap_count} gap(s) in your security "
            "controls baseline. These are addressable within 30 days and are "
            "unlikely to block coverage renewal, but should be remediated before "
            "your next underwriting submission."
        )
    elif gap_count <= 7:
        lines.append(
            f"This assessment identified {gap_count} gaps across your controls "
            "baseline. Several of these — particularly MFA, EDR, and backup "
            "testing — are required by most insurers and may affect your "
            "renewal premium or coverage availability if not addressed promptly."
        )
    else:
        lines.append(
            f"This assessment identified {gap_count} material gaps in your "
            "security controls. Without remediating the critical items below, "
            "you risk premium increases of 30-100%, coverage exclusions, or "
            "denial of renewal at your next underwriting cycle."
        )

    lines += [
        "",
        "-" * 68,
        "DETAILED FINDINGS",
        "-" * 68,
        "",
    ]

    # Group roadmap by priority
    critical = [r for r in roadmap if r["priority"] == 1]
    important = [r for r in roadmap if r["priority"] == 2]
    standard = [r for r in roadmap if r["priority"] == 3]

    def _section(items: list[dict[str, Any]], heading: str) -> None:
        if not items:
            return
        lines.append(f"  {heading}")
        lines.append("")
        for item in items:
            klaravex = "  [Klaravex can assist]" if item.get("klaravex_can_help") else ""
            lines.append(f"  [{item['control'].upper().replace('_',' ')}]{klaravex}")
            lines.append(f"  Label:  {item['label']}")
            lines.append(f"  Action: {item['action']}")
            lines.append(f"  Effort: {item['effort']}")
            lines.append("")

    _section(critical, "CRITICAL — Remediate within 30 days")
    _section(important, "IMPORTANT — Remediate within 90 days")
    _section(standard, "STANDARD — Address in next planning cycle")

    lines += [
        "-" * 68,
        "REMEDIATION ROADMAP SUMMARY",
        "-" * 68,
        "",
        f"  Critical items (≤30 days):  {len(critical)}",
        f"  Important items (≤90 days): {len(important)}",
        f"  Standard items:             {len(standard)}",
        "",
        "Priority order: MFA > EDR > Backup testing > IR plan > Email security",
        "",
        "-" * 68,
        "NEXT STEPS",
        "-" * 68,
        "",
        "1. Schedule a 30-minute remediation call with the Klaravex team to",
        "   walk through this report and agree priorities.",
        "2. Review the managed-service recommendation below — many of these",
        "   controls are included in Klaravex managed plans at no extra cost.",
        "3. Share this report with your insurance broker at renewal.",
        "",
        "Book your remediation call: https://personal.klaravex.com/book",
        "",
        "-" * 68,
        "KLARAVEX MANAGED SERVICE RECOMMENDATION",
        "-" * 68,
        "",
    ]

    # Inline the upsell text
    upsell = upsell_recommendation(
        score=round(
            (
                sum(w for k, _, w, _ in _CIR_CONTROLS if k not in gaps)
                / _MAX_SCORE
            ) * 100
        ) if _MAX_SCORE else 0,
        intake=intake,
    )
    lines.append(f"Recommended tier:  {upsell['tier']}")
    lines.append(f"Rationale:         {upsell['rationale']}")
    lines += [
        "",
        f"Learn more + book a discovery call: klaravex.com",
        "",
        "=" * 68,
        "DISCLAIMER",
        "=" * 68,
        "",
        "This report reflects Klaravex's assessment based on the information",
        "provided during intake. It does not constitute a legal opinion and",
        "is not a guarantee of insurance coverage. Results may differ after",
        "a full technical audit. Anthony Stewart, Klaravex LLC.",
        "",
        "support@klaravex.com  |  klaravex.com",
    ]

    return "\n".join(lines)


def upsell_recommendation(score: int, intake: dict[str, Any]) -> dict[str, Any]:
    """Map a CIR score + intake data to a Klaravex managed-service tier.

    Returns {"tier": str, "rationale": str, "cta_url": str, "price_hint": str}.
    """
    industry = (intake.get("industry") or "").lower()
    has_compliance = any(
        k in industry for k in ("health", "hipaa", "legal", "finance", "fintech")
    )
    env = (intake.get("primary_environment") or "").lower()
    cloud_heavy = any(k in env for k in ("m365", "aws", "gworkspace", "azure"))

    if score < 50 or has_compliance:
        tier = "Directive"
        rationale = (
            "Your organisation has significant control gaps and/or operates in "
            "a regulated industry (HIPAA, SOC 2, ISO 27001). The Directive tier "
            "includes MDR (Huntress), vCISO advisory, compliance programme "
            "management, and a full IR retainer — everything needed to close "
            "these gaps and keep your insurer satisfied at renewal."
        )
        price_hint = "$129/user/month"
    elif score < 75 or cloud_heavy:
        tier = "Assurance"
        rationale = (
            "Your organisation has a partial controls baseline with several "
            "insurer-required items still open. The Assurance tier adds Huntress "
            "MDR, email security hardening, quarterly posture reviews, and "
            "security awareness training — the fastest path to a clean "
            "insurance questionnaire."
        )
        price_hint = "$79/user/month"
    else:
        tier = "Foundation"
        rationale = (
            "Your controls baseline is strong. The Foundation tier will maintain "
            "your Atera RMM coverage, automated patching, and Klara AI AI first-line "
            "support — locking in what you have and preventing regression ahead "
            "of your next renewal."
        )
        price_hint = "$49/user/month"

    return {
        "tier":       tier,
        "rationale":  rationale,
        "cta_url":    "https://klaravex.com",
        "price_hint": price_hint,
    }


# ---------------------------------------------------------------------------
# A5 kickoff — generic dispatcher, follows per_incident_session.py pattern
# ---------------------------------------------------------------------------

async def a5_kickoff(sku: str, checkout_session: dict[str, Any]) -> dict[str, Any]:
    """Generic A5 assessment kickoff triggered by checkout.session.completed.

    Idempotent — dedup by stripe_session_id + SKU.
    Returns {"ticket_id": str|None, "sku": str, "triage": str,
             "followups_scheduled": int}.
    """
    # Normalise alias SKUs
    canonical_sku = _A5_SKU_ALIASES.get(sku, sku)
    cfg = A5_SKU_CONFIG.get(canonical_sku)
    if cfg is None:
        raise ValueError(
            f"a5_kickoff: unknown SKU '{sku}' (canonical: '{canonical_sku}') "
            f"— add it to A5_SKU_CONFIG first"
        )

    stripe_session_id = checkout_session.get("id", "")
    obj = checkout_session
    meta = obj.get("metadata") or {}

    # Resolve customer email + name
    customer_email: Optional[str] = (
        (obj.get("customer_details") or {}).get("email")
        or obj.get("customer_email")
        or meta.get("caller_email")
    )
    customer_name: Optional[str] = None
    if not customer_email and obj.get("customer"):
        try:
            cust = stripe.Customer.retrieve(obj["customer"])
            customer_email = cust.get("email")
            customer_name = cust.get("name")
        except Exception as exc:
            log.warning("a5_kickoff[%s]: stripe customer retrieve failed: %s", canonical_sku, exc)
    else:
        customer_name = (obj.get("customer_details") or {}).get("name")

    if not customer_email:
        log.warning(
            "a5_kickoff[%s]: no customer email on session %s — skipping",
            canonical_sku, stripe_session_id,
        )
        return {
            "ticket_id": None, "sku": canonical_sku,
            "triage": "skipped_no_email", "followups_scheduled": 0,
        }

    # Idempotency: skip if ticket already exists for this session + SKU
    existing = await _find_existing_a5_ticket(stripe_session_id, canonical_sku)
    if existing:
        log.info(
            "a5_kickoff[%s]: session %s already has ticket %s — skipping",
            canonical_sku, stripe_session_id, existing,
        )
        return {
            "ticket_id": existing, "sku": canonical_sku,
            "triage": "duplicate_skipped", "followups_scheduled": 0,
        }

    # Upsert client profile (B2B segment)
    try:
        await tickets_lib.get_or_create_client(
            customer_email,
            segment="b2b",
            name=customer_name,
            stripe_customer_id=obj.get("customer"),
        )
    except Exception as exc:
        log.warning("a5_kickoff[%s]: client upsert failed (continuing): %s", canonical_sku, exc)

    # Create ticket
    subject = f"{cfg.display_name} — {customer_name or customer_email}"
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=customer_email,
            subject=subject,
            severity="standard",
            status="open",
            source="stripe",
            archetype="A5",
            sku=canonical_sku,
            workflow_state="INTAKE",
            summary="Intake pending",
            segment_hint="b2b",
            metadata={
                "stripe_session_id":  stripe_session_id,
                "stripe_customer_id": obj.get("customer"),
                "contact_name":       customer_name,
                "turnaround_days":    cfg.turnaround_days,
            },
            initial_event={
                "type":              "checkout.session.completed",
                "source":            "stripe",
                "stripe_session_id": stripe_session_id,
            },
        )
    except Exception as exc:
        log.exception("a5_kickoff[%s]: ticket creation failed: %s", canonical_sku, exc)
        return {
            "ticket_id": None, "sku": canonical_sku,
            "triage": "ticket_error", "followups_scheduled": 0,
        }

    # Send intake form email
    try:
        await _send_a5_intake_email(customer_email, customer_name, ticket_id, cfg)
    except Exception as exc:
        log.warning("a5_kickoff[%s]: intake email failed (non-fatal): %s", canonical_sku, exc)

    # Alert Anthony
    try:
        await _alert_anthony_a5(customer_email, customer_name, ticket_id, cfg)
    except Exception as exc:
        log.warning("a5_kickoff[%s]: Anthony alert failed (non-fatal): %s", canonical_sku, exc)

    # Schedule follow-up rows
    followups_scheduled = 0
    try:
        followups_scheduled = await _schedule_a5_followups(
            ticket_id, customer_email, customer_name, cfg
        )
    except Exception as exc:
        log.warning("a5_kickoff[%s]: followup scheduling failed (non-fatal): %s", canonical_sku, exc)

    log.info(
        "a5_kickoff[%s] complete: ticket=%s email=%s followups=%d",
        canonical_sku, ticket_id, customer_email, followups_scheduled,
    )
    return {
        "ticket_id":          ticket_id,
        "sku":                canonical_sku,
        "triage":             "intake_sent",
        "followups_scheduled": followups_scheduled,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _find_existing_a5_ticket(stripe_session_id: str, sku: str) -> Optional[str]:
    """Return ticket_id if an A5 ticket already exists for this session + SKU."""
    if not stripe_session_id:
        return None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id::text FROM klaravex_tickets
                 WHERE archetype = 'A5'
                   AND sku = $2
                   AND metadata->>'stripe_session_id' = $1
                 LIMIT 1
                """,
                stripe_session_id,
                sku,
            )
        return row["id"] if row else None
    except Exception as exc:
        log.warning("a5 existing-ticket lookup failed: %s", exc)
        return None


async def _send_a5_intake_email(
    email: str,
    name: Optional[str],
    ticket_id: str,
    cfg: _A5SkuConfig,
) -> None:
    """Confirmation + intake form link email for any A5 assessment."""
    greeting = f"Hi {name}," if name else "Hi there,"
    intake_url = f"{PORTAL_BASE_URL}{cfg.intake_path}?ticket={ticket_id}"
    fields_preview = ", ".join(cfg.intake_fields[:4])
    escalation_block = f"\n{cfg.escalation_note}\n" if cfg.escalation_note else ""
    body = (
        f"{greeting}\n\n"
        f"Payment received — thank you for choosing the {cfg.display_name}.\n\n"
        f"Your assessment reference: {ticket_id}\n\n"
        f"To begin, please complete the 5-minute intake form so we can scope "
        f"your assessment accurately:\n\n"
        f"  {intake_url}\n\n"
        f"We will ask about: {fields_preview} (and a few more).\n"
        f"{escalation_block}\n"
        f"Deliverable: {cfg.deliverable}\n\n"
        f"Anthony will review the automated analysis, sign the final report, "
        f"and schedule a readout call to walk through the findings with you.\n\n"
        f"— The Klaravex Team\n"
        f"support@klaravex.com · klaravex.com"
    )
    await send_email(
        to=email,
        subject=f"[Klaravex] {cfg.display_name} confirmed — ref {ticket_id}",
        body=body,
    )


async def _alert_anthony_a5(
    email: str,
    name: Optional[str],
    ticket_id: str,
    cfg: _A5SkuConfig,
) -> None:
    """Alert Anthony of a new A5 purchase so he can prepare for his role."""
    subject = f"[Klaravex A5] {cfg.display_name} — {name or email}"
    body = (
        f"New A5 assessment purchased:\n\n"
        f"Ticket:            {ticket_id}\n"
        f"Email:             {email}\n"
        f"Name:              {name or '—'}\n"
        f"Product:           {cfg.display_name}\n"
        f"Turnaround:        {cfg.turnaround_days} business days\n"
        f"Anthony role:      {cfg.anthony_role}\n"
        f"Deliverable:       {cfg.deliverable}\n\n"
        f"Intake form sent to client. Klara AI will run the automated gap analysis "
        f"once the intake form is submitted and surface it for your review.\n"
    )
    await send_email(to=ALERT_EMAIL, subject=subject, body=body)


async def _schedule_a5_followups(
    ticket_id: str,
    email: str,
    name: Optional[str],
    cfg: _A5SkuConfig,
) -> int:
    """Insert scheduled follow-up rows from the SKU config. Returns count inserted."""
    pool = await get_pool()
    count = 0
    async with pool.acquire() as conn:
        for item in cfg.followup_schedule:
            try:
                await conn.execute(
                    """
                    INSERT INTO klaravex_a5_followups
                        (ticket_id, sku, client_email, client_name,
                         template, send_after_hours)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (ticket_id, template) DO NOTHING
                    """,
                    ticket_id,
                    cfg.display_name,
                    email.lower(),
                    name,
                    item["template"],
                    item["offset_hours"],
                )
                count += 1
            except Exception as exc:
                log.warning(
                    "a5_followups insert failed (%s): %s", item["template"], exc
                )
    return count
