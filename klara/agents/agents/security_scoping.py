"""
app/agents/security_scoping.py
────────────────────────────────
SecurityScopingAgent — P3 service-delivery agent.

Generates a professional security assessment scoping document and rules of
engagement from client discovery data, then queues it for Anthony's review
before delivery.

Trigger:  POST /api/v1/admin/deals/{lead_id}/security-scope

Input data:
  scope_type           (str)  — "m365_review" | "internal_pentest" | "full_suite"
  client_name          (str)
  primary_contact      (str)  — full name of the client's point of contact
  domain_count         (int)  — number of internet-facing domains in scope
  user_count           (int)  — number of user accounts in scope
  m365_tenant_name     (str, optional)  — e.g. "contoso.onmicrosoft.com"
  network_sites        (int)  — number of physical / logical network sites
  ad_domain            (str, optional)  — Active Directory domain FQDN
  in_scope_systems     (list[str])
  out_of_scope_systems (list[str])
  testing_window       (str)  — e.g. "weekdays 18:00–22:00 CET"
  emergency_contact    (str)  — name + phone number for emergency stop

Flow:
  1. Validate input and normalise scope_type.
  2. Generate scoping document via Claude (Markdown).
  3. Create ApprovalRequest (P3) via approval_manager.
  4. Write AuditLog entry.
  5. Return AgentResult.needs_approval().

Permission: P3 — legal/engagement document; must be reviewed before client delivery.
"""
from __future__ import annotations

import json

import structlog
from anthropic import AsyncAnthropic

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)

_VALID_SCOPE_TYPES = {"m365_review", "internal_pentest", "full_suite"}

# ── Prompt ────────────────────────────────────────────────────────────────────

_SCOPING_PROMPT = """\
You are a cybersecurity consultant at Klaravex producing a formal
security assessment scoping document and rules of engagement for a client.

Engagement context:
{context_json}

Generate a single Markdown document using ## for section headings.
Include exactly these sections in order:

## 1. Engagement Overview
One paragraph: engagement type, objectives, and business rationale.
Reference client_name, scope_type, and user/domain counts concretely.

## 2. Scope Definition
Two sub-tables:

### In Scope
| System / Asset | Type | Notes |
(populate from in_scope_systems list; infer Type from the asset name)

### Out of Scope
| System / Asset | Reason |
(populate from out_of_scope_systems; where list is empty state "None declared — all discovered assets treated as in scope unless otherwise agreed in writing")

## 3. Rules of Engagement
Bullet list covering:
- Permitted testing window: {testing_window}
- Permitted techniques (vary by scope_type — see below)
- Prohibited techniques: destructive exploitation, DoS/DDoS, social engineering of employees without prior written consent, data exfiltration beyond proof-of-concept
- Emergency stop procedure: if a critical service is disrupted, testing stops immediately; {emergency_contact} must be reached within 5 minutes
- Communication protocol: all findings reported to primary_contact within 24 h of discovery for critical severity; full report within 5 business days of engagement close

Permitted techniques by scope_type:
  m365_review:    Microsoft Secure Score review, Entra ID configuration audit,
                  conditional access policy review, MFA coverage assessment,
                  Exchange Online mail-flow and anti-phishing review,
                  SharePoint/OneDrive sharing policy audit, audit log review.
                  No active exploitation. No credential spraying.
  internal_pentest: Unauthenticated and authenticated network scanning (Nmap, Nessus),
                  AD enumeration (BloodHound — read-only), SMB share enumeration,
                  Kerberoasting (proof-of-concept hash capture only — no cracking on production),
                  lateral movement simulation in isolated test path only.
  full_suite:     All techniques from m365_review AND internal_pentest.

## 4. Authorisation Statement
A formal template block the client must sign. Include:
- Client name, primary contact, date field
- Statement that the client authorises Klaravex to conduct the assessment
  within the defined scope and testing window
- Acknowledgement that the client holds appropriate authority over all in-scope systems
- Signature line for client representative

## 5. Assessment Methodology
{methodology_section}

## 6. Expected Deliverables and Timeline
Table: Deliverable | Format | ETA from engagement start.
Include:
- Scoping sign-off (this document)  | PDF + e-signature | Day 0
- Kick-off call                      | Video call        | Day 1–2
- Active assessment                  | (varies)          | Day 3–{assessment_days}
- Preliminary findings               | Encrypted email   | Day {findings_day}
- Final report                       | PDF, Markdown     | Day {report_day}
- Debrief call                       | Video call        | Day {debrief_day}

## 7. DSGVO Article 32 Relevance
One paragraph explaining that this assessment directly supports the client's
obligation under DSGVO (GDPR) Article 32 to implement appropriate technical
and organisational measures, and that the findings report may be used as
documented evidence of due diligence.

Tone: formal, legally precise, enterprise-grade. No marketing language.
Output ONLY the Markdown document — no preamble, no explanation outside the doc.
"""

