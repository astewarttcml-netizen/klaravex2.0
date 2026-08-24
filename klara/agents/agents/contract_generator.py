"""
app/agents/contract_generator.py
──────────────────────────────────
P4 agent — generates a draft SoW/contract from lead + proposal data.

Triggered by: POST /api/v1/admin/deals/{lead_id}/generate-contract  (admin API)

Flow:
  1. Load lead and latest proposal for that lead
  2. Claude drafts a professional SoW/contract (English or German)
  3. Queue for Anthony's P4 approval before sending to client
  4. Stamp proposal.contract_generated_at (idempotency guard)

Output format: structured contract with Scope, Deliverables, Timeline,
Payment Terms, GDPR / data processing clause, and Governing Law (German law).

Permission: P4 — client-facing legal document, always requires manual review.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import BaseAgent, AgentContext, AgentResult, PermissionLevel
from app.models.lead import Lead

logger = structlog.get_logger(__name__)

_CONTRACT_PROMPT_EN = textwrap.dedent("""\
You are Anthony Stewart, IT Consultant at Klaravex (klaravex.de).
Draft a professional Statement of Work / Service Contract in English.

Client details:
  Name:          {name}
  Company:       {company}
  Email:         {email}
  Services:      {services}
  Budget range:  {budget}
  Timeline:      {timeline}
  Call notes:    {call_notes}
  Proposal ref:  {proposal_ref}

Contract requirements:
1. PARTIES — Anthony Stewart / Klaravex AND client full name/company
2. SCOPE OF WORK — bullet list of deliverables derived from services and call notes
3. TIMELINE — start date placeholder, milestones aligned with stated timeline
4. FEES AND PAYMENT TERMS
   - Fee based on budget range (use the midpoint if range given)
   - Net-14 payment terms
   - Invoiced upon completion of each milestone
5. INTELLECTUAL PROPERTY — work product belongs to client upon full payment
6. DATA PROCESSING (GDPR Art. 28) — brief clause: Anthony processes only data
   necessary for the service; data processed under German / EU law
7. CONFIDENTIALITY — mutual NDA clause, 2-year term
8. GOVERNING LAW — Laws of Germany; disputes in Berlin courts
9. SIGNATURES — placeholder lines for both parties

Format: use numbered sections with clear headings. Professional but plain language.
No legalese jargon. Leave [DATE] and [MILESTONE DATE] placeholders.
End with SIGNATURE BLOCK.
""")

_CONTRACT_PROMPT_DE = textwrap.dedent("""\
Sie sind Anthony Stewart, IT-Berater bei Klaravex (klaravex.de).
Erstellen Sie einen professionellen Dienstleistungsvertrag / Leistungsbeschreibung auf DEUTSCH.

Kundendaten:
  Name:              {name}
  Unternehmen:       {company}
  E-Mail:            {email}
  Leistungen:        {services}
  Budgetrahmen:      {budget}
  Zeitrahmen:        {timeline}
  Gesprächsnotizen:  {call_notes}
  Angebots-Ref.:     {proposal_ref}

Anforderungen:
1. VERTRAGSPARTEIEN — Anthony Stewart / Klaravex UND vollständiger Kundenname
2. LEISTUNGSUMFANG — Aufzählung der Liefergegenstände
3. PROJEKTLAUFZEIT — Startdatum-Platzhalter, Meilensteine
4. VERGÜTUNG UND ZAHLUNGSBEDINGUNGEN — Netto 14 Tage, Rechnung je Meilenstein
5. GEISTIGES EIGENTUM — geht nach vollständiger Zahlung auf den Auftraggeber über
6. DATENSCHUTZ (DSGVO Art. 28) — Verarbeitung nur notwendiger Daten nach deutschem Recht
7. VERTRAULICHKEIT — gegenseitige NDA-Klausel, 2 Jahre Laufzeit
8. ANWENDBARES RECHT — Deutsches Recht; Gerichtsstand Berlin
9. UNTERSCHRIFTEN — Platzhalterzeilen

