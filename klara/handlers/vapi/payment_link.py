"""A9 Vapi tool: payment_link.

Generates a Stripe Checkout Session prefilled with caller email + call_sid
metadata, sends link via SMS (preferred) or email, and returns the URL so
Vapi can read it back to the caller. See WORKFLOWS.md §A9.4.
"""

import logging
import os
from typing import Any

import httpx
import stripe
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from ..lib.email import send_email

log = logging.getLogger("klaravex.vapi.payment_link")
router = APIRouter()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_TEST_KEY = os.environ.get("STRIPE_SECRET_KEY_TEST", "")
# Stripe coupon ID for the job-loss self-attestation discount (50% off).
# Create once in Stripe dashboard: Coupons → "Job Loss 50%" → 50% off, no expiry.
# Set STRIPE_JOB_LOSS_COUPON_ID to that coupon's ID in the env.
STRIPE_JOB_LOSS_COUPON_ID = os.environ.get("STRIPE_JOB_LOSS_COUPON_ID", "")
TEST_CALLER_PHONES = set(
    p.strip() for p in os.environ.get("TEST_CALLER_PHONES", "").split(",") if p.strip()
)
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER", "")

# Hardcoded Stripe price IDs — do not use env vars for price IDs.
# Consumer SKUs
SKU_PRICE_MAP: dict[str, str] = {
    "per-incident":            "price_1TvQqI14iRJDip4yBEGW2tUb",  # $29 flat, revised 2026-07-21 (was $39, was $79)
    "essentials":              "price_1TtnI614iRJDip4yI18E1VNO",  # $29/mo, revised 2026-07-16 (was $24/mo)
    "family-senior":           "price_1TtnI614iRJDip4yZXbgYR3R",  # $39/mo, revised 2026-07-16 (was $19/mo)
    "home-membership":         "price_1TfPfQ14iRJDip4yxDlFw3Ei",
    "resume-basic":            "price_1TtnIm14iRJDip4yphE3tmOQ",  # $79, revised 2026-07-16 (was $199, INACTIVE — checkout was broken)
    "resume-premium":          "price_1TtnIm14iRJDip4yoFbpzTf2",  # $149, revised 2026-07-16 (was $499, INACTIVE — checkout was broken)
    "resume-executive":        "price_1TtnIn14iRJDip4yIdxb9MYI",  # $249, revised 2026-07-16 (was $799, INACTIVE — checkout was broken)
    "tech-kit":                "price_1TtnJV14iRJDip4ymW4aLCJk",  # $149 flat, revised 2026-07-16 (was $299; site shows 3 tiers but no tier-selection is built, see TASKS.md 17B)
    "solo-launch":             "price_1TfPfX14iRJDip4yq9rRazM9",
    "ai-coaching":             "price_1TtnI714iRJDip4yrkxZbb8s",  # $49 flat, revised 2026-07-16 (was $75)
    "identity-privacy":        "price_1TfPfZ14iRJDip4ynDJEmVZU",
    "deep-clean":              "price_1TtnKE14iRJDip4yUCZ3q1ED",  # $79, created 2026-07-16 — was advertised on site with no backend mapping at all
    "fresh-start":             "price_1TtnKF14iRJDip4yh3lG4zrx",  # $199, created 2026-07-16 — was advertised on site with no backend mapping at all
    # B2B subscription SKUs
    "foundation":              "price_1TfPfe14iRJDip4yPaewQdoC",
    "assurance":               "price_1TfPfg14iRJDip4yfkbdGANo",
    "directive":               "price_1TfPfh14iRJDip4yHfauRkRh",
    "co-managed-foundation":   "price_1TfPfi14iRJDip4ybtw2slmb",
    "co-managed-assurance":    "price_1TfPfj14iRJDip4yud69dQ2D",
    "co-managed-directive":    "price_1TfPfk14iRJDip4ym3Gn2Hju",
    # B2B one-off SKUs
    "sat":                     "price_1TfPfl14iRJDip4ymDyM8tmV",
    "email-security":          "price_1TfPfm14iRJDip4yeoqzjBul",
    "managed-edr":             "price_1TfPfn14iRJDip4yKn4O6K7U",
    "loki-concierge":          "price_1TfPfp14iRJDip4y0s9Z5uXk",
    "cir-small":               "price_1TfPfq14iRJDip4ytBMXa5K0",
    "cir-medium":              "price_1TfPfr14iRJDip4yNmAmxISt",
    "cir-large":               "price_1TfPfs14iRJDip4yarUWH5QA",
    "it-audit":                "price_1TfPft14iRJDip4y5yEbWY5W",
    "hipaa-gap":               "price_1TfPfu14iRJDip4y1MDaGPTg",
    "m365-migration":          "price_1TfPfv14iRJDip4yYanxHwAK",
    "m365-setup":              "price_1TfPfw14iRJDip4yeaH0HXbu",
    "azure-review":            "price_1TfPfy14iRJDip4yBPSXCEdB",
    "azure-project":           "price_1TfPfz14iRJDip4yWUA1W1O7",
    "intune-rollout":          "price_1TfPg014iRJDip4y8JMuLlWj",
    "windows-server-project":  "price_1TfPg114iRJDip4yDf5OXGsh",
    "backup-dr-setup":         "price_1TfPg214iRJDip4y9ZBPUjs4",
    "powershell-project":      "price_1TfPg314iRJDip4yZ8SHTCtE",
    "remote-block-10hr":       "price_1TfPg414iRJDip4ylHPxT95g",
    "remote-block-25hr":       "price_1TfPg614iRJDip4yQ3OvcUcH",
    "monitoring-setup":        "price_1TfPg714iRJDip4yAVKZICgW",
    "firewall-deploy":         "price_1TfPg814iRJDip4yZJISvzVM",
    "procurement-flat":        "price_1TfPg914iRJDip4yoPovPINS",
    "ai-automation-project":   "price_1TfPgA14iRJDip4yU0tMIGGQ",
    "onboarding-fee":          "price_1TfPgB14iRJDip4yFmkvdY0y",
    "attestation-prep":        "price_1TfPgC14iRJDip4yQhH9EKbk",
    "office-it-relocation":    "price_1TfPgE14iRJDip4yG6W9k0hD",
    "pentest":                 "price_1TfPgF14iRJDip4yCICmIJ6h",
    "iso27001-readiness":      "price_1TfPgG14iRJDip4yhvEq9yYa",
    "vcio-standalone":         "price_1TfPgH14iRJDip4yy1WZxF74",
    "vciso-standalone":        "price_1TfPgI14iRJDip4yeDFIsqyf",
    "ir-retainer":             "price_1TfPgJ14iRJDip4yh8eiyNps",
}