_M365_METHODOLOGY = """\
CIS Microsoft 365 Foundations Benchmark v3.1 control families assessed:
  - 1.x Account / Authentication (MFA, legacy auth, admin accounts)
  - 2.x Application Permissions (OAuth app consents, service principals)
  - 3.x Data Management (DLP, retention, sensitivity labels)
  - 4.x Email Security (anti-phishing, anti-spam, DKIM, DMARC, SPF)
  - 5.x Audit and Alerting (unified audit log, alert policies)
  - 6.x Storage (SharePoint/OneDrive external sharing, Teams guest access)

Tools: Microsoft Secure Score, Entra ID portal audit, Graph API read-only queries,
Maester (open-source M365 baseline checker), manual configuration review."""

_PENTEST_METHODOLOGY = """\
AD / Network assessment methodology (PTES-aligned):
  Phase 1 — Reconnaissance: passive OSINT (Shodan, Censys, certificate transparency)
  Phase 2 — Scanning: Nmap full-port TCP/UDP on in-scope subnets; Nessus credentialed scan
  Phase 3 — Enumeration: SMB (enum4linux-ng), LDAP (ldapsearch), DNS zone transfer attempt
  Phase 4 — Vulnerability identification: CVE cross-reference; Nessus plugin output triage
  Phase 5 — AD-specific: BloodHound/SharpHound data collection (read-only); Kerberoastable
             account identification; AS-REP roasting check; ACL abuse path mapping
  Phase 6 — Exploitation (PoC only, with prior written sign-off per finding)
  Phase 7 — Post-exploitation: privilege escalation path documentation only — no persistence

Tools: Nmap, Nessus (credentialed), BloodHound CE, CrackMapExec (enumeration only),
Impacket (read-only), Responder (listen-only mode), Metasploit (modules as needed)."""

_FULL_METHODOLOGY = _M365_METHODOLOGY + "\n\n" + _PENTEST_METHODOLOGY

_METHODOLOGY_MAP = {
    "m365_review": _M365_METHODOLOGY,
    "internal_pentest": _PENTEST_METHODOLOGY,
    "full_suite": _FULL_METHODOLOGY,
}

_TIMELINE_MAP = {
    # (assessment_days, findings_day, report_day, debrief_day)
    "m365_review":    (5,  6,  8, 10),
    "internal_pentest": (10, 11, 14, 16),
    "full_suite":     (15, 16, 20, 22),
}


