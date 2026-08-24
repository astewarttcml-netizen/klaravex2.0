"""
app/agents/faq_responder.py
────────────────────────────
P2 agent — answers common IT questions using an embedded service knowledge base.

Triggered by: routing agent when message matches FAQ pattern (no strong lead signal).
Also callable directly via POST /api/v1/agents/run with agent="faq_responder".

Covers:
  - Microsoft 365 (licensing, setup, migration, shared mailboxes, Teams)
  - Azure / Entra ID (tenant setup, SSO, conditional access, MFA)
  - Intune / device management (MDM, compliance policies, app deployment)
  - Networking (Meraki, VPN, SD-WAN basics)
  - General IT consulting (what do you do, how does it work, pricing ballpark)

Strategy: embedded KB passed as context to Claude Haiku for fast, accurate answers.
Haiku is sufficient — this is retrieval + synthesis, not reasoning.

Permission: P2 — informational only, no PII exposure.
"""
from __future__ import annotations

import textwrap

import structlog
from anthropic import AsyncAnthropic

from klara.rarv.runtime import BaseAgent, AgentContext, AgentResult, PermissionLevel

logger = structlog.get_logger(__name__)

# ── Embedded knowledge base ───────────────────────────────────────────────────
_KNOWLEDGE_BASE = textwrap.dedent("""
=== IT EXPERTS BERLIN — SERVICE KNOWLEDGE BASE ===

ABOUT:
  Anthony Stewart is a freelance IT consultant in Berlin, Germany.
  10+ years enterprise experience: Merrill Lynch, World Bank Group, FDH Aero.
  Specialises in Microsoft 365, Azure, Entra ID, Intune, Meraki, VMware.
  Serves English-speaking expats, international companies, and German SMBs.

SERVICES AND TYPICAL SCOPE:
  1. Microsoft 365 Setup & Migration
     - New tenant creation and licence assignment
     - Email migration (on-prem Exchange → M365, Gmail → M365)
     - Teams deployment, SharePoint/OneDrive setup
     - Shared mailboxes, distribution lists, calendar sharing
     - Typical timeline: 1–4 weeks depending on size
     - Typical cost range: €1,500–€8,000 depending on size

  2. Azure / Entra ID (Azure AD) Identity
     - Tenant setup and hardening
     - Hybrid identity with on-prem AD sync (Entra Connect)
     - SSO for business applications (SAML, OIDC)
     - Conditional Access policies, MFA rollout
     - Privileged Identity Management (PIM)
     - Typical timeline: 2–6 weeks
     - Typical cost range: €2,000–€12,000

  3. Intune / Modern Device Management
     - MDM enrolment for Windows, macOS, iOS, Android
     - Compliance policies, configuration profiles
     - App deployment and protection policies
     - Autopilot / zero-touch provisioning
     - Typical timeline: 2–4 weeks
     - Typical cost range: €1,500–€6,000

  4. Network Infrastructure
     - Meraki switching, wireless, SD-WAN
     - VPN configuration (site-to-site, client VPN)
     - Network segmentation and VLAN design
     - Typical timeline: 1–3 weeks
     - Typical cost range: €1,000–€5,000

  5. Security & Compliance
     - Microsoft Defender for Business / Endpoint
     - Security baseline implementation
     - GDPR / DSGVO data inventory and policy support
     - Vulnerability assessments for SMB environments
     - Typical cost range: €1,500–€10,000

  6. General IT Support Retainer
     - Monthly retainer for ongoing IT support
     - Remote and on-site (Berlin area) support
     - Typical cost: €500–€2,000/month depending on scope

PRICING PHILOSOPHY:
  - Project-based or retainer; no hourly billing for setup projects
  - Prices above are indicative; precise quote follows scoping call
  - German invoice (Rechnung) provided; VAT (MwSt) applicable
  - Payment: net 14 days per milestone

LANGUAGES: English (native), German (professional working proficiency)
LOCATION: Berlin, Germany — remote-first, on-site available Berlin area
CONTACT: via website form or direct email
BOOKING: Calendly link provided in follow-up

FAQ:
Q: Do you work with small businesses (1–10 people)?
A: Yes, absolutely. Many clients are small businesses setting up M365 for the first time.

Q: Can you help migrate from Google Workspace to Microsoft 365?
A: Yes. Gmail/Drive to M365/OneDrive migrations are a core service.

Q: Do you offer ongoing support after the project?
A: Yes, monthly retainer options are available.

Q: Are you available for on-site work?
A: Yes, within Berlin and Brandenburg. Remote-first for the rest of Germany.

Q: Can you work with German companies and provide German documentation?
A: Yes. Fluent in technical German, invoices in German, DSGVO-compliant processes.

Q: How quickly can you start?
A: Typically within 1–2 weeks of contract signature. Urgent projects accommodated.
""")

_FAQ_SYSTEM = textwrap.dedent("""\
You are the AI assistant for Klaravex (Anthony Stewart, IT consultant).
Use ONLY the knowledge base provided to answer the question. Do not invent facts.
Be helpful, concise, and professional. If the answer is not in the KB, say so and
suggest the prospect book a free 20-minute discovery call.
Always end by offering to connect them with Anthony for a personalised discussion.
Respond in the same language as the question.
""")


class FaqResponderAgent(BaseAgent):
    name = "faq_responder"
    permission_level = PermissionLevel.P2
    description = (
        "Answers common questions about Klaravex services (M365, Azure, "
        "Intune, Meraki, pricing, timelines) using an embedded service knowledge base. "
        "Uses Claude Haiku for fast, accurate retrieval + synthesis. "
        "Returns draft_response for use in chat. P2 — informational only."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        question = payload.get("message") or payload.get("question", "")
        if not question:
            return AgentResult.fail("faq_responder: 'message' or 'question' is required.")

        log.info("faq_responder.answering", question_length=len(question))

        kb = getattr(context.settings, "brand_faq_knowledge_override", "") or _KNOWLEDGE_BASE

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=_FAQ_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"KNOWLEDGE BASE:\n{kb}\n\n"
                            f"QUESTION: {question}"
                        ),
                    }
                ],
            )
            try:
                from klara.rarv.runtime.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model="claude-haiku-4-5-20251001",
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            answer = response.content[0].text.strip()
        except Exception as exc:
            log.error("faq_responder.claude_error", error=str(exc))
            return AgentResult.fail(str(exc))

        log.info("faq_responder.answered", tokens=response.usage.output_tokens)

        return AgentResult.ok({
            "question": question,
            "answer": answer,
            "tokens_used": response.usage.output_tokens,
        })
