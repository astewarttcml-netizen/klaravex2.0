"""
app/agents/atera_ticket_creator.py
────────────────────────────────────
P2 agent — creates an Atera PSA ticket for a qualified consumer support request,
then generates a Stripe Checkout Session so the user has a payment link ready.

Triggered by: consumer pipeline after consumer_intake returns [CONSUMER_READY].
Also callable directly via POST /api/v1/agents/run with agent="atera_ticket_creator".

Flow:
  1. Extract consumer info from pipeline payload
  2. Get or create Atera customer ("Personal Clients") and contact
  3. Create ticket with problem description
  4. Create Stripe Checkout Session (Standard $100 default; adjustable post-session)
  5. Return ticket ID + friendly confirmation message with payment link

Permission: P2 — user explicitly requested support; this is not cold outreach.
The ticket itself is internal to Atera; no email is sent to the user from here.
Anthony will initiate the remote session from the Atera portal.

Stripe fallback: if STRIPE_SECRET_KEY is not configured the payment link step
is skipped and the reply omits the payment URL without failing the pipeline.
Atera fallback: if ATERA_API_KEY is not configured the reply is a generic
"we'll contact you" message.
"""
from __future__ import annotations

import structlog

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

_FALLBACK_REPLY_EN = (
    "Thanks for reaching out! A member of our support team will contact you "
    "at the email address you provided within a few hours to arrange a remote session."
)
_FALLBACK_REPLY_DE = (
    "Vielen Dank! Ein Mitglied unseres Support-Teams wird sich in Kürze mit Ihnen "
    "in Verbindung setzen, um eine Remote-Sitzung zu vereinbaren."
)