class SecurityScopingAgent(BaseAgent):
    name = "security_scoping"
    description = (
        "Generates a formal security assessment scoping document and rules of "
        "engagement from client discovery data. Scope types: m365_review, "
        "internal_pentest, full_suite. Creates P3 ApprovalRequest before delivery. "
        "Trigger: POST /api/v1/admin/deals/{lead_id}/security-scope."
    )
    permission_level = PermissionLevel.P3

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        db = context.db
        log = logger.bind(
            agent=self.name,
            conversation_id=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        # ── Validate and normalise input ──────────────────────────────────────
        scope_type: str = (input_data.get("scope_type") or "").strip().lower()
        client_name: str = (input_data.get("client_name") or "").strip()
        primary_contact: str = (input_data.get("primary_contact") or "").strip()
        testing_window: str = (input_data.get("testing_window") or "").strip()
        emergency_contact: str = (input_data.get("emergency_contact") or "").strip()
        in_scope_systems: list = input_data.get("in_scope_systems") or []
        out_of_scope_systems: list = input_data.get("out_of_scope_systems") or []

        required = [
            ("scope_type", scope_type),
            ("client_name", client_name),
            ("primary_contact", primary_contact),
            ("testing_window", testing_window),
            ("emergency_contact", emergency_contact),
        ]
        missing = [f for f, v in required if not v]
        if missing:
            return AgentResult.fail(
                f"security_scoping: missing required fields: {', '.join(missing)}",
                agent=self.name,
            )

        if scope_type not in _VALID_SCOPE_TYPES:
            return AgentResult.fail(
                f"security_scoping: invalid scope_type '{scope_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_SCOPE_TYPES))}.",
                agent=self.name,
            )

        domain_count: int = int(input_data.get("domain_count") or 1)
        user_count: int = int(input_data.get("user_count") or 0)
        network_sites: int = int(input_data.get("network_sites") or 1)
        m365_tenant_name: str = (input_data.get("m365_tenant_name") or "").strip()
        ad_domain: str = (input_data.get("ad_domain") or "").strip()

        assessment_days, findings_day, report_day, debrief_day = _TIMELINE_MAP[scope_type]

        context_payload = {
            "scope_type": scope_type,
            "client_name": client_name,
            "primary_contact": primary_contact,
            "domain_count": domain_count,
            "user_count": user_count,
            "m365_tenant_name": m365_tenant_name or "(not provided)",
            "network_sites": network_sites,
            "ad_domain": ad_domain or "(not provided)",
            "in_scope_systems": in_scope_systems,
            "out_of_scope_systems": out_of_scope_systems,
            "testing_window": testing_window,
            "emergency_contact": emergency_contact,
        }

        log.info(
            "security_scoping.generating",
            scope_type=scope_type,
            client_name=client_name,
            user_count=user_count,
        )

        # ── Generate scoping document via Claude ──────────────────────────────
        anthropic_client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            response = await anthropic_client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=context.settings.anthropic_max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": _SCOPING_PROMPT.format(
                            context_json=json.dumps(context_payload, indent=2),
                            testing_window=testing_window,
                            emergency_contact=emergency_contact,
                            methodology_section=_METHODOLOGY_MAP[scope_type],
                            assessment_days=assessment_days,
                            findings_day=findings_day,
                            report_day=report_day,
                            debrief_day=debrief_day,
                        ),
                    }
                ],
            )
            try:
                from app.services.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=context.settings.anthropic_model,
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            scoping_markdown: str = response.content[0].text.strip()
            tokens_used: int = response.usage.output_tokens
        except Exception as exc:
            log.error(
                "security_scoping.claude_error",
                error=str(exc),
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            return AgentResult.fail(
                f"security_scoping: LLM error — {exc}",
                agent=self.name,
            )

        log.info(
            "security_scoping.document_generated",
            client_name=client_name,
            scope_type=scope_type,
            tokens_used=tokens_used,
            doc_length=len(scoping_markdown),
        )

        # ── Create P3 ApprovalRequest ─────────────────────────────────────────
        approval_payload = {
            **context_payload,
            "scoping_markdown": scoping_markdown,
        }

        try:
            from app.agents.registry import registry
            approval_mgr = registry.get("approval_manager")
            approval_result = await approval_mgr(
                context,
                {
                    "action": "create",
                    "action_name": "security_scoping.deliver",
                    "risk_level": "P3",
                    "payload": approval_payload,
                    "justification": (
                        f"Security scoping document ({scope_type}) generated for "
                        f"{client_name} — {user_count} users, {domain_count} domain(s). "
                        f"Testing window: {testing_window}. "
                        f"Review required before sending to {primary_contact}."
                    ),
                    "requested_by": self.name,
                },
            )
        except Exception as exc:
            log.error(
                "security_scoping.approval_queue_error",
                error=str(exc),
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            return AgentResult.fail(
                f"security_scoping: approval queue error — {exc}",
                agent=self.name,
            )

        if not approval_result.success:
            return AgentResult.fail(
                f"security_scoping: could not create approval request — "
                f"{approval_result.error}",
                agent=self.name,
            )

        approval_id: str = approval_result.output["approval_id"]

        # ── Write AuditLog entry ──────────────────────────────────────────────
        try:
            audit_agent = registry.get("audit_logger")
            await audit_agent(
                context,
                {
                    "event_type": "agent.action",
                    "agent_name": self.name,
                    "action_name": "security_scoping.deliver",
                    "lead_id": context.lead_id,
                    "approval_id": approval_id,
                    "details": {
                        "client_name": client_name,
                        "scope_type": scope_type,
                        "user_count": user_count,
                        "domain_count": domain_count,
                        "tokens_used": tokens_used,
                        "status": "pending_approval",
                    },
                    "success": True,
                },
            )
        except Exception as exc:
            log.warning("security_scoping.audit_warning", error=str(exc))

        log.info(
            "security_scoping.queued_for_approval",
            approval_id=approval_id,
            client_name=client_name,
            scope_type=scope_type,
            lead_id=context.lead_id,
        )

        return AgentResult.needs_approval(
            approval_id=approval_id,
            action="security_scoping.deliver",
        )
