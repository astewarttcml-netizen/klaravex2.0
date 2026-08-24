"""
app/agents/callback_intake.py
──────────────────────────────
Processes inbound phone callback requests from the "Rückruf anfordern" form
on German-language WordPress pages.

Unlike form_intake (email required, full qualification flow), callback_intake:
  - Requires phone number, not email
  - Email is optional — many German SMB owners don't include it
  - Stamps callback_requested_at for idempotency
  - Fires lead_alert with phone-first formatting (Anthony needs to call back)
  - Fires discovery_call_prep immediately so Anthony is briefed before calling
  - Does NOT fire calendar_integration (no Calendly link — they gave phone)
  - Does NOT fire outreach_email (no email-first contact — respect the channel)
  - Runs lead_qualification on the message text if provided (for scoring)

GDPR: phone is PII under Art. 4 GDPR. Consent is required at form level.
Source tag: LeadSource.callback_request

Permission: P2 — creates a lead record (internal write).
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.lead import Lead, LeadSource, LeadStatus

logger = structlog.get_logger(__name__)


class CallbackIntakeAgent(BaseAgent):
    name = "callback_intake"
    description = (
        "Creates or updates a Lead record from a phone callback request form "
        "(Rückruf anfordern). Phone is required; email is optional. "
        "Fires a phone-first lead alert to Anthony and generates call prep. "
        "Does not send Calendly invite or outreach email."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        Expected input_data keys:
          phone (required)
          name (optional)
          email (optional)
          company (optional)
          message (optional — "Wie kann ich Ihnen helfen?")
          preferred_callback_time (optional — e.g. "Vormittags", "14:00–16:00")
          gdpr_consent (bool, required)
          gdpr_consent_ip (optional)
        """
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        phone = (input_data.get("phone") or "").strip()
        gdpr_consent = input_data.get("gdpr_consent", False)

        if not phone:
            return AgentResult.fail("callback_intake: 'phone' is required.")

        if not gdpr_consent:
            return AgentResult.fail(
                "GDPR-Einwilligung ist erforderlich. Bitte akzeptieren Sie die Datenschutzerklärung."
            )

        db = context.db
        email_raw = (input_data.get("email") or "").strip().lower() or None

        # ── Upsert logic ──────────────────────────────────────────────────────
        # Match priority: phone → email → create new
        lead: Lead | None = None

        # 1. Try to match by phone first (the primary identifier for callback leads)
        result = await db.execute(
            select(Lead).where(Lead.phone == phone).limit(1)
        )
        lead = result.scalar_one_or_none()

        # 2. If no phone match and we have an email, try that
        if not lead and email_raw:
            result = await db.execute(
                select(Lead).where(Lead.email == email_raw).limit(1)
            )
            lead = result.scalar_one_or_none()

        preferred_time = (input_data.get("preferred_callback_time") or "").strip() or None

        if lead:
            # Update existing lead — never overwrite with empty values
            lead.name = input_data.get("name") or lead.name
            lead.phone = phone  # authoritative — they submitted this form
            if email_raw:
                lead.email = email_raw
            lead.company = input_data.get("company") or lead.company
            lead.message = input_data.get("message") or lead.message
            if preferred_time:
                lead.preferred_callback_time = preferred_time
            # Stamp callback_requested_at only on first callback (idempotency)
            if not lead.callback_requested_at:
                lead.callback_requested_at = datetime.now(timezone.utc)
            log.info("callback_intake.updated_lead", lead_id=lead.id, phone=phone)
        else:
            lead = Lead(
                name=input_data.get("name"),
                email=email_raw,
                phone=phone,
                company=input_data.get("company"),
                message=input_data.get("message"),
                source=LeadSource.callback_request,
                status=LeadStatus.new,
                gdpr_consent=True,
                gdpr_consent_timestamp=datetime.now(timezone.utc),
                gdpr_consent_ip=input_data.get("gdpr_consent_ip"),
                callback_requested_at=datetime.now(timezone.utc),
                preferred_callback_time=preferred_time,
            )
            db.add(lead)
            await db.flush()
            log.info("callback_intake.created_lead", lead_id=lead.id, phone=phone)

        context.lead_id = lead.id

        # ── Lead qualification (non-fatal — score the message if present) ─────
        score = 50  # default mid-tier for callback requests (intent is high)
        tier = "WARM"
        qualification: dict = {}
        message_text = (input_data.get("message") or "").strip()

        if message_text:
            try:
                from app.agents.registry import registry
                qual_agent = registry.get("lead_qualification")
                qual_result = await qual_agent(
                    context,
                    {
                        "name": lead.name or "",
                        "email": lead.email or "",
                        "phone": phone,
                        "company": lead.company or "",
                        "message": message_text,
                        "source": LeadSource.callback_request,
                    },
                )
                if qual_result.success and qual_result.output:
                    qualification = qual_result.output.get("qualification", {})

                    # Run scoring on qualification output
                    score_agent = registry.get("lead_scoring")
                    score_result = await score_agent(
                        context,
                        {"qualification": qualification, "source": LeadSource.callback_request},
                    )
                    if score_result.success and score_result.output:
                        score = score_result.output.get("score", score)
                        tier = score_result.output.get("tier", tier)

                    lead.score = score
                    lead.score_reason = qualification.get("reasoning")
                    lead.status = LeadStatus.qualified
                    log.info(
                        "callback_intake.qualified",
                        lead_id=lead.id,
                        score=score,
                        tier=tier,
                    )
            except Exception as exc:
                # Non-fatal — intake succeeds even if qualification fails
                log.warning("callback_intake.qualification_failed", lead_id=lead.id, error=str(exc))
        else:
            # No message — default to WARM (they took action to request a callback)
            lead.score = score
            lead.status = LeadStatus.qualified
            log.info(
                "callback_intake.no_message_default_warm",
                lead_id=lead.id,
                score=score,
            )

        # ── Alert Anthony — phone-first format ────────────────────────────────
        try:
            from app.agents.registry import registry
            alert = registry.get("lead_alert")
            await alert(
                context,
                {
                    "lead_id": lead.id,
                    "tier": tier,
                    "score": score,
                    "qualification": qualification,
                    "alert_mode": "callback",   # triggers phone-first email variant
                },
            )
            log.info("callback_intake.alert_sent", lead_id=lead.id, tier=tier)
        except Exception as exc:
            log.error("callback_intake.alert_failed", lead_id=lead.id, error=str(exc))

        # ── Discovery call prep — generated immediately so Anthony is briefed ─
        try:
            from app.agents.registry import registry
            prep_agent = registry.get("discovery_call_prep")
            prep_result = await prep_agent(
                context,
                {"lead_id": lead.id, "triggered_by": "callback_intake"},
            )
            if prep_result.success:
                log.info("callback_intake.call_prep_generated", lead_id=lead.id)
            else:
                log.warning(
                    "callback_intake.call_prep_failed",
                    lead_id=lead.id,
                    error=prep_result.error,
                )
        except Exception as exc:
            # Non-fatal — alert is the critical path
            log.error("callback_intake.call_prep_error", lead_id=lead.id, error=str(exc))

        return AgentResult.ok(
            output={
                "lead_id": lead.id,
                "phone": phone,
                "tier": tier,
                "score": score,
                "preferred_callback_time": preferred_time,
                "source": LeadSource.callback_request,
            },
            agent=self.name,
        )