class AteraTicketCreatorAgent(BaseAgent):
    name = "atera_ticket_creator"
    description = (
        "Creates an Atera PSA support ticket for a qualified consumer support request. "
        "Gets or creates the consumer as an Atera contact, then opens a ticket. "
        "Returns ticket ID and a chat confirmation message. P2 — user-requested."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
        )

        # Only act when intake flagged CONSUMER_READY
        consumer_status = input_data.get("consumer_status", "")
        if consumer_status != "CONSUMER_READY":
            return AgentResult.ok({
                "ticket_created": False,
                "reason": f"consumer_status={consumer_status!r} — no ticket needed",
            })

        api_key = getattr(context.settings, "atera_api_key", "")
        if not api_key:
            log.warning("atera_ticket_creator.no_api_key")
            lang = input_data.get("language", "en")
            return AgentResult.ok({
                "ticket_created": False,
                "reply": _FALLBACK_REPLY_DE if lang == "de" else _FALLBACK_REPLY_EN,
                "reason": "ATERA_API_KEY not configured",
            })

        # Extract consumer details — prefer visitor_name/visitor_email from intake output,
        # then fall back to the raw payload fields passed from the API endpoint.
        name = (
            input_data.get("visitor_name")
            or input_data.get("name")
            or "Unknown"
        )
        email = (
            input_data.get("visitor_email")
            or input_data.get("email")
            or ""
        )
        device = input_data.get("device", "")
        problem = input_data.get("problem", "Remote support request via chat")
        phone = input_data.get("phone", "")
        language = input_data.get("language", "en")

        if not email:
            log.warning("atera_ticket_creator.no_email")
            return AgentResult.ok({
                "ticket_created": False,
                "reply": (
                    "To create your support ticket, I need your email address. "
                    "Could you share it so our support team can reach you?"
                ),
                "reason": "no email provided",
            })

        from klara.rarv.runtime.atera_client import AteraClient, AteraError
        client = AteraClient(api_key=api_key)
        try:
            result = await client.onboard_consumer(
                name=name,
                email=email,
                problem=problem,
                device=device,
                phone=phone,
            )
        except AteraError as exc:
            log.error("atera_ticket_creator.api_error", error=str(exc))
            return AgentResult.ok({
                "ticket_created": False,
                "reply": _FALLBACK_REPLY_DE if language == "de" else _FALLBACK_REPLY_EN,
                "reason": f"Atera API error: {exc}",
            })
        except Exception as exc:
            log.error("atera_ticket_creator.unexpected_error", error=str(exc))
            return AgentResult.ok({
                "ticket_created": False,
                "reply": _FALLBACK_REPLY_DE if language == "de" else _FALLBACK_REPLY_EN,
                "reason": f"unexpected error: {exc}",
            })

        ticket_number = result["ticket_number"]
        first_name = name.split()[0] if name and name != "Unknown" else ""
        greeting = f"Hi {first_name}! " if first_name else ""

        # ── Stripe payment link ───────────────────────────────────────────────
        payment_url: str = ""
        stripe_session_id: str = ""
        if context.settings.stripe_configured:
            try:
                from klara.rarv.runtime.stripe_consumer import (
                    create_consumer_checkout_session,
                    TIER_STANDARD,
                )
                tier_name, tier_cents = TIER_STANDARD
                checkout = await create_consumer_checkout_session(
                    api_key=context.settings.stripe_secret_key,
                    amount_cents=tier_cents,
                    description=f"Remote IT Support — {tier_name}",
                    customer_email=email,
                    success_url=context.settings.stripe_success_url.replace(
                        "{INVOICE_ID}", f"ticket-{result['ticket_id']}"
                    ),
                    cancel_url=context.settings.stripe_cancel_url.replace(
                        "{INVOICE_ID}", f"ticket-{result['ticket_id']}"
                    ),
                    metadata={
                        "ticket_id": str(result["ticket_id"]),
                        "ticket_number": ticket_number,
                        "contact_id": str(result["contact_id"]),
                        "customer_email": email,
                        "customer_name": name,
                        "customer_phone": phone,
                        "device": device,
                        "problem": problem[:500],
                        "source": "consumer_pipeline",
                    },
                )
                payment_url = checkout["url"]
                stripe_session_id = checkout["session_id"]
            except Exception as exc:
                log.warning("atera_ticket_creator.stripe_skipped", error=str(exc))

        # ── Build reply ───────────────────────────────────────────────────────
        if language == "de":
            if payment_url:
                reply = (
                    f"{greeting}Ihr Support-Ticket wurde erstellt (#{ticket_number}).\n\n"
                    f"Bitte bezahlen Sie Ihre Sitzung sicher über diesen Link:\n"
                    f"{payment_url}\n\n"
                    f"Preise: Quick Fix (≤ 30 Min.) – $50 | Standard (≤ 1 Std.) – $100 | "
                    f"Erweitert (> 1 Std.) – $150/Std. Die endgültige Abrechnung erfolgt nach "
                    f"der Sitzung — Differenzen werden erstattet.\n\n"
                    f"Ein Klaravex-Techniker wird sich innerhalb weniger Stunden an {email} melden, "
                    f"um die Remote-Sitzung zu starten."
                )
            else:
                reply = (
                    f"{greeting}Ich habe ein Support-Ticket für Sie erstellt (#{ticket_number}). "
                    f"Ein Klaravex-Techniker wird sich innerhalb weniger Stunden an {email} bei Ihnen melden, "
                    f"um eine Remote-Sitzung zu vereinbaren. Bitte halten Sie Ihren Computer bereit."
                )
        else:
            if payment_url:
                reply = (
                    f"{greeting}Your support ticket has been created (#{ticket_number}).\n\n"
                    f"Please pay for your session securely here:\n"
                    f"{payment_url}\n\n"
                    f"Pricing: Quick Fix (under 30 min) – $50 | Standard (up to 1 hr) – $100 | "
                    f"Extended (over 1 hr) – $150/hr. Final billing is based on actual session "
                    f"length — you'll be refunded if it runs shorter.\n\n"
                    f"A Klaravex technician will reach out to {email} within a few hours to start your remote session."
                )
            else:
                reply = (
                    f"{greeting}Your support ticket has been created (#{ticket_number}). "
                    f"A Klaravex technician will reach out to {email} within a few hours to set up a remote session. "
                    f"Please make sure your device is powered on and connected to the internet."
                )

        log.info(
            "atera_ticket_creator.success",
            ticket_id=result["ticket_id"],
            ticket_number=ticket_number,
            contact_id=result["contact_id"],
            stripe_session_id=stripe_session_id or None,
        )

        return AgentResult.ok({
            "ticket_created": True,
            "ticket_id": result["ticket_id"],
            "ticket_number": ticket_number,
            "contact_id": result["contact_id"],
            "payment_url": payment_url,
            "stripe_session_id": stripe_session_id,
            "reply": reply,
        })
