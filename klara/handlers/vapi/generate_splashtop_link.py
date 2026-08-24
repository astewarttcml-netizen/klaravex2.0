"""A9 Vapi tool: generate_splashtop_link.

When voice walkthrough hits a wall, Vapi calls this to mint an Atera
Splashtop SOS attended session URL and deliver it to the caller via SMS,
email, or both. Returns rich metadata so Klara can verbalise EXACTLY
what the caller should look for ("a text from area code 424" /
"an email from support@klaravex.com").

Older-caller optimisations (2026-06-10):
  - SMS body now includes brand attribution + the caller's first name
    when available, plus a "from Klara" line so older callers know
    who sent it.
  - Email path is now fully implemented (was previously declared but
    not wired). Older callers often check email more reliably than SMS.
  - Returns delivery_summary with sender hint + arrival time estimate
    so the Vapi assistant can walk the caller through finding it.
  - Returns delivered_via list so the assistant knows which channels
    actually succeeded and can offer the other if needed.

See WORKFLOWS.md §A9.5 step 5.
"""

import asyncio
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

log = logging.getLogger("klaravex.vapi.splashtop")
router = APIRouter()

ATERA_API_KEY = os.environ.get("ATERA_API_KEY", "")
ATERA_BASE = os.environ.get("ATERA_BASE_URL", "https://app.atera.com/api/v3")
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER", "")


class SplashtopRequest(BaseModel):
    caller_email: EmailStr | None = None
    caller_phone: str | None = None
    caller_first_name: str | None = None
    # Older-caller default — email is friendlier than tap-this-link SMS. The
    # Vapi assistant should ask "what's the best email address to send it to?"
    # rather than assuming the phone number on file is the right channel.
    # Pass delivery="sms" explicitly only if the caller asks for a text.
    delivery: str = Field(default="email", pattern="^(sms|email|both)$")
    test: bool = Field(default=False, alias="_test")


def _sender_hint_for_phone() -> str:
    """Human-readable hint about who the SMS will appear from."""
    if not TWILIO_FROM:
        return "Klaravex"
    # Extract area code from E.164 format (+14243486010 → 424)
    digits = "".join(c for c in TWILIO_FROM if c.isdigit())
    if len(digits) >= 4 and digits.startswith("1"):
        return f"area code {digits[1:4]}"
    return TWILIO_FROM


async def _send_sms(to: str, body: str) -> tuple[bool, str]:
    """Delegates to the gated lib.sms helper so SMS_ENABLED is honored centrally."""
    from ..lib.sms import send_sms as _gated
    return await _gated(to, body, source="splashtop_link")


