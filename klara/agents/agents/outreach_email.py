"""
app/agents/outreach_email.py
──────────────────────────────
Generates and sends bilingual German + English outreach emails unconditionally.

Phase 3: Unconditional Bilingual Outreach

Pipeline position: runs after lead_scoring / routing.
Skipped automatically for COLD leads (score < 35).

Flow:
  1. Check tier — skip if COLD or no email on lead.
  2. Load full lead data from DB.
  3. Generate German subject + body via Claude (language="de").
  4. Generate English subject + body via Claude (language="en") — SIMULTANEOUSLY.
  5. Send German email via send_email (to same lead.email).
  6. Send English email via send_email (to same lead.email).
  7. Create Email DB record with language_versions=["de", "en"] + all 4 fields.
  8. Return {email_id, subject_de, subject_en, body_de, body_en, sent_status="both_sent"}.

CRITICAL: Both German and English are ALWAYS generated and sent.
No conditional branching on lead.language_preference.
Every lead receives both versions simultaneously.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from uuid import uuid4

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.lead import Lead

logger = structlog.get_logger(__name__)

# ── Prompts ────────────────────────────────────────────────────────────────────

OUTREACH_PROMPT_DE = """\
Du bist ein Senior IT-Berater bei Klaravex und antwortest auf eine
eingehende Kontaktanfrage von einem potenziellen Kunden.

Schreibe eine professionelle, persönliche Antwort-E-Mail auf Deutsch.

Regeln:
- Ton: professionell, warm, nicht salesy – wie ein erfahrener Berater, kein
  Marketing-Text.
- Länge: ~150–200 Wörter im Body.
- Beginne die E-Mail mit einer persönlichen Anrede (Name sofern vorhanden, sonst
  "Guten Tag,").
- Beziehe dich direkt auf die Anfrage des Kunden (nutze das Feld "message").
- Schlage konkret vor, in einem kurzen Telefonat / Video-Call Details zu besprechen.
- Signatur: "Freundliche Grüße,\nIhr Klaravex Team"
- Erwähne KEINE Preise.

Liefere das Ergebnis als valides JSON-Objekt mit exakt diesen Feldern:
{{
  "subject": "<Betreffzeile auf Deutsch>",
  "body_text": "<Plain-Text-Body, Zeilenumbrüche mit \\n>",
  "body_html": "<HTML-Body, einfaches HTML ohne <html>/<head>/<body>-Tags>"
}}

Kundendaten:
{lead_context}
"""

OUTREACH_PROMPT_EN = """\
You are a senior IT consultant at Klaravex responding to an incoming
inquiry from a potential client.

Write a professional, personalized follow-up email in English.

Rules:
- Tone: professional, warm, not salesy — like an experienced consultant, not
  marketing copy.
- Length: ~150–200 words in the body.
- Begin the email with a personal greeting (use name if available, otherwise
  "Hello,").
- Directly reference the client's inquiry (use the "message" field).
- Propose concretely to discuss details in a brief call / video meeting.
- Signature: "Best regards,\nYour Klaravex Team"
- Do NOT mention pricing.

Deliver the result as a valid JSON object with exactly these fields:
{{
  "subject": "<Subject line in English>",
  "body_text": "<Plain-text body, newlines as \\n>",
  "body_html": "<HTML body, simple HTML without <html>/<head>/<body> tags>"
}}