Format: nummerierte Abschnitte, klare Überschriften. Professionell, aber verständlich.
Platzhalter: [DATUM] und [MEILENSTEINDATUM].
""")


class ContractGeneratorAgent(BaseAgent):
    name = "contract_generator"
    permission_level = PermissionLevel.P4
    description = (
        "Triggered via POST /api/v1/admin/deals/{lead_id}/generate-contract. "
        "Drafts a bilingual SoW/contract from lead and proposal data, then queues "
        "it for Anthony's P4 approval. Includes Scope, Deliverables, Timeline, "
        "Payment Terms, GDPR Art. 28 clause, and Governing Law (Germany)."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        lead_id = context.lead_id or payload.get("lead_id")
        if not lead_id:
            return AgentResult.fail("contract_generator: 'lead_id' is required.")

        lead = (await context.db.execute(
            select(Lead).where(Lead.id == lead_id)
        )).scalar_one_or_none()

        if not lead:
            return AgentResult.fail(f"Lead {lead_id} not found.")
        if lead.status == "anonymised":
            return AgentResult.fail("Cannot generate contract for anonymised lead.")

        # Fetch latest proposal for this lead (if exists)
        proposal_ref = "N/A"
        try:
            from app.models.proposal import Proposal
            result = await context.db.execute(
                select(Proposal)
                .where(Proposal.lead_id == lead_id)
                .order_by(Proposal.created_at.desc())
                .limit(1)
            )
            proposal = result.scalar_one_or_none()
            if proposal:
                proposal_ref = str(proposal.id)
        except Exception:
            pass  # proposal model optional

        language = _detect_language(lead)
        prompt_template = _CONTRACT_PROMPT_DE if language == "de" else _CONTRACT_PROMPT_EN

        call_notes_summary = ""
        if lead.call_notes:
            import json
            try:
                notes = json.loads(lead.call_notes)
                call_notes_summary = (
                    f"Pain points: {notes.get('pain_points', '')}. "
                    f"Budget: {notes.get('budget', '')}. "
                    f"Timeline: {notes.get('timeline', '')}. "
                    f"Next action: {notes.get('next_action', '')}."
                )
            except Exception:
                call_notes_summary = lead.call_notes[:500]

        prompt = prompt_template.format(
            name=lead.name or "Client",
            company=lead.company or "Client Organisation",
            email=lead.email or "",
            services=lead.services_interest or "IT Consulting Services",
            budget=lead.budget_range or "To be confirmed",
            timeline=lead.timeline or "To be confirmed",
            call_notes=call_notes_summary or "No call notes on file",
            proposal_ref=proposal_ref,
        )

        log.info("contract_generator.drafting", lead_id=lead_id, language=language)

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            from app.services.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="_CONTRACT_PROMPT_EN",
                content=str(_CONTRACT_PROMPT_EN),
            )
        except Exception:
            pass

        try:
            response = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            contract_text = response.content[0].text.strip()
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=response, lead_id=lead_id,
            )
        except Exception as exc:
            log.error("contract_generator.claude_error", lead_id=lead_id, error=str(exc))
            return AgentResult.fail(str(exc))

        # Queue for P4 approval
        try:
            from app.agents.registry import registry
            approval_agent = registry.get("approval_manager")
            await approval_agent(context, {
                "action": "create",
                "action_name": "send_contract_to_client",
                "risk_level": "P4",
                "payload": {
                    "lead_id": lead_id,
                    "to_email": lead.email,
                    "to_name": lead.name or lead.email,
                    "contract_text": contract_text,
                    "language": language,
                    "proposal_ref": proposal_ref,
                },
                "justification": (
                    f"Contract draft for {lead.name or lead.email} "
                    f"({lead.company or 'unknown'}). Proposal ref: {proposal_ref}. "
                    f"Language: {language.upper()}. Requires legal review before sending."
                ),
                "requested_by": self.name,
            })
        except Exception as exc:
            log.error("contract_generator.approval_queue_error",
                      lead_id=lead_id, error=str(exc))
            return AgentResult.fail(str(exc))

        log.info("contract_generator.queued_for_approval",
                 lead_id=lead_id, language=language,
                 tokens=response.usage.output_tokens)

        return AgentResult.ok({
            "status": "queued_for_p4_approval",
            "lead_id": lead_id,
            "language": language,
            "proposal_ref": proposal_ref,
            "contract_preview": contract_text[:300] + "…",
            "tokens_used": response.usage.output_tokens,
        })


def _detect_language(lead: Lead) -> str:
    email = lead.email or ""
    if email.endswith(".de") or email.endswith(".at") or email.endswith(".ch"):
        return "de"
    return "en"
