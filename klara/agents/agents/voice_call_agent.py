"""
app/agents/voice_call_agent.py
───────────────────────────────
VoiceCallAgent (P3) — initiates an AI-powered outbound phone call via Vapi.ai
to a lead or newly converted platform client.

Call persona:
  Name: "Anthony" — Klaravex
  Voice: ElevenLabs (configured in Vapi assistant)
  LLM: Claude (claude-sonnet-4-x or configured model)
  Language: English primary, can switch to German if client speaks German

Call objectives:
  1. Introduce Klaravex and confirm project details.
  2. Qualify timeline, budget, and decision-making authority.
  3. Book a follow-up discovery call if not already booked.
  4. Hand off to post_call_processor via Vapi webhook.

P3: Requires human approval in production unless LOKI_MODE=full_autonomy.
In full_autonomy mode this gate is bypassed — calls are placed immediately.

Vapi.ai REST API docs: https://docs.vapi.ai/api-reference
Webhook events processed by VapiWebhookProcessorAgent.

Environment variables required:
  VAPI_API_KEY         — Vapi.ai API key (from dashboard)
  VAPI_PHONE_NUMBER_ID — Vapi phone number ID to call from
  VAPI_ASSISTANT_ID    — Pre-configured Vapi assistant ID
                         (create once in Vapi dashboard, reference here)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import structlog
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)
_VAPI_BASE = "https://api.vapi.ai"


# ── System prompt injected into the Vapi call as assistant context ────────────
_CALL_SYSTEM_PROMPT = """\
You are Anthony, a senior IT consultant at Klaravex. You are calling
a client who responded to your bid or inquiry on a freelance platform.

Your tone: professional, warm, direct — like a senior consultant, not a salesperson.
Keep the call to 5-7 minutes maximum.

Objectives (in order):
1. Confirm you're speaking with the right person (project owner/decision maker).
2. Briefly introduce yourself: "I'm Anthony from Klaravex. You posted
   [project title] — I wanted to introduce myself quickly and see if there's a fit."
3. Ask 2-3 qualifying questions:
   - "What's the timeline you're working with?"
   - "Have you worked with a freelance IT consultant before?"
   - "Are you the right person to discuss the technical and commercial side?"
4. If interested: propose a 30-minute video call this week.
   "I can send you a calendar link — does Tuesday or Wednesday afternoon work?"
5. Close politely regardless of outcome.

IMPORTANT:
- Never discuss pricing on this call.
- If they're not the right contact, ask for a warm introduction.
- If they go to voicemail, leave a concise message:
  "Hi, this is Anthony from Klaravex. I'm following up on the [project title]
  project. I'd love to schedule a quick 5-minute call — I'll send you an email with
  my calendar link. Talk soon."
