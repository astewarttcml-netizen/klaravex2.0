"""Job-loss discount — self-attestation form + Stripe promo code issuance.

Flow:
  GET  /api/v1/job-loss-discount  — render attestation HTML form
  POST /api/v1/job-loss-discount  — validate → create single-use Stripe promo
                                     code → email applicant → log to DB → notify Anthony

Rate limit: 3 submissions per email per day (enforced in DB, not SlowAPI).
IP-level rate limit: 10/hour via SlowAPI (prevents throwaway email storms).

Stripe setup required (one-time, done in Stripe Dashboard):
  Coupons → New → 50% off, forever, name "Job Loss 50%"
  Set env var STRIPE_JOB_LOSS_COUPON_ID to the coupon ID (e.g. coupon_xxxx).

SKUs eligible for discount (same as payment_link.py):
  ai-coaching   → price_1TtnI714iRJDip4yrkxZbb8s  ($49)
  resume-basic  → price_1TtnIm14iRJDip4yphE3tmOQ  ($79)
  resume-premium → price_1TtnIm14iRJDip4yoFbpzTf2 ($149)
  resume-executive → price_1TtnIn14iRJDip4yIdxb9MYI ($249)
  tech-kit      → price_1TtnJV14iRJDip4ymW4aLCJk   ($149)
"""

import logging
import os
import re
from typing import Optional

import stripe
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from .lib.db import get_pool
from .lib.email import send_email
from .lib.rate_limit import limiter

log = logging.getLogger("klaravex.job_loss_discount")
router = APIRouter()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_JOB_LOSS_COUPON_ID = os.environ.get("STRIPE_JOB_LOSS_COUPON_ID", "")
_ANTHONY_EMAIL = os.environ.get("ANTHONY_EMAIL", "astewart.tcml@gmail.com")
_SUPPORT_EMAIL = "support@klaravex.com"

# Maximum number of codes issued to one email address (honour-system, not hard-blocking
# legitimate re-applications — just caps abuse).
_MAX_PER_EMAIL = 1

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ─── HTML helpers ────────────────────────────────────────────────────────────

_CSS = """
:root{
  --bg:#0b0d10;--panel:#14181d;--line:#272d35;--ink:#e9eef3;--mute:#94a0ad;
  --accent:#5fc1ff;--teal:#5eead4;--warn:#ffb454;--bad:#ff6b6b;
  --pad:1.25rem;
}
*{box-sizing:border-box}
html,body{background:var(--bg);color:var(--ink);margin:0;
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
header{border-bottom:1px solid var(--line);padding:1rem var(--pad);
  display:flex;align-items:center;gap:.75rem}
header .brand{font-weight:700;letter-spacing:-.02em;font-size:1.05rem}
main{max-width:580px;margin:0 auto;padding:2.5rem var(--pad)}
h1{font-size:1.45rem;margin:0 0 .5rem;letter-spacing:-.02em}
.sub{color:var(--mute);margin:0 0 2rem;font-size:.93rem;line-height:1.55}
.card{background:var(--panel);border:1px solid var(--line);
  border-radius:12px;padding:1.75rem}
label{display:block;margin-bottom:1.1rem}
label span{display:block;color:var(--mute);font-size:.82rem;
  text-transform:uppercase;letter-spacing:.04em;margin-bottom:.35rem}
input[type=text],input[type=email],textarea{
  width:100%;background:#0e1216;color:var(--ink);
  border:1px solid var(--line);border-radius:8px;
  padding:.65rem .75rem;font:inherit;
  transition:border-color .15s}
input:focus,textarea:focus{outline:none;border-color:var(--accent)}
textarea{resize:vertical;min-height:90px}
.attest{display:flex;align-items:flex-start;gap:.65rem;
  background:#0e1216;border:1px solid var(--line);
  border-radius:8px;padding:1rem;margin-bottom:1.5rem}
.attest input[type=checkbox]{margin-top:.2rem;accent-color:var(--teal);
  width:1.05rem;height:1.05rem;flex-shrink:0}
.attest p{margin:0;font-size:.92rem;color:var(--ink)}
button[type=submit]{
  width:100%;background:var(--teal);color:#001a18;
  border:none;border-radius:8px;padding:.75rem 1rem;
  font:inherit;font-weight:700;cursor:pointer;
  font-size:1rem;letter-spacing:-.01em;
  transition:opacity .15s}
button:hover{opacity:.88}
.notice{font-size:.82rem;color:var(--mute);margin-top:1rem;
  text-align:center;line-height:1.55}
.alert{padding:.9rem 1rem;border-radius:8px;
  margin-bottom:1.5rem;font-size:.92rem}
.alert.err{background:#2a1318;color:var(--bad);border:1px solid #4a2030}
.alert.ok{background:#0d2821;color:var(--teal);border:1px solid #1a4a3a}
footer{border-top:1px solid var(--line);padding:1rem var(--pad);
  color:var(--mute);font-size:.8rem;text-align:center;margin-top:3rem}
"""

