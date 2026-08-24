"""
app/agents/calendly_webhook.py
───────────────────────────────
P3 agent — processes Calendly webhook events (invitee.created / invitee.canceled).

Closes the booking loop:
  • Matches invitee email → existing Lead
  • Stamps meeting_booked_at, meeting_start_time, calendly_event_uri
  • Advances lead status: new → qualified on booking
  • Auto-triggers discovery_call_prep for the matched lead
  • Sends booking alert to Anthony via LeadAlertAgent

New-lead fallback:
  If no lead matches the invitee email a minimal Lead row is created
  with source=manual so the booking is not lost.

Permission: P3 — creates/modifies internal DB records, sends internal alert.
  No outbound client email is sent by this agent directly.
  discovery_call_prep (P2) is queued — it has its own approval gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select

from klara.rarv.runtime import BaseAgent, AgentContext, AgentResult, PermissionLevel
from klara.rarv.lead import Lead, LeadStatus, LeadSource

logger = structlog.get_logger(__name__)

# Only these statuses can be advanced to 'qualified' on a Calendly booking.
# Higher statuses (discovery_done, proposal_sent, won, lost) are left as-is.
_ADVANCEABLE = {"new", "qualified"}


class CalendlyWebhookAgent(BaseAgent):
    name = "calendly_webhook"
    # Promoted P3 → P2 per phase3-004 (2026-05-24, override of the 30-day data gate).
    # Justification:
    #   - Webhook payloads are HMAC-signed by Calendly (cryptographically
    #     authenticated) so untrusted input is rejected before this agent runs.
    #   - The action is internal-state-only: stamps meeting timestamps and
    #     advances lead status (new → qualified). No outbound client email
    #     is sent from this agent.
    #   - PRD §18 already lists "Update client project stage from verified
    #     backend state" as Auto-allowed; Calendly webhook is the canonical
    #     instance of that pattern. Promotion brings the registry in line
    #     with the decision matrix.
    #   - Rollback risk is bounded: if a stamp is wrong, the same agent
    #     re-runs on the next webhook event and overwrites. No external
    #     side-effects to compensate.
    # Recorded in autonomy_promotions table (migration 0051).
    permission_level = PermissionLevel.P2
    description = (
        "Processes Calendly invitee.created / invitee.canceled webhook events. "
        "Matches invitee to an existing lead by email, stamps meeting timestamps, "
        "advances lead status (new → qualified), queues discovery_call_prep, and "
        "sends a booking alert to Anthony. Creates a minimal stub lead if no match "
        "found. P2 — auto-execute. Verified by HMAC-signed Calendly webhook; "
        "internal DB writes + internal alert only."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        event_type = payload.get("event_type", "")
        # Router pre-extracts invitee + scheduled_event from the raw Calendly body
        invitee = payload.get("invitee", {})
        scheduled_event = payload.get("scheduled_event", {})

        if not invitee:
            log.warning("calendly_webhook.missing_invitee", event_type=event_type)
            return AgentResult.ok({"status": "skipped", "reason": "no_invitee_in_payload"})

        invitee_email = (invitee.get("email") or "").lower().strip()
        invitee_name = invitee.get("name", "")
        event_uri = scheduled_event.get("uri", "")
        start_time_str = scheduled_event.get("start_time", "")
        event_name = scheduled_event.get("name", "")

        log.info(
            "calendly_webhook.received",
            event_type=event_type,
            invitee_email=invitee_email,
            event_uri=event_uri,
        )

        if event_type == "invitee.created":
            return await self._handle_booking(
                context=context,
                log=log,
                invitee_email=invitee_email,
                invitee_name=invitee_name,
                event_uri=event_uri,
                start_time_str=start_time_str,
                event_name=event_name,
            )
        elif event_type == "invitee.canceled":
            return await self._handle_cancellation(
                context=context,
                log=log,
                invitee_email=invitee_email,
                event_uri=event_uri,
            )
        else:
            log.info("calendly_webhook.unhandled_event_type", event_type=event_type)
            return AgentResult.ok({
                "status": "skipped",
                "reason": f"unhandled_event_type:{event_type}",
            })

    # ── invitee.created ───────────────────────────────────────────────────────

    async def _handle_booking(
        self,
        context: AgentContext,
        log: Any,
        invitee_email: str,
        invitee_name: str,
        event_uri: str,
        start_time_str: str,
        event_name: str,
    ) -> AgentResult:
        # Parse start time
        meeting_start_time: datetime | None = None
        if start_time_str:
            try:
                meeting_start_time = datetime.fromisoformat(
                    start_time_str.replace("Z", "+00:00")
                )
            except ValueError:
                log.warning("calendly_webhook.bad_start_time", raw=start_time_str)

        now = datetime.now(timezone.utc)
        lead_created = False

        # ── Find or create lead ───────────────────────────────────────────────
        lead: Lead | None = None
        if invitee_email:
            result = await context.db.execute(
                select(Lead).where(Lead.email == invitee_email).limit(1)
            )
            lead = result.scalar_one_or_none()

        if lead is None:
            log.info("calendly_webhook.lead_not_found_creating_stub", email=invitee_email)
            lead = Lead(
                email=invitee_email,
                name=invitee_name or invitee_email,
                status=LeadStatus.qualified,
                source=LeadSource.manual,
                gdpr_consent=False,   # no consent captured — marketing must not use
                message=f"Created from Calendly booking: {event_name}",
            )
            context.db.add(lead)
            await context.db.flush()   # get lead.id
            lead_created = True
            log.info("calendly_webhook.stub_lead_created", lead_id=lead.id)
        else:
            log.info(
                "calendly_webhook.lead_matched",
                lead_id=lead.id,
                current_status=lead.status,
            )

        # ── Stamp booking fields ──────────────────────────────────────────────
        lead.meeting_booked_at = now
        if meeting_start_time:
            lead.meeting_start_time = meeting_start_time
        if event_uri:
            lead.calendly_event_uri = event_uri

        # ── Advance status: new → qualified only ──────────────────────────────
        # qualified+ statuses are already in the pipeline — no regression.
        status_before = lead.status
        if lead.status == LeadStatus.new:
            lead.status = LeadStatus.qualified
            log.info(
                "calendly_webhook.status_advanced",
                lead_id=lead.id,
                from_status="new",
                to_status="qualified",
            )

        await context.db.flush()

        # ── Audit log ─────────────────────────────────────────────────────────
        try:
            from app.agents.registry import registry
            audit = registry.get("audit_logger")
            await audit(context, {
                "action": "calendly_booking_received",
                "lead_id": str(lead.id),
                "event_type": "invitee.created",
                "event_uri": event_uri,
                "lead_created": lead_created,
                "status_before": str(status_before),
                "status_after": str(lead.status),
            })
        except Exception as exc:
            log.warning("calendly_webhook.audit_failed", error=str(exc))

        # ── Queue discovery_call_prep ─────────────────────────────────────────
        prep_result = None
        try:
            from app.agents.registry import registry
            prep_agent = registry.get("discovery_call_prep")
            prep_result = await prep_agent(context, {
                "lead_id": str(lead.id),
                "triggered_by": "calendly_booking",
                "meeting_start_time": start_time_str,
                "event_name": event_name,
            })
            if not prep_result.success:
                log.warning(
                    "calendly_webhook.prep_agent_failed",
                    lead_id=lead.id,
                    error=prep_result.error,
                )
        except Exception as exc:
            log.warning("calendly_webhook.prep_agent_exception", error=str(exc))

        # ── Alert Anthony ─────────────────────────────────────────────────────
        try:
            from app.agents.registry import registry
            alert = registry.get("lead_alert")
            await alert(context, {
                "lead_id": str(lead.id),
                "alert_type": "calendly_booking",
                "message": (
                    f"📅 New Calendly booking: {invitee_name} ({invitee_email})\n"
                    f"Event: {event_name}\n"
                    f"Start: {start_time_str or 'unknown'}"
                ),
            })
        except Exception as exc:
            log.warning("calendly_webhook.alert_failed", error=str(exc))

        return AgentResult.ok({
            "status": "booking_processed",
            "lead_id": str(lead.id),
            "lead_created": lead_created,
            "status_before": str(status_before),
            "status_after": str(lead.status),
            "meeting_booked_at": now.isoformat(),
            "discovery_prep_success": prep_result.success if prep_result else None,
        })

    # ── invitee.canceled ──────────────────────────────────────────────────────

    async def _handle_cancellation(
        self,
        context: AgentContext,
        log: Any,
        invitee_email: str,
        event_uri: str,
    ) -> AgentResult:
        lead: Lead | None = None
        if invitee_email:
            result = await context.db.execute(
                select(Lead)
                .where(Lead.email == invitee_email)
                .where(Lead.calendly_event_uri == event_uri)
                .limit(1)
            )
            lead = result.scalar_one_or_none()

        if lead is None:
            # Try matching by email alone if URI lookup misses
            if invitee_email:
                result = await context.db.execute(
                    select(Lead)
                    .where(Lead.email == invitee_email)
                    .limit(1)
                )
                lead = result.scalar_one_or_none()

        if lead is None:
            log.info(
                "calendly_webhook.cancellation_no_match",
                email=invitee_email,
                event_uri=event_uri,
            )
            return AgentResult.ok({"status": "cancellation_no_lead_found"})

        log.info(
            "calendly_webhook.cancellation_clearing",
            lead_id=lead.id,
            was_booked_at=str(lead.meeting_booked_at),
        )

        lead.meeting_booked_at = None
        lead.meeting_start_time = None
        lead.calendly_event_uri = None
        await context.db.flush()

        try:
            from app.agents.registry import registry
            alert = registry.get("lead_alert")
            await alert(context, {
                "lead_id": str(lead.id),
                "alert_type": "calendly_cancellation",
                "message": f"❌ Calendly booking canceled: {invitee_email}",
            })
        except Exception as exc:
            log.warning("calendly_webhook.cancel_alert_failed", error=str(exc))

        return AgentResult.ok({
            "status": "cancellation_processed",
            "lead_id": str(lead.id),
        })
