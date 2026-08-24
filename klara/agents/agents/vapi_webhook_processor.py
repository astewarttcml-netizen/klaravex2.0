"""
app/agents/vapi_webhook_processor.py
──────────────────────────────────────
VapiWebhookProcessorAgent (P2) — processes incoming Vapi.ai call event
webhooks and feeds call transcripts into the post_call_processor pipeline.

Vapi sends webhook events to POST /api/v1/webhooks/vapi
Events handled:
  - "end-of-call-report"  → extract transcript, summary, call duration
  - "transcript"          → real-time transcript chunks (ignored for now)
  - "call-started"        → log and return 200
  - "call-ended"          → log and return 200

On "end-of-call-report":
  1. Extract transcript and call summary from Vapi payload.
  2. Identify lead_id from call.metadata.
  3. Update PlatformBid.call_completed_at + call_outcome (if bid_id in metadata).
  4. Fire post_call_processor agent with the transcript.
  5. Return { processed: true }.

P2 — internal write, no approval gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)


class VapiWebhookProcessorAgent(BaseAgent):
    name = "vapi_webhook_processor"
    description = (
        "Processes Vapi.ai call event webhooks. On end-of-call-report, extracts the "
        "transcript and fires post_call_processor. Updates PlatformBid call outcome. P2."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data: raw Vapi webhook payload (dict)

        Returns AgentResult.ok({ "processed": bool, "event_type": str })
        """
        event_type = (
            input_data.get("type")
            or input_data.get("message", {}).get("type")
            or "unknown"
        )

        logger.info(
            "vapi_webhook_processor.received",
            event_type=event_type,
        )

        if event_type == "end-of-call-report":
            return await self._handle_end_of_call(context, input_data)

        # All other event types — ack and return
        return AgentResult.ok(output={"processed": True, "event_type": event_type})

    async def _handle_end_of_call(
        self, context: AgentContext, payload: dict
    ) -> AgentResult:
        """Process end-of-call-report from Vapi."""
        # Vapi wraps everything under "message" in some webhook versions
        msg = payload.get("message", payload)

        call = msg.get("call", {})
        vapi_call_id = call.get("id") or msg.get("callId", "")
        call_duration_secs = msg.get("durationSeconds") or call.get("duration", 0)
        ended_reason = msg.get("endedReason") or call.get("endedReason", "unknown")

        # Extract metadata (set when call was created)
        metadata = call.get("metadata") or {}
        lead_id = metadata.get("lead_id") or context.lead_id
        bid_id = metadata.get("bid_id")
        project_title = metadata.get("project_title", "")

        # Extract transcript
        transcript = _extract_transcript(msg)
        summary = msg.get("summary") or msg.get("analysis", {}).get("summary", "")

        # Determine call outcome from ended_reason + summary
        call_outcome = _classify_outcome(ended_reason, summary, transcript)

        logger.info(
            "vapi_webhook_processor.end_of_call",
            vapi_call_id=vapi_call_id,
            lead_id=lead_id,
            bid_id=bid_id,
            duration_secs=call_duration_secs,
            outcome=call_outcome,
            ended_reason=ended_reason,
        )

        # ── Update PlatformBid ────────────────────────────────────────────────
        if bid_id:
            try:
                from app.models.platform_bid import PlatformBid
                bid_q = await context.db.execute(
                    select(PlatformBid).where(PlatformBid.id == bid_id)
                )
                bid = bid_q.scalar_one_or_none()
                if bid:
                    bid.call_completed_at = datetime.now(tz=timezone.utc)
                    bid.call_outcome = call_outcome
                    await context.db.commit()
            except Exception as exc:
                logger.warning(
                    "vapi_webhook_processor.bid_update_error",
                    bid_id=bid_id,
                    error=str(exc),
                )

        # ── Fire post_call_processor ──────────────────────────────────────────
        if transcript and lead_id:
            try:
                from app.agents.registry import get_registry
                registry = get_registry()
                post_call = registry.get("post_call_processor")

                if post_call:
                    call_ctx = AgentContext(
                        db=context.db,
                        settings=context.settings,
                        lead_id=lead_id,
                        conversation_id=context.conversation_id,
                        request_id=context.request_id,
                    )
                    call_result = await post_call.run(
                        call_ctx,
                        {
                            "lead_id": lead_id,
                            "transcript": transcript,
                            "summary": summary,
                            "call_duration_secs": call_duration_secs,
                            "call_outcome": call_outcome,
                            "vapi_call_id": vapi_call_id,
                            "project_title": project_title,
                            "source": "vapi_outbound",
                        },
                    )
                    logger.info(
                        "vapi_webhook_processor.post_call_fired",
                        lead_id=lead_id,
                        success=call_result.success,
                    )
            except Exception as exc:
                logger.error(
                    "vapi_webhook_processor.post_call_error",
                    lead_id=lead_id,
                    error=str(exc),
                )
        elif not transcript:
            logger.info(
                "vapi_webhook_processor.no_transcript",
                vapi_call_id=vapi_call_id,
                ended_reason=ended_reason,
            )

        return AgentResult.ok(
            output={
                "processed": True,
                "event_type": "end-of-call-report",
                "vapi_call_id": vapi_call_id,
                "lead_id": lead_id,
                "bid_id": bid_id,
                "call_outcome": call_outcome,
                "duration_secs": call_duration_secs,
            }
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_transcript(msg: dict) -> str:
    """
    Vapi transcript can appear in multiple forms depending on webhook version.
    Try each known location in order of preference.
    """
    # 1. Formatted transcript string
    if msg.get("transcript"):
        return msg["transcript"]

    # 2. Array of transcript objects [{role, message}]
    transcript_arr = msg.get("messages") or msg.get("transcriptMessages") or []
    if transcript_arr and isinstance(transcript_arr, list):
        lines = []
        for t in transcript_arr:
            role = t.get("role", "unknown").title()
            text = t.get("message") or t.get("content") or ""
            if text:
                lines.append(f"{role}: {text}")
        if lines:
            return "\n".join(lines)

    # 3. Analysis object
    analysis = msg.get("analysis", {})
    if analysis.get("transcript"):
        return analysis["transcript"]

    return ""


def _classify_outcome(
    ended_reason: str,
    summary: str,
    transcript: str,
) -> str:
    """
    Classify call outcome from Vapi metadata.
    Returns one of: interested | not_interested | no_answer | voicemail | unknown
    """
    reason_lower = (ended_reason or "").lower()
    summary_lower = (summary or "").lower()
    transcript_lower = (transcript or "").lower()

    if any(r in reason_lower for r in ("no-answer", "voicemail", "machine")):
        return "voicemail" if "voicemail" in reason_lower else "no_answer"

    if "customer-did-not-answer" in reason_lower:
        return "no_answer"

    # Sentiment analysis on summary/transcript
    positive_signals = [
        "interested", "yes", "sounds good", "let's schedule", "book", "calendar",
        "love to", "great", "perfect", "follow up", "call you back",
    ]
    negative_signals = [
        "not interested", "no thanks", "don't need", "already have",
        "found someone", "decided to go", "not right now",
    ]

    combined = summary_lower + " " + transcript_lower
    pos_count = sum(1 for s in positive_signals if s in combined)
    neg_count = sum(1 for s in negative_signals if s in combined)

    if neg_count > 0:
        return "not_interested"
    if pos_count >= 2:
        return "interested"

    return "unknown"