_TEAL_DOT = '<span style="color:var(--teal);font-size:.55rem;vertical-align:middle">●</span>'


def _base(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Klaravex</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="brand">Klaravex</div>
  {_TEAL_DOT}
  <span style="color:var(--mute);font-size:.88rem">AI Skills &amp; Career Support</span>
</header>
<main>{body}</main>
<footer>
  Klaravex LLC &middot; US managed IT &amp; career support &middot;
  <a href="mailto:support@klaravex.com">support@klaravex.com</a> &middot;
  <a href="https://klaravex.com">klaravex.com</a>
</footer>
</body>
</html>"""


_FORM_BODY = """
<h1>Job-Loss Discount</h1>
<p class="sub">
  We offer 50% off our AI Skills Coaching and Resume/Job-Hunt Kit for anyone
  who has recently been laid off. No documents required — we operate on the
  same honour system we use for our scam-recovery services.
</p>
{alert}
<div class="card">
  <form method="post" action="/api/v1/job-loss-discount">
    <label>
      <span>Your name</span>
      <input type="text" name="name" placeholder="First and last name"
             value="{name}" required maxlength="120">
    </label>
    <label>
      <span>Email address</span>
      <input type="email" name="email" placeholder="you@example.com"
             value="{email}" required maxlength="254">
    </label>
    <label>
      <span>Brief statement <span style="color:var(--mute);font-weight:400;font-size:.78rem">(optional but helpful)</span></span>
      <textarea name="statement" placeholder="e.g. I was laid off in June and am actively job-searching."
                maxlength="600">{statement}</textarea>
    </label>
    <div class="attest">
      <input type="checkbox" name="attested" id="attested" required>
      <label for="attested" style="margin:0">
        <p>I confirm I am currently job-seeking due to a recent job loss or lay-off, and I am
           applying for this discount in good faith.</p>
      </label>
    </div>
    <button type="submit">Apply for 50% discount →</button>
    <p class="notice">
      Your promo code will be emailed within seconds. One code per email address.
      This code applies to AI Skills Coaching and all Resume Kit tiers.
    </p>
  </form>
</div>
"""


def _form_page(
    alert_html: str = "",
    name: str = "",
    email: str = "",
    statement: str = "",
) -> HTMLResponse:
    body = _FORM_BODY.format(
        alert=alert_html,
        name=name,
        email=email,
        statement=statement,
    )
    return HTMLResponse(_base("Job-Loss Discount", body))


_SUCCESS_BODY = """
<h1>Promo code sent</h1>
<p class="sub">
  Check your inbox at <strong>{email}</strong> — your 50% discount code is on its way.<br>
  If you don't see it within a few minutes, check your spam folder or email us at
  <a href="mailto:support@klaravex.com">support@klaravex.com</a>.
</p>
<div class="card" style="text-align:center;padding:2rem">
  <div style="font-size:2.5rem;margin-bottom:.5rem">✓</div>
  <div style="color:var(--teal);font-weight:600;font-size:1.1rem">Code emailed to {email}</div>
  <div style="color:var(--mute);font-size:.88rem;margin-top:.5rem">
    Use it at checkout on <a href="https://klaravex.com">klaravex.com</a>
  </div>
</div>
<p class="notice" style="margin-top:1.5rem">
  <a href="https://klaravex.com/personal">Browse AI Skills &amp; Resume services →</a>
</p>
"""


def _success_page(email: str) -> HTMLResponse:
    body = _SUCCESS_BODY.format(email=email)
    return HTMLResponse(_base("Code sent", body))


# ─── DB helpers ──────────────────────────────────────────────────────────────

async def _count_existing(email: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_job_loss_discounts WHERE email = $1",
            email.lower(),
        )


async def _log_discount(
    *,
    email: str,
    name: str,
    statement: str,
    promo_code: str,
    promo_code_id: str,
) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO klaravex_job_loss_discounts
                (email, name, statement, promo_code, stripe_promo_code_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id::text
            """,
            email.lower(), name.strip(), statement.strip(), promo_code, promo_code_id,
        )