# Test mode price IDs (Stripe test key) — only used for TEST_CALLER_PHONES
SKU_TEST_PRICE_MAP: dict[str, str] = {
    "per-incident": "price_1Tg7Mx14iRJDip4yuyoNsuZf",
    # All other SKUs fall back to test key with the same live price ID during testing
    # (Stripe test mode accepts any price ID created in test mode)
}

# SKUs eligible for the job-loss self-attestation discount.
JOB_LOSS_DISCOUNT_SKUS = {
    "ai-coaching",
    "resume-basic", "resume-premium", "resume-executive",
}

# SKUs that use Stripe subscription mode; all others use payment (one-off).
SUBSCRIPTION_SKUS = {
    "essentials", "family-senior", "home-membership",
    "foundation", "assurance", "directive",
    "co-managed-foundation", "co-managed-assurance", "co-managed-directive",
    "loki-concierge", "vcio-standalone", "vciso-standalone",
}


class PaymentLinkRequest(BaseModel):
    sku: str = Field(default="per-incident")
    call_sid: str = Field(default="")
    caller_email: EmailStr | None = None
    # When provided, this array of single characters is the SOURCE OF TRUTH
    # for the email — the backend joins them and ignores `caller_email`.
    # Defeats LLM token-auto-completion ("astew…" → "asteward" instead of
    # "astewart") by forcing each character to be its own JSON element.
    # Klara is instructed to pass this whenever she's gathered an email
    # via spelling.
    caller_email_letters: list[str] | None = None
    caller_phone: str | None = None
    delivery: str = Field(default="sms", pattern="^(sms|email)$")
    test: bool = Field(default=False, alias="_test")
    # Self-attestation: customer confirmed they are recently job-seeking/laid off.
    # Triggers a 50% discount on eligible SKUs (ai-coaching + resume tiers).
    job_loss_attested: bool = Field(default=False)


