"""
app/api/webhooks.py
────────────────────
WordPress webhook receiver.

POST /api/v1/webhooks/wordpress

WordPress fires this hook on:
  - New contact form submission (plugin: WPForms / CF7 / Gravity Forms)
  - New post published (for content-aware routing in future)
  - WooCommerce order (if services are sold via WC in future)

Security: every request MUST carry X-WP-Signature: sha256=<hmac>
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, Optional

from app.agents.base import AgentContext
from app.agents.registry import registry
from app.config import get_settings, Settings
from app.core.security import verify_wp_webhook_signature
from app.database import get_db

router = APIRouter()


class WPWebhookPayload(BaseModel):
    event: str                        # e.g. "form_submission", "post_published"
    form_id: Optional[str] = None
    fields: Optional[dict[str, Any]] = None   # form field values
    post_id: Optional[str] = None
    post_type: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


@router.post("/wordpress", status_code=status.HTTP_200_OK)
async def wordpress_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_wp_signature: Optional[str] = Header(None, alias="X-WP-Signature"),
):
    """
    Receive WordPress webhooks.

    Authentication: HMAC-SHA256 signature over the raw body,
    using WP_WEBHOOK_SECRET.  Returns 403 on invalid signature.
    """
    body = await request.body()

    # Verify HMAC signature
    if not verify_wp_webhook_signature(body, x_wp_signature or ""):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature.",
        )

    # Parse body
    try:
        import json
        payload_dict = json.loads(body)
        payload = WPWebhookPayload(**payload_dict)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload.",
        )

    context = AgentContext(db=db, settings=settings)

    # Dispatch on event type
    if payload.event == "form_submission":
        return await _handle_form_submission(context, payload)
    elif payload.event == "callback_request":
        return await _handle_callback_request(context, payload)
    elif payload.event == "post_published":
        # Stub — future content agent will handle this
        return {"status": "acknowledged", "event": "post_published", "action": "queued"}
    else:
        # Log unknown events but don't error — WordPress sends many event types
        from app.agents.registry import registry as reg
        audit = reg.get("audit_logger")
        await audit(
            context,
            {
                "event_type": "webhook.unknown_event",
                "details": {"wp_event": payload.event},
                "success": True,
            },
        )
        return {"status": "acknowledged", "event": payload.event, "action": "ignored"}


async def _handle_form_submission(context: AgentContext, payload: WPWebhookPayload):
    """Map WP form fields to our lead schema and run the form pipeline."""
    fields = payload.fields or {}

    # Common field name mappings across WPForms / CF7 / Gravity Forms
    name = fields.get("name") or fields.get("your-name") or fields.get("field_1", "")
    email = fields.get("email") or fields.get("your-email") or fields.get("field_2", "")
    message = fields.get("message") or fields.get("your-message") or fields.get("field_3", "")
    company = fields.get("company") or fields.get("field_4")
    gdpr = fields.get("gdpr_consent") or fields.get("privacy_policy") or False

    if isinstance(gdpr, str):
        gdpr = gdpr.lower() in ("true", "yes", "1", "on")

    if not email:
        return {"status": "skipped", "reason": "no_email_field"}

    loki = registry.get("loki_orchestrator")
    result = await loki(
        context,
        {
            "pipeline": "form",
            "payload": {
                "session_token": f"wp-form-{email}",
                "name": name,
                "email": email,
                "company": company,
                "message": message,
                "services_interest": [],
                "gdpr_consent": gdpr,
                "source": "wp_webhook",
                "channel": "wp_webhook",
            },
        },
    )

    return {
        "status": "processed",
        "event": "form_submission",
        "lead_id": context.lead_id,
        "approval_required": result.approval_required,
    }


async def _handle_callback_request(context: AgentContext, payload: WPWebhookPayload):
    """
    Handle Rückruf anfordern (phone callback) form submissions.

    Expected fields (WPForms field names):
      phone                  — required
      name                   — optional
      email                  — optional
      company                — optional
      message / nachricht    — optional (free-text inquiry)
      callback_time          — optional (preferred callback window)
      gdpr_consent           — required (must be truthy)
      gdpr_consent_ip        — optional (set by WPForms)

    Phone is the primary identifier — email is NOT required.
    Runs CallbackIntakeAgent directly (no orchestrator pipeline needed).
    """
    fields = payload.fields or {}

    phone = (
        fields.get("phone")
        or fields.get("telefon")
        or fields.get("telefonnummer")
        or fields.get("field_phone")
        or ""
    ).strip()

    name = (
        fields.get("name")
        or fields.get("vorname_nachname")
        or fields.get("field_name")
        or ""
    ).strip()

    email = (
        fields.get("email")
        or fields.get("e-mail")
        or fields.get("field_email")
        or ""
    ).strip().lower() or None

    company = (
        fields.get("company")
        or fields.get("unternehmen")
        or fields.get("firma")
        or fields.get("field_company")
        or None
    )

    message = (
        fields.get("message")
        or fields.get("nachricht")
        or fields.get("anliegen")
        or fields.get("field_message")
        or ""
    ).strip() or None

    callback_time = (
        fields.get("callback_time")
        or fields.get("rueckruf_zeit")
        or fields.get("preferred_time")
        or fields.get("zeitfenster")
        or None
    )

    gdpr = fields.get("gdpr_consent") or fields.get("datenschutz") or False
    if isinstance(gdpr, str):
        gdpr = gdpr.lower() in ("true", "yes", "1", "on", "ja")

    gdpr_ip = fields.get("gdpr_consent_ip") or payload.meta and payload.meta.get("user_ip")

    if not phone:
        return {"status": "skipped", "reason": "no_phone_field"}

    callback_agent = registry.get("callback_intake")
    result = await callback_agent(
        context,
        {
            "phone": phone,
            "name": name or None,
            "email": email,
            "company": company,
            "message": message,
            "preferred_callback_time": callback_time,
            "gdpr_consent": gdpr,
            "gdpr_consent_ip": gdpr_ip,
        },
    )

    return {
        "status": "processed",
        "event": "callback_request",
        "lead_id": context.lead_id,
        "phone": phone,
        "success": result.success,
    }