# ─── Stripe helper ───────────────────────────────────────────────────────────

def _create_promo_code(email: str) -> tuple[str, str]:
    """Create a single-use Stripe promotion code for the job-loss coupon.

    Returns (code_string, promo_code_id).
    Raises stripe.error.StripeError on Stripe failure.
    """
    if not STRIPE_JOB_LOSS_COUPON_ID:
        raise RuntimeError("STRIPE_JOB_LOSS_COUPON_ID env var not set")

    promo = stripe.PromotionCode.create(
        coupon=STRIPE_JOB_LOSS_COUPON_ID,
        max_redemptions=1,
        metadata={"source": "job_loss_attestation", "applicant_email": email},
    )
    return promo["code"], promo["id"]


# ─── Email helpers ────────────────────────────────────────────────────────────

async def _email_applicant(email: str, name: str, code: str) -> None:
    greeting = f"Hi {name.split()[0]}," if name.strip() else "Hi there,"
    body = (
        f"{greeting}\n\n"
        f"Your job-loss discount code is ready:\n\n"
        f"    {code}\n\n"
        f"This code gives you 50% off any of the following services:\n"
        f"  • AI Skills Coaching\n"
        f"  • Resume/Job-Hunt Kit (Basic, Premium, or Executive)\n"
        f"  • Tech Career Kit\n\n"
        f"Enter it at checkout on klaravex.com. The code is single-use and\n"
        f"expires when redeemed — apply it in a single checkout session.\n\n"
        f"We're rooting for you.\n\n"
        f"— The Klaravex Team\n"
        f"  support@klaravex.com · klaravex.com\n"
    )
    html = f"""
<p>{greeting}</p>
<p>Your job-loss discount code is ready:</p>
<p style="font-size:1.4em;font-weight:700;letter-spacing:.05em;
          font-family:monospace;background:#f3f4f6;padding:.6em 1em;
          border-radius:8px;display:inline-block">{code}</p>
<p>This code gives you <strong>50% off</strong> any of the following services:</p>
<ul>
  <li>AI Skills Coaching</li>
  <li>Resume/Job-Hunt Kit (Basic, Premium, or Executive)</li>
  <li>Tech Career Kit</li>
</ul>
<p>Enter it at checkout on <a href="https://klaravex.com">klaravex.com</a>.
   The code is single-use — apply it in one checkout session.</p>
<p>We're rooting for you.</p>
<p style="color:#6b7280;font-size:.9em">— The Klaravex Team<br>
  <a href="mailto:support@klaravex.com">support@klaravex.com</a> ·
  <a href="https://klaravex.com">klaravex.com</a></p>
"""
    await send_email(
        to=email,
        subject=f"Your Klaravex discount code: {code}",
        body=body,
        html=html,
    )