async def _send_email(to: str, url: str, first_name: str | None) -> tuple[bool, str]:
    """Wraps lib.email.send_email. Returns (ok, error_or_empty)."""
    try:
        # Imported lazily so module-import works even when MS Graph creds are absent.
        from ..lib.email import send_email
    except Exception as exc:  # noqa: BLE001
        return False, f"email lib unavailable: {exc}"

    name_line = f"Hi {first_name}," if first_name else "Hi,"
    body = (
        f"{name_line}\n\n"
        "This is Klara at Klaravex. I sent you a screen-share link so we can\n"
        "look at what you're seeing together. Tap the link below from your\n"
        "phone, tablet, or computer:\n\n"
        f"  {url}\n\n"
        "After you tap it, you'll be asked to allow screen sharing. Say yes —\n"
        "I'll only be able to see your screen for this one session, and you\n"
        "can stop it any time by closing the app.\n\n"
        "If anything doesn't work or you can't find this email, just call us\n"
        "back at +1 (424) 348-6010 and we'll try a different way.\n\n"
        "Klaravex Support\n"
        "support@klaravex.com · +1 (424) 348-6010"
    )
    try:
        await send_email(
            to=to,
            subject="Klaravex screen-share link",
            body=body,
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001
        log.warning("splashtop email exception: %s", exc)
        return False, str(exc)[:120]


def _build_sms_body(url: str, first_name: str | None) -> str:
    """Friendly SMS body that older callers can recognise as legitimate."""
    name = f" {first_name}" if first_name else ""
    return (
        f"Hi{name}, this is Klara at Klaravex. Tap this link to start the "
        f"screen-share session so we can fix this together:\n\n{url}\n\n"
        f"If the link doesn't work, call us back at +1 (424) 348-6010."
    )


@router.post("/generate_splashtop_link")
async def generate_splashtop_link(req: SplashtopRequest) -> dict[str, Any]:
    if req.test:
        url = "https://sos.splashtop.com/test"
        return {
            "status": "ok",
            "test": True,
            "url": url,
            "delivered_via": [],
            "delivery_summary": "test mode — no message actually sent",
        }
    if not ATERA_API_KEY:
        raise HTTPException(status_code=503, detail="atera not configured")

    # 1. Mint the Splashtop SOS session URL via Atera.
    # Atera's API auth is `Authorization: Bearer <jwt>` — NOT X-Api-Key.
    # The X-Api-Key header silently returns 401 even when the JWT is valid,
    # which was the root cause of every splashtop_sos 401 in production.
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{ATERA_BASE}/splashtop-sos-session",
            headers={
                "Authorization": f"Bearer {ATERA_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"NotifyEmail": str(req.caller_email or "")},
        )
        if r.status_code >= 300:
            log.error("atera sos session failed: %s %s", r.status_code, r.text)
            raise HTTPException(status_code=502, detail="atera unavailable")
        body = r.json()
        url = body.get("SessionUrl") or body.get("Url") or ""
        session_id = body.get("SessionId") or body.get("Id") or ""

    if not url:
        raise HTTPException(status_code=502, detail="atera returned no session url")

    # 2. Deliver via the requested channels. If the caller asked for SMS but
    #    SMS is disabled at the platform level (Twilio account not yet
    #    approved for outbound, see lib.sms), fall back to email so we
    #    don't tell the caller "I just texted you" and have nothing arrive.
    from ..lib.sms import sms_enabled
    effective_delivery = req.delivery
    sms_degraded = False
    if req.delivery in ("sms", "both") and not sms_enabled():
        sms_degraded = True
        if req.caller_email:
            effective_delivery = "email"  # quietly substitute
        else:
            effective_delivery = "sms"  # still attempt — _send_sms will return sms_disabled

    tasks: list[Any] = []
    delivered_via: list[str] = []
    delivery_errors: list[str] = []

    if effective_delivery in ("sms", "both") and req.caller_phone:
        sms_body = _build_sms_body(url, req.caller_first_name)
        tasks.append(("sms", _send_sms(req.caller_phone, sms_body)))

    if effective_delivery in ("email", "both") and req.caller_email:
        tasks.append(("email", _send_email(str(req.caller_email), url, req.caller_first_name)))

    if tasks:
        results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
        for (channel, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                delivery_errors.append(f"{channel}: {result}")
                continue
            ok, err = result
            if ok:
                delivered_via.append(channel)
            else:
                delivery_errors.append(f"{channel}: {err}")

    # 3. Build a delivery_summary the Vapi assistant can read back to the caller.
    #    This is the single most useful field for older callers — it tells the
    #    assistant EXACTLY what hint to give ("look for a text from area code 424").
    if "sms" in delivered_via and "email" in delivered_via:
        summary = (
            f"Sent two ways — a text message from {_sender_hint_for_phone()} "
            f"(should arrive in under 30 seconds) and an email from "
            f"support@klaravex.com (may take a minute or two)."
        )
    elif "sms" in delivered_via:
        summary = (
            f"Sent a text message from {_sender_hint_for_phone()}. It should "
            f"arrive in under 30 seconds. Tap the link in the message to start."
        )
    elif "email" in delivered_via:
        summary = (
            "Sent an email from support@klaravex.com. It usually arrives in a "
            "minute or two. If it goes to spam, please check there too."
        )
    else:
        summary = (
            "I couldn't send the link automatically. Please go to "
            "https://klaravex.com/support and enter session code "
            f"{session_id or url[-8:]} to start the session."
        )

    response: dict[str, Any] = {
        "status": "ok" if delivered_via else "delivery_failed",
        "url": url,
        "session_id": session_id,
        "delivered_via": delivered_via,
        "delivery_summary": summary,
    }
    if sms_degraded:
        # Surface the degrade so the Vapi assistant can adjust its language.
        response["sms_degraded"] = True
        response["sms_degraded_reason"] = "sms_temporarily_unavailable_substituted_email"
    if delivery_errors:
        response["delivery_errors"] = delivery_errors
    return response