- Speak naturally. Use the client's name if known.
"""


class VoiceCallAgent(BaseAgent):
    name = "voice_call_agent"
    description = (
        "Initiates an AI-powered outbound phone call via Vapi.ai to a lead or platform client. "
        "Uses Claude as the LLM brain and ElevenLabs voice (configured in Vapi). "
        "P3 — approval gate in production, auto-fires in full_autonomy mode."
    )
    permission_level = PermissionLevel.P3

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data:
          phone_number: str      — E.164 format, e.g. "+491234567890"
          lead_id:      str      — Klara AI lead ID (for context)
          bid_id:       str      — platform bid ID (optional, for context)
          client_name:  str      — client's first name for personalisation
          project_title: str     — project title for call context
          language:     str      — "en" | "de" (default "en")

        Returns AgentResult.ok({
            "vapi_call_id": str,
            "status": "initiated"
        })
        """
        phone_number = input_data.get("phone_number")
        if not phone_number:
            return AgentResult.fail("voice_call_agent: 'phone_number' is required.")

        lead_id = input_data.get("lead_id") or context.lead_id
        bid_id = input_data.get("bid_id")
        client_name = input_data.get("client_name", "there")
        project_title = input_data.get("project_title", "your project")
        language = input_data.get("language", "en")

        vapi_api_key = getattr(context.settings, "vapi_api_key", None)
        vapi_phone_number_id = getattr(context.settings, "vapi_phone_number_id", None)
        vapi_assistant_id = getattr(context.settings, "vapi_assistant_id", None)

        if not vapi_api_key:
            return AgentResult.fail("VAPI_API_KEY not configured.")
        if not vapi_phone_number_id:
            return AgentResult.fail("VAPI_PHONE_NUMBER_ID not configured.")

        # ── Build call payload ────────────────────────────────────────────────
        # If VAPI_ASSISTANT_ID is set, use the pre-configured assistant.
        # Otherwise, define the assistant inline (useful for first-time setup).
        personalised_prompt = (
            _CALL_SYSTEM_PROMPT
            .replace("[project title]", project_title)
            .replace("[client name]", client_name)
        )

        if vapi_assistant_id:
            # Use pre-configured Vapi assistant, override system prompt with
            # project-specific context
            assistant_payload = {
                "assistantId": vapi_assistant_id,
                "assistantOverrides": {
                    "model": {
                        "systemPrompt": personalised_prompt,
                    }
                },
            }
        else:
            # Inline assistant definition (fallback for first setup)
            assistant_payload = {
                "assistant": {
                    "name": "Anthony — Klaravex",
                    "model": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-5",
                        "temperature": 0.6,
                        "systemPrompt": personalised_prompt,
                    },
                    "voice": {
                        "provider": "11labs",
                        "voiceId": "pNInz6obpgDQGcFmaJgB",  # "Adam" voice — change in Vapi dashboard
                    },
                    "firstMessage": (
                        f"Hello, may I speak with {client_name}? "
                        f"This is Anthony calling from Klaravex."
                    ),
                    "firstMessageMode": "assistant-speaks-first",
                    "language": language,
                    "endCallMessage": (
                        "Thank you for your time. I'll send you a calendar link shortly. "
                        "Have a great day!"
                    ),
                    "transcriber": {
                        "provider": "deepgram",
                        "model": "nova-2",
                        "language": language,
                    },
                    "maxDurationSeconds": 480,   # 8 minutes max
                    "silenceTimeoutSeconds": 30,
                    "backgroundSound": "off",
                    "backgroundDenoisingEnabled": True,
                    "serverMessages": ["end-of-call-report", "transcript"],
                },
            }

        call_payload = {
            **assistant_payload,
            "phoneNumberId": vapi_phone_number_id,
            "customer": {
                "number": phone_number,
                "name": client_name,
            },
            "metadata": {
                "lead_id": lead_id or "",
                "bid_id": bid_id or "",
                "project_title": project_title,
                "initiated_by": "loki_voice_call_agent",
            },
        }

        # ── Make the call ─────────────────────────────────────────────────────
        try:
            async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
                async with session.post(
                    f"{_VAPI_BASE}/call/phone",
                    headers={
                        "Authorization": f"Bearer {vapi_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=call_payload,
                ) as resp:
                    data = await resp.json()
                    if resp.status not in (200, 201):
                        error_msg = (
                            data.get("message")
                            or data.get("error")
                            or f"HTTP {resp.status}"
                        )
                        logger.error(
                            "voice_call_agent.vapi_error",
                            status=resp.status,
                            error=error_msg,
                            lead_id=lead_id,
                        )
                        return AgentResult.fail(f"Vapi API error: {error_msg}")

                    vapi_call_id = data.get("id", "")

        except Exception as exc:
            logger.error(
                "voice_call_agent.http_error",
                error=str(exc),
                lead_id=lead_id,
            )
            return AgentResult.fail(str(exc))

        # ── Store call ID on bid if provided ──────────────────────────────────
        if bid_id and vapi_call_id:
            try:
                from klara.rarv.platform_bid import PlatformBid
                bid_q = await context.db.execute(
                    select(PlatformBid).where(PlatformBid.id == bid_id)
                )
                bid = bid_q.scalar_one_or_none()
                if bid:
                    bid.vapi_call_id = vapi_call_id
                    await context.db.commit()
            except Exception as exc:
                logger.warning(
                    "voice_call_agent.bid_update_error",
                    bid_id=bid_id,
                    error=str(exc),
                )

        logger.info(
            "voice_call_agent.call_initiated",
            vapi_call_id=vapi_call_id,
            phone=phone_number[:6] + "****",
            lead_id=lead_id,
            project=project_title[:50],
        )

        return AgentResult.ok(
            output={
                "vapi_call_id": vapi_call_id,
                "status": "initiated",
                "phone_number": phone_number[:6] + "****",
                "lead_id": lead_id,
                "bid_id": bid_id,
            }
        )