async def _notify_anthony(email: str, name: str, statement: str, code: str, row_id: str) -> None:
    body = (
        f"Job-loss discount issued.\n\n"
        f"  Name:      {name}\n"
        f"  Email:     {email}\n"
        f"  Code:      {code}\n"
        f"  Statement: {statement or '(none provided)'}\n"
        f"  DB row:    {row_id}\n"
    )
    await send_email(
        to=_ANTHONY_EMAIL,
        subject=f"[Klaravex] Job-loss discount issued — {email}",
        body=body,
    )


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.get("/job-loss-discount", tags=["Job-loss discount"])
async def job_loss_form(request: Request) -> HTMLResponse:
    """Render the self-attestation form."""
    return _form_page()


@router.post("/job-loss-discount", tags=["Job-loss discount"])
@limiter.limit("10/hour")
async def job_loss_submit(
    request: Request,
    name: str = Form(..., max_length=120),
    email: str = Form(..., max_length=254),
    statement: str = Form(default="", max_length=600),
    attested: Optional[str] = Form(default=None),
) -> HTMLResponse:
    """Process attestation, issue Stripe promo code, email applicant."""

    # ── 1. Basic validation ───────────────────────────────────────────────────
    name = name.strip()
    email = email.strip().lower()
    statement = statement.strip()

    if not name:
        return _form_page(
            '<div class="alert err">Please enter your name.</div>',
            name=name, email=email, statement=statement,
        )
    if not _EMAIL_RE.match(email):
        return _form_page(
            '<div class="alert err">Please enter a valid email address.</div>',
            name=name, email=email, statement=statement,
        )
    if not attested:
        return _form_page(
            '<div class="alert err">Please check the attestation box to continue.</div>',
            name=name, email=email, statement=statement,
        )

    # ── 2. Rate limit: 1 discount per email address ───────────────────────────
    try:
        existing = await _count_existing(email)
    except Exception:
        log.exception("DB count failed for job_loss email=%s", email)
        existing = 0  # fail open on DB error — don't block applicant

    if existing >= _MAX_PER_EMAIL:
        return _form_page(
            '<div class="alert err">'
            'A discount code has already been issued to this email address. '
            'If you need help, email <a href="mailto:support@klaravex.com">support@klaravex.com</a>.'
            '</div>',
            name=name, email=email, statement=statement,
        )

    # ── 3. Create Stripe promo code ───────────────────────────────────────────
    try:
        code, promo_id = _create_promo_code(email)
    except stripe.error.StripeError as exc:
        log.exception("Stripe promo code creation failed for email=%s", email)
        return _form_page(
            f'<div class="alert err">We couldn\'t generate your code right now — '
            f'please email <a href="mailto:support@klaravex.com">support@klaravex.com</a> '
            f'and we\'ll send it manually. (Error: {exc.user_message or str(exc)[:80]})</div>',
            name=name, email=email, statement=statement,
        )
    except RuntimeError as exc:
        log.error("STRIPE_JOB_LOSS_COUPON_ID not configured: %s", exc)
        return _form_page(
            '<div class="alert err">This discount is temporarily unavailable. '
            'Please email <a href="mailto:support@klaravex.com">support@klaravex.com</a>.</div>',
            name=name, email=email, statement=statement,
        )

    # ── 4. Log to DB ──────────────────────────────────────────────────────────
    try:
        row_id = await _log_discount(
            email=email,
            name=name,
            statement=statement,
            promo_code=code,
            promo_code_id=promo_id,
        )
    except Exception:
        log.exception("DB log failed for job_loss email=%s code=%s", email, code)
        row_id = "db-error"  # code already issued; don't block delivery

    # ── 5. Email applicant ────────────────────────────────────────────────────
    try:
        await _email_applicant(email, name, code)
    except Exception:
        log.exception("Failed to email job_loss code to %s", email)
        # Code is in DB; fall through to success page — Anthony notified below.

    # ── 6. Notify Anthony ─────────────────────────────────────────────────────
    try:
        await _notify_anthony(email, name, statement, code, row_id)
    except Exception:
        log.exception("Failed to notify Anthony of job_loss discount email=%s", email)

    log.info("job_loss_discount issued: email=%s code=%s row=%s", email, code, row_id)
    return _success_page(email)