Client data:
{lead_context}
"""


class OutreachEmailAgent(BaseAgent):
    name = "outreach_email"
    description = (
        "Generates and sends German + English outreach emails unconditionally to all leads. "
        "Skips COLD leads and leads without an email address. "
        "Both languages sent simultaneously. No approval gate (P2)."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        Generates and sends both German and English outreach emails unconditionally.
        
        input_data: {
            "tier": "HOT" | "WARM" | "COLD" (required)
            "lead_id": str (required)
        }
        
        Returns:
            AgentResult.ok() with {
                "email_id": str,
                "subject_de": str,
                "subject_en": str,
                "body_de": str,
                "body_en": str,
                "sent_status": "both_sent",
                "languages": ["de", "en"],
            }
        """
        tier = input_data.get("tier", "COLD")
        lead_id = context.lead_id or input_data.get("lead_id")

        # Skip COLD leads
        if tier == "COLD":
            logger.info("outreach_email.skipped", reason="COLD lead", lead_id=lead_id)
            return AgentResult.ok(output={"skipped": True, "reason": "COLD lead"})

        if not lead_id:
            return AgentResult.fail("outreach_email: 'lead_id' is required.")

        # Load lead
        result = await context.db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if not lead:
            return AgentResult.fail(f"Lead {lead_id} not found.")

        if not lead.email:
            logger.info("outreach_email.skipped", reason="no email address", lead_id=lead_id)
            return AgentResult.ok(output={"skipped": True, "reason": "no email address"})

        # ── Generate both German and English unconditionally ──────────────────
        lead_context = {
            "name": lead.name or "",
            "company": lead.company or "",
            "email": lead.email,
            "message": lead.message or "",
            "services_interest": lead.services_interest or "[]",
            "score": lead.score,
            "tier": tier,
        }
        context_str = json.dumps(lead_context, ensure_ascii=False, indent=2)

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        # ── SIMULTANEOUS: Draft German and English ────────────────────────────
        try:
            from klara.rarv.runtime.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="OUTREACH_PROMPT_DE",
                content=str(OUTREACH_PROMPT_DE),
            )
        except Exception:
            pass

        try:
            de_task = client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": OUTREACH_PROMPT_DE.format(lead_context=context_str),
                }],
            )
            en_task = client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": OUTREACH_PROMPT_EN.format(lead_context=context_str),
                }],
            )

            # Wait for both to complete simultaneously
            de_response, en_response = await asyncio.gather(de_task, en_task)

            de_raw = de_response.content[0].text.strip()
            en_raw = en_response.content[0].text.strip()
            from klara.rarv.runtime.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=de_response, lead_id=lead_id,
            )
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=en_response, lead_id=lead_id,
            )
        except Exception as exc:
            logger.error("outreach_email.claude_error", error=str(exc), lead_id=lead_id)
            return AgentResult.fail(str(exc))

        # ── Parse JSON from Claude's responses ──────────────────────────────
        email_draft_de = _parse_json(de_raw)
        email_draft_en = _parse_json(en_raw)

        if not email_draft_de:
            logger.error("outreach_email.parse_error_de", raw=de_raw[:200], lead_id=lead_id)
            return AgentResult.fail("Could not parse German email draft from Claude response.")

        if not email_draft_en:
            logger.error("outreach_email.parse_error_en", raw=en_raw[:200], lead_id=lead_id)
            return AgentResult.fail("Could not parse English email draft from Claude response.")

        subject_de = email_draft_de.get("subject", "Ihre Anfrage – Klaravex")
        body_text_de = email_draft_de.get("body_text", "")
        body_html_de = email_draft_de.get("body_html", "")

        subject_en = email_draft_en.get("subject", "Your Inquiry – Klaravex")
        body_text_en = email_draft_en.get("body_text", "")
        body_html_en = email_draft_en.get("body_html", "")

        # ── Send German email ──────────────────────────────────────────────────
        from klara.rarv.runtime.email_sender import send_resend_email

        de_sent = await send_resend_email(
            context.settings,
            to_email=lead.email,
            to_name=lead.name or "",
            subject=subject_de,
            body_html=body_html_de,
            body_text=body_text_de,
        )

        if not de_sent:
            logger.warning(
                "outreach_email.de_send_failed",
                lead_id=lead_id,
                email=lead.email,
            )

        # ── Send English email ─────────────────────────────────────────────────
        en_sent = await send_resend_email(
            context.settings,
            to_email=lead.email,
            to_name=lead.name or "",
            subject=subject_en,
            body_html=body_html_en,
            body_text=body_text_en,
        )

        if not en_sent:
            logger.warning(
                "outreach_email.en_send_failed",
                lead_id=lead_id,
                email=lead.email,
            )

        # ── Log bilingual send ─────────────────────────────────────────────────
        email_id = str(uuid4())
        logger.info(
            "outreach_email.bilingual_sent",
            email_id=email_id,
            lead_id=lead_id,
            tier=tier,
            languages=["de", "en"],
            de_sent=de_sent,
            en_sent=en_sent,
            to=lead.email,
        )

        # ── Return result ──────────────────────────────────────────────────────
        return AgentResult.ok(
            output={
                "email_id": email_id,
                "subject_de": subject_de,
                "subject_en": subject_en,
                "body_de": body_text_de,
                "body_en": body_text_en,
                "sent_status": "both_sent" if (de_sent and en_sent) else "partial_sent",
                "de_sent": de_sent,
                "en_sent": en_sent,
                "languages": ["de", "en"],
                "tier": tier,
                "lead_id": lead_id,
                "to_email": lead.email,
                "tokens_used_de": de_response.usage.output_tokens,
                "tokens_used_en": en_response.usage.output_tokens,
            }
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict | None:
    """Extract the first JSON object from a Claude response string."""
    # Try raw parse first (Claude may return clean JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Extract from markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Find first { ... } span
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None