def _email_from_letters(letters: list[str] | None) -> str | None:
    """Reconstruct an email address from a list of single-character tokens.

    Accepts each item as 1+ characters; joins them in order. Normalizes
    common 'spoken' tokens that the LLM might emit instead of literal
    punctuation: 'period'/'dot' → '.', 'at'/'at sign' → '@'. Strips
    surrounding whitespace from each piece.
    """
    if not letters:
        return None
    PUNCT_MAP = {
        "period": ".", "dot": ".", ".": ".",
        "at": "@", "at sign": "@", "@": "@",
        "underscore": "_", "_": "_",
        "hyphen": "-", "dash": "-", "-": "-",
        "plus": "+", "+": "+",
    }
    out_chars: list[str] = []
    for raw in letters:
        if raw is None:
            continue
        s = str(raw).strip().lower()
        if not s:
            continue
        if s in PUNCT_MAP:
            out_chars.append(PUNCT_MAP[s])
        else:
            # Keep only the characters as given (don't auto-uppercase, don't expand)
            out_chars.append(s)
    joined = "".join(out_chars).strip()
    # Sanity: must contain exactly one '@' and at least one '.' after it.
    if joined.count("@") != 1:
        log.warning("email_letters joined='%s' has no single @, ignoring", joined)
        return None
    local, _, domain = joined.partition("@")
    if "." not in domain:
        log.warning("email_letters joined='%s' has malformed domain, ignoring", joined)
        return None
    return joined


# Homoglyph map: characters that LOOK like Latin letters but are Cyrillic
# (or other scripts) and would silently break email delivery. Vapi's STT
# sometimes emits these when callers spell with NATO phonetics ("T as in Tango"
# → Cyrillic 'т' U+0442 instead of Latin 't' U+0074). Pydantic's EmailStr
# accepts them as syntactically valid (IDN/UTF-8 local part) but Gmail and
# most real providers reject the resulting address.
_HOMOGLYPHS = {
    # Cyrillic lowercase → Latin lowercase
    "а":"a","в":"b","с":"c","ԁ":"d","е":"e","ё":"e","ғ":"f","һ":"h",
    "і":"i","ј":"j","к":"k","ӏ":"l","м":"m","н":"n","о":"o","ο":"o",
    "р":"p","ԛ":"q","ѕ":"s","т":"t","ц":"u","х":"x","у":"y","ѵ":"v",
    "ҡ":"k","ԝ":"w","ӡ":"z",
    # Cyrillic uppercase → Latin uppercase
    "А":"A","В":"B","С":"C","Ԁ":"D","Е":"E","Ғ":"F","Н":"H","І":"I",
    "Ј":"J","К":"K","М":"M","Н":"N","О":"O","Р":"P","Ԛ":"Q","Ѕ":"S",
    "Т":"T","Х":"X","У":"Y","Ѵ":"V","Ԝ":"W","Ӡ":"Z",
    # Greek look-alikes → Latin
    "α":"a","ε":"e","ι":"i","ν":"v","ο":"o","ρ":"p","τ":"t","υ":"u","χ":"x",
    "Α":"A","Β":"B","Ε":"E","Ζ":"Z","Η":"H","Ι":"I","Κ":"K","Μ":"M","Ν":"N",
    "Ο":"O","Ρ":"P","Τ":"T","Χ":"X",
    # Mathematical / fullwidth (rare but cheap to handle)
    "𝐚":"a","𝐛":"b","𝐜":"c","𝐝":"d","𝐞":"e",
}


def _sanitize_email(raw: str | None) -> str | None:
    """Map look-alike Cyrillic/Greek/etc. characters to their ASCII Latin
    equivalents so the address actually resolves to a real mailbox.

    Returns the cleaned email, or None if input was None/empty.
    Logs the change if any character was substituted.
    """
    if not raw:
        return raw
    out_chars = [_HOMOGLYPHS.get(c, c) for c in raw]
    cleaned = "".join(out_chars)
    if cleaned != raw:
        log.warning(
            "caller_email normalized homoglyphs: %r → %r (non-ASCII chars in input)",
            raw, cleaned,
        )
    # Any remaining non-ASCII after mapping = still likely broken; log + return as-is.
    # We do NOT reject the call — better to try sending than to silently drop.
    remaining_non_ascii = [c for c in cleaned if ord(c) >= 128]
    if remaining_non_ascii:
        log.warning(
            "caller_email still has non-ASCII chars after sanitize: %r (chars: %s)",
            cleaned, [hex(ord(c)) for c in remaining_non_ascii],
        )
    return cleaned


@router.post("/payment_link")
async def create_payment_link(req: PaymentLinkRequest) -> dict[str, Any]:
    if req.test:
        return {"status": "ok", "test": True, "url": "https://buy.stripe.com/test"}

    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="stripe not configured")

    # PRECEDENCE: if Klara passed caller_email_letters (array of single chars),
    # reconstruct the email from that and IGNORE caller_email entirely. The
    # array form defeats LLM token-auto-completion on email strings.
    reconstructed = _email_from_letters(req.caller_email_letters)
    if reconstructed:
        log.info(
            "using reconstructed email from letters: %r (ignoring caller_email=%r)",
            reconstructed, str(req.caller_email) if req.caller_email else None,
        )
        req = req.model_copy(update={"caller_email": reconstructed})

    # Sanitize the email of homoglyphs (Cyrillic 'т' → Latin 't', etc.) so the
    # downstream Microsoft Graph send actually reaches the real mailbox.
    if req.caller_email:
        cleaned = _sanitize_email(str(req.caller_email))
        if cleaned and cleaned != str(req.caller_email):
            req = req.model_copy(update={"caller_email": cleaned})

    # Auto-switch to test mode when caller is a known test phone
    is_test_caller = req.caller_phone and req.caller_phone in TEST_CALLER_PHONES
    if is_test_caller and STRIPE_TEST_KEY:
        log.info("test caller detected (%s) — using Stripe test mode", req.caller_phone)
        active_stripe_key = STRIPE_TEST_KEY
        active_price_map = {**SKU_PRICE_MAP, **SKU_TEST_PRICE_MAP}
    else:
        active_stripe_key = stripe.api_key
        active_price_map = SKU_PRICE_MAP

    price_id = active_price_map.get(req.sku)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"unknown sku: {req.sku}")

    # Job-loss discount: apply 50% coupon when customer self-attested job loss
    # and the SKU is eligible (ai-coaching + resume tiers).
    job_loss_discount_params: dict[str, Any] = {}
    apply_job_loss_discount = (
        req.job_loss_attested
        and req.sku in JOB_LOSS_DISCOUNT_SKUS
        and STRIPE_JOB_LOSS_COUPON_ID
    )
    if apply_job_loss_discount:
        # discounts and allow_promotion_codes are mutually exclusive in Stripe.
        job_loss_discount_params = {
            "discounts": [{"coupon": STRIPE_JOB_LOSS_COUPON_ID}],
            "allow_promotion_codes": False,
        }
        log.info(
            "job_loss discount applied: sku=%s coupon=%s call_sid=%s",
            req.sku, STRIPE_JOB_LOSS_COUPON_ID, req.call_sid,
        )
    else:
        job_loss_discount_params = {"allow_promotion_codes": True}

    try:
        session = stripe.checkout.Session.create(
            mode="subscription" if req.sku in SUBSCRIPTION_SKUS else "payment",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=req.caller_email or None,
            success_url="https://klaravex.com/personal/thanks/?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://klaravex.com/personal/pricing/",
            metadata={
                "call_sid": req.call_sid,
                "intent": req.sku,
                "source": "vapi",
                "job_loss_attested": "true" if req.job_loss_attested else "false",
            },
            **job_loss_discount_params,
            api_key=active_stripe_key,
        )
    except stripe.error.InvalidRequestError as exc:
        raise HTTPException(status_code=400, detail=f"stripe invalid request: {exc.user_message}") from exc
    except stripe.error.StripeError as exc:
        raise HTTPException(status_code=502, detail=f"stripe error: {exc.user_message}") from exc
    url = session.url or ""

    # Route to email if delivery=sms but no phone number available
    if req.delivery == "sms" and not req.caller_phone and req.caller_email:
        req = req.model_copy(update={"delivery": "email"})

    sms_ok = False
    # NOTE: this fires for every SKU (per-incident, subscriptions, resume
    # packages, etc.) via both the Vapi phone flow and the web chat agent —
    # the copy must stay channel- and price-agnostic. Do not hardcode a SKU's
    # price or phone-specific language ("stay on the call") here; the Stripe
    # checkout page itself shows the actual price.
    if req.delivery == "sms" and req.caller_phone:
        sms_ok = await _send_sms(req.caller_phone, f"Klaravex payment link: {url}")
        if not sms_ok and req.caller_email:
            log.info("sms failed, falling back to email for call_sid=%s", req.call_sid)
            await send_email(
                to=str(req.caller_email),
                subject="Your Klaravex payment link",
                body=(
                    "Here's your Klaravex payment link:\n\n"
                    f"{url}\n\n"
                    "This link is valid for 24 hours.\n\n"
                    "Questions? Call +1 (424) 348-6010."
                ),
            )
    elif req.delivery == "email" and req.caller_email:
        await send_email(
            to=str(req.caller_email),
            subject="Your Klaravex payment link",
            body=(
                "Here's your Klaravex payment link:\n\n"
                f"{url}\n\n"
                "This link is valid for 24 hours.\n\n"
                "Questions? Call +1 (424) 348-6010."
            ),
        )

    return {"status": "ok", "url": url, "session_id": session.id}


async def _send_sms(to: str, body: str) -> bool:
    """Delegates to the gated lib.sms helper so SMS_ENABLED is honored centrally."""
    from ..lib.sms import send_sms as _gated
    ok, _err = await _gated(to, body, source="vapi_payment_link")
    return ok


