"""
Klaravex client portal — magic-link auth + dashboard pages.

Mounts at /portal (configurable via PORTAL_PREFIX) and serves:
  GET  /portal/                  -> dashboard (requires session) or login redirect
  GET  /portal/login             -> email-entry form
  POST /portal/login/request     -> send magic link to email
  GET  /portal/login/verify      -> consume token, set session cookie, redirect
  GET  /portal/logout            -> clear session
  GET  /portal/tickets           -> list of tickets
  GET  /portal/stats             -> aggregate counters
  GET  /portal/docs              -> KB index
  GET  /portal/ledger            -> block-hours ledger (A7)
  GET  /portal/subscription      -> subscription status from Stripe

Auth model:
- Issue a 32-byte random token, email a link containing it.
- Token is single-use, 15min TTL, stored as sha256 hash in klaravex_portal_tokens.
- After verify, mint a long-lived (30d) session token; same table, purpose='session'.

Templates: simple Jinja-rendered HTML in ../templates/. No JS framework — HTMX
loaded from CDN for live interactions. All pages share base.html.

Mount with:
    from infra.klara.handlers.portal import router as portal_router
    app.include_router(portal_router, prefix="/portal")
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..lib.db import get_pool
from ..lib import tickets as tickets_lib
from ..lib import kb as kb_lib
from ..lib import escalation as escalation_lib
from ..lib import oauth as oauth_lib
from ..lib.email import send_email

log = logging.getLogger("klaravex.portal")
router = APIRouter()

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
PORTAL_PATH_PREFIX = "/portal"
PORTAL_LOGIN_TTL_MIN = int(os.environ.get("PORTAL_LOGIN_TTL_MIN", "15"))
PORTAL_SESSION_TTL_DAYS = int(os.environ.get("PORTAL_SESSION_TTL_DAYS", "30"))
SESSION_COOKIE = "klaravex_portal"

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ──────────────────────────────────────────────────────────────────────────────
# Token helpers
# ──────────────────────────────────────────────────────────────────────────────

def _hash_token(plaintext: str) -> bytes:
    return hashlib.sha256(plaintext.encode("utf-8")).digest()


async def _issue_token(email: str, *, purpose: str, ttl: timedelta, request: Optional[Request] = None) -> str:
    plaintext = secrets.token_urlsafe(32)
    token_hash = _hash_token(plaintext)
    expires_at = datetime.now(timezone.utc) + ttl
    ip = request.client.host if (request and request.client) else None
    user_agent = request.headers.get("user-agent") if request else None

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO klaravex_portal_tokens
                (token_hash, email, purpose, expires_at, ip, user_agent)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            token_hash, email.lower(), purpose, expires_at, ip, user_agent,
        )
    return plaintext


async def _consume_login_token(plaintext: str) -> Optional[str]:
    """If valid: mark used, return email. Else None."""
    token_hash = _hash_token(plaintext)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT email, expires_at, used_at
              FROM klaravex_portal_tokens
             WHERE token_hash = $1 AND purpose = 'login'
            """,
            token_hash,
        )
        if not row:
            return None
        if row["used_at"] is not None:
            return None
        if row["expires_at"] < datetime.now(timezone.utc):
            return None
        await conn.execute(
            "UPDATE klaravex_portal_tokens SET used_at = now() WHERE token_hash = $1",
            token_hash,
        )
        return row["email"]


async def _validate_session(plaintext: str) -> Optional[str]:
    if not plaintext:
        return None
    token_hash = _hash_token(plaintext)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT email
              FROM klaravex_portal_tokens
             WHERE token_hash = $1
               AND purpose = 'session'
               AND expires_at > now()
            """,
            token_hash,
        )
        return row["email"] if row else None


# ──────────────────────────────────────────────────────────────────────────────
# Auth dependency
# ──────────────────────────────────────────────────────────────────────────────

async def current_user(klaravex_portal: Optional[str] = Cookie(default=None)) -> str:
    email = await _validate_session(klaravex_portal or "")
    if not email:
        raise HTTPException(status_code=401, detail="not authenticated")
    return email


async def _send_magic_link(email: str, link: str) -> None:
    body = (
        f"Hi,\n\n"
        f"Sign in to your Klaravex portal:\n\n  {link}\n\n"
        f"This link expires in {PORTAL_LOGIN_TTL_MIN} minutes and can be used once.\n\n"
        f"If you didn't request this, you can ignore this email.\n\n"
        f"— Klaravex\nhello@klaravex.com"
    )
    await send_email(
        to=email,
        subject="Your Klaravex portal sign-in link",
        body=body,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Routes — auth
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    providers = {
        "google": oauth_lib.is_configured("google"),
        "microsoft": oauth_lib.is_configured("microsoft"),
    }
    return templates.TemplateResponse(
        request, "login.html",
        {"error": error, "providers": providers},
    )


# ──────────────────────────────────────────────────────────────────────────────
# OAuth login (T14.1) — Google + Microsoft via authorization code + PKCE
# ──────────────────────────────────────────────────────────────────────────────

def _oauth_redirect_uri(provider: str) -> str:
    return f"{PORTAL_BASE_URL.rstrip('/')}{PORTAL_PATH_PREFIX}/login/oauth/{provider}/callback"


@router.get("/login/oauth/{provider}/start")
async def oauth_start(provider: str, request: Request):
    if provider not in oauth_lib.PROVIDERS:
        raise HTTPException(status_code=404, detail="unknown provider")
    try:
        flow = await oauth_lib.start_login(provider, _oauth_redirect_uri(provider))
    except oauth_lib.OAuthNotConfigured:
        return RedirectResponse(
            url=f"{PORTAL_PATH_PREFIX}/login?error=provider_not_configured",
            status_code=303,
        )
    except oauth_lib.OAuthError as exc:
        log.warning("oauth start failed [%s]: %s", provider, exc)
        return RedirectResponse(
            url=f"{PORTAL_PATH_PREFIX}/login?error=provider_unavailable",
            status_code=303,
        )
    await oauth_lib.save_oauth_state(
        state=flow.state,
        provider=provider,
        code_verifier=flow.code_verifier,
        nonce=flow.nonce,
    )
    return RedirectResponse(url=flow.authorize_url, status_code=303)


@router.get("/login/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    if provider not in oauth_lib.PROVIDERS:
        raise HTTPException(status_code=404, detail="unknown provider")
    if error:
        log.info("oauth user-cancelled or provider error [%s]: %s", provider, error)
        return RedirectResponse(
            url=f"{PORTAL_PATH_PREFIX}/login?error=oauth_cancelled",
            status_code=303,
        )
    if not code or not state:
        return RedirectResponse(
            url=f"{PORTAL_PATH_PREFIX}/login?error=oauth_missing_params",
            status_code=303,
        )

    saved = await oauth_lib.consume_oauth_state(state)
    if not saved or saved["provider"] != provider:
        return RedirectResponse(
            url=f"{PORTAL_PATH_PREFIX}/login?error=oauth_state_invalid",
            status_code=303,
        )

    try:
        identity = await oauth_lib.exchange_code(
            provider,
            code=code,
            code_verifier=saved["code_verifier"],
            redirect_uri=_oauth_redirect_uri(provider),
            expected_nonce=saved["nonce"],
        )
    except oauth_lib.OAuthNotConfigured:
        return RedirectResponse(
            url=f"{PORTAL_PATH_PREFIX}/login?error=provider_not_configured",
            status_code=303,
        )
    except oauth_lib.OAuthError as exc:
        log.warning("oauth exchange failed [%s]: %s", provider, exc)
        return RedirectResponse(
            url=f"{PORTAL_PATH_PREFIX}/login?error=oauth_exchange_failed",
            status_code=303,
        )

    if not identity.email_verified:
        return RedirectResponse(
            url=f"{PORTAL_PATH_PREFIX}/login?error=oauth_email_unverified",
            status_code=303,
        )

    email = await oauth_lib.upsert_linked_account(identity)
    session_plain = await _issue_token(
        email, purpose="session", ttl=timedelta(days=PORTAL_SESSION_TTL_DAYS), request=request,
    )
    response = RedirectResponse(
        url=f"{PORTAL_BASE_URL.rstrip('/')}{PORTAL_PATH_PREFIX}/",
        status_code=303,
    )
    response.set_cookie(
        SESSION_COOKIE,
        session_plain,
        max_age=PORTAL_SESSION_TTL_DAYS * 86400,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.post("/login/request", response_class=HTMLResponse)
async def login_request(request: Request, email: str = Form(...)):
    email_norm = (email or "").strip().lower()
    if "@" not in email_norm:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Please enter a valid email."}
        )
    # Always show the same success page — don't leak which emails exist.
    plaintext = await _issue_token(
        email_norm, purpose="login", ttl=timedelta(minutes=PORTAL_LOGIN_TTL_MIN), request=request
    )
    link = f"{PORTAL_BASE_URL.rstrip('/')}{PORTAL_PATH_PREFIX}/login/verify?token={plaintext}"
    try:
        await _send_magic_link(email_norm, link)
    except Exception as exc:
        log.exception("magic link delivery failed: %s", exc)
    return templates.TemplateResponse(request, "login_sent.html", {"email": email_norm})


@router.get("/login/verify", response_class=HTMLResponse)
async def login_verify_preview(request: Request, token: str):
    """Render a confirm page WITHOUT consuming the token.

    Email link scanners (M365 Safe Links, Outlook ATP, Gmail safety-check) pre-fetch
    every link via GET to scan for malicious content. If we consumed the token here,
    the user would get an "expired link" error on their actual click. Instead, GET
    renders a one-click confirm form; POST actually signs in. The form auto-submits
    via JS for a seamless experience on real browsers (scanners don't run JS).
    """
    return templates.TemplateResponse(
        request,
        "login_confirm.html",
        {"token": token},
    )


@router.post("/login/verify", response_class=HTMLResponse)
async def login_verify_consume(request: Request, token: str = Form(...)):
    """Actually consume the token and create a session."""
    email = await _consume_login_token(token)
    if not email:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "That link has expired or already been used. Request a new one."},
            status_code=400,
        )
    session_plain = await _issue_token(
        email, purpose="session", ttl=timedelta(days=PORTAL_SESSION_TTL_DAYS), request=request
    )
    response = RedirectResponse(url=f"{PORTAL_BASE_URL.rstrip('/')}{PORTAL_PATH_PREFIX}/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_plain,
        max_age=PORTAL_SESSION_TTL_DAYS * 86400,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url=f"{PORTAL_BASE_URL.rstrip('/')}{PORTAL_PATH_PREFIX}/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ──────────────────────────────────────────────────────────────────────────────
# Routes — dashboard
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, email: str = Depends(current_user)):
    stats = await tickets_lib.stats_for_email(email)
    recent = await tickets_lib.list_tickets_for_email(email, limit=5)
    pool = await get_pool()
    async with pool.acquire() as conn:
        recent_nps = await conn.fetchval(
            "SELECT 1 FROM klaravex_portal_nps WHERE client_email=$1 "
            "AND created_at > now() - interval '90 days' LIMIT 1",
            email.lower(),
        )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"email": email, "stats": stats, "recent": recent, "show_nps": not recent_nps},
    )


@router.post("/nps", response_class=HTMLResponse)
async def submit_nps(
    request: Request,
    score: int = Form(..., ge=0, le=10),
    comment: str = Form(""),
    email: str = Depends(current_user),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO klaravex_portal_nps (client_email, score, comment) VALUES ($1, $2, $3)",
            email.lower(), score, comment.strip()[:1000] or None,
        )
    return RedirectResponse(url="/portal/", status_code=303)


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_page(request: Request, email: str = Depends(current_user)):
    items = await tickets_lib.list_tickets_for_email(email, limit=200)
    return templates.TemplateResponse(
        request, "tickets.html", {"email": email, "tickets": items}
    )


@router.get("/tickets/new", response_class=HTMLResponse)
async def submit_ticket_page(request: Request, email: str = Depends(current_user)):
    return templates.TemplateResponse(request, "submit_ticket.html", {"email": email})


@router.post("/tickets/submit", response_class=HTMLResponse)
async def submit_ticket(
    request: Request,
    subject: str = Form(...),
    summary: str = Form(...),
    email: str = Depends(current_user),
):
    subject = subject.strip()
    summary = summary.strip()
    if not subject or not summary:
        return templates.TemplateResponse(
            request, "submit_ticket.html",
            {"email": email, "error": "Subject and description are required."},
            status_code=400,
        )
    await tickets_lib.create_ticket(
        client_email=email,
        subject=subject[:200],
        severity="standard",
        status="open",
        source="portal",
        summary=summary[:4000],
    )
    return RedirectResponse(url="/portal/tickets", status_code=303)


# NOTE: this wildcard route must stay registered AFTER /tickets/new and
# /tickets/submit -- otherwise it would shadow them (ticket_id="new" etc.)
# since Starlette matches path routes in registration order.
@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
async def ticket_detail_page(
    request: Request, ticket_id: str, email: str = Depends(current_user),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        ticket = await conn.fetchrow(
            "SELECT id, subject, summary, severity, status, created_at "
            "FROM klaravex_tickets WHERE id=$1 AND client_email=$2",
            ticket_id, email.lower(),
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="Ticket not found")
        messages = await conn.fetch(
            "SELECT sender_role, body, created_at FROM klaravex_portal_messages "
            "WHERE ticket_id=$1 ORDER BY created_at ASC",
            ticket_id,
        )
    return templates.TemplateResponse(
        request, "ticket_detail.html",
        {"email": email, "ticket": dict(ticket), "messages": [dict(m) for m in messages]},
    )


@router.post("/tickets/{ticket_id}/messages", response_class=HTMLResponse)
async def post_ticket_message(
    request: Request, ticket_id: str, body: str = Form(...), email: str = Depends(current_user),
):
    body = body.strip()
    pool = await get_pool()
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "SELECT client_email FROM klaravex_tickets WHERE id=$1", ticket_id,
        )
        if owner is None or owner.lower() != email.lower():
            raise HTTPException(status_code=404, detail="Ticket not found")
        if body:
            await conn.execute(
                "INSERT INTO klaravex_portal_messages (ticket_id, client_email, sender_role, body) "
                "VALUES ($1, $2, 'client', $3)",
                ticket_id, email.lower(), body[:10000],
            )
    return RedirectResponse(url=f"/portal/tickets/{ticket_id}", status_code=303)


_COMMON_TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Anchorage", "Pacific/Honolulu", "Europe/London", "Europe/Berlin",
    "Europe/Paris", "UTC",
]


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, email: str = Depends(current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        client = await conn.fetchrow(
            "SELECT name, phone, timezone FROM klaravex_clients WHERE email=$1", email.lower(),
        )
    return templates.TemplateResponse(
        request, "profile.html",
        {"email": email, "client": dict(client) if client else {}, "timezones": _COMMON_TIMEZONES},
    )


@router.post("/profile", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    name: str = Form(""),
    phone: str = Form(""),
    tz: str = Form("America/New_York"),
    email: str = Depends(current_user),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE klaravex_clients
               SET name = $2, phone = $3, timezone = $4, updated_at = now()
             WHERE email = $1
            """,
            email.lower(), name.strip()[:200] or None, phone.strip()[:40] or None, tz,
        )
        client = await conn.fetchrow(
            "SELECT name, phone, timezone FROM klaravex_clients WHERE email=$1", email.lower(),
        )
    return templates.TemplateResponse(
        request, "profile.html",
        {"email": email, "client": dict(client) if client else {}, "timezones": _COMMON_TIMEZONES, "saved": True},
    )


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request, email: str = Depends(current_user)):
    stats = await tickets_lib.stats_for_email(email)
    return templates.TemplateResponse(request, "stats.html", {"email": email, "stats": stats})


@router.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request, email: str = Depends(current_user)):
    # Minimal KB index built from chunk source_urls.
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT source_url, source_title, MAX(ingested_at) AS ingested_at "
            "FROM klaravex_kb_chunks GROUP BY source_url, source_title ORDER BY source_title"
        )
    docs = [dict(r) for r in rows]
    return templates.TemplateResponse(request, "docs.html", {"email": email, "docs": docs})


@router.get("/ledger", response_class=HTMLResponse)
async def ledger_page(request: Request, email: str = Depends(current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT delta_hours, reason, sku, created_at
              FROM klaravex_hours_ledger
             WHERE client_email = $1
             ORDER BY created_at DESC
             LIMIT 200
            """,
            email.lower(),
        )
        balance = await conn.fetchval(
            "SELECT COALESCE(SUM(delta_hours), 0) FROM klaravex_hours_ledger WHERE client_email = $1",
            email.lower(),
        )
    entries = [dict(r) for r in rows]
    return templates.TemplateResponse(
        request, "ledger.html", {"email": email, "entries": entries, "balance": float(balance or 0)}
    )


def _fmt_interval(interval: str, count: int) -> str:
    base = {"day": "day", "week": "week", "month": "month", "year": "year"}.get(interval, interval)
    return f"{base}" if count == 1 else f"{count} {base}s"


@router.get("/subscription", response_class=HTMLResponse)
async def subscription_page(request: Request, email: str = Depends(current_user)):
    import stripe
    from datetime import datetime as _dt, timezone as _tz

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT stripe_customer_id, name, segment, company, metadata "
            "FROM klaravex_clients WHERE email = $1",
            email.lower(),
        )
    client = dict(row) if row else {}
    stripe_customer_id = client.get("stripe_customer_id")

    subscriptions: list[dict] = []
    total_monthly_usd = 0.0
    billing_portal_url: str | None = None
    fetch_error: str | None = None

    if stripe_customer_id and stripe.api_key:
        try:
            resp = stripe.Subscription.list(
                customer=stripe_customer_id,
                status="all",
                limit=20,
                expand=["data.items.data.price.product"],
            )
            for sub in resp.get("data", []):
                items = sub.get("items", {}).get("data", [])
                for item in items:
                    price = item.get("price") or {}
                    product = price.get("product") or {}
                    if isinstance(product, dict):
                        plan_name = product.get("name") or "Subscription"
                    else:
                        plan_name = str(product)
                    recur = price.get("recurring") or {}
                    interval = recur.get("interval", "month")
                    interval_count = int(recur.get("interval_count", 1))
                    amount_cents = int(price.get("unit_amount") or 0)
                    amount = amount_cents / 100.0
                    currency = (price.get("currency") or "usd").upper()
                    if interval == "month" and currency == "USD":
                        total_monthly_usd += amount / interval_count
                    elif interval == "year" and currency == "USD":
                        total_monthly_usd += amount / (12 * interval_count)
                    cpe = sub.get("current_period_end")
                    next_renewal = _dt.fromtimestamp(cpe, tz=_tz.utc).strftime("%Y-%m-%d") if cpe else "—"
                    subscriptions.append({
                        "id": sub.get("id"),
                        "plan": plan_name,
                        "amount_display": f"${amount:,.2f} {currency}" if currency == "USD" else f"{amount:,.2f} {currency}",
                        "interval_display": _fmt_interval(interval, interval_count),
                        "status": sub.get("status", "—"),
                        "next_renewal": next_renewal,
                        "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
                        "trial_end": (_dt.fromtimestamp(sub["trial_end"], tz=_tz.utc).strftime("%Y-%m-%d")
                                      if sub.get("trial_end") else None),
                    })
        except Exception as exc:
            log.warning("subscription fetch failed for %s: %s", stripe_customer_id, exc)
            fetch_error = "Couldn't fetch live subscription data right now. Please refresh."

        # Build Stripe-hosted billing portal session for self-service management
        try:
            portal_session = stripe.billing_portal.Session.create(
                customer=stripe_customer_id,
                return_url=f"{PORTAL_BASE_URL.rstrip('/')}{PORTAL_PATH_PREFIX}/subscription",
            )
            billing_portal_url = portal_session.get("url")
        except Exception as exc:
            log.warning("billing portal session create failed: %s", exc)

    return templates.TemplateResponse(
        request,
        "subscription.html",
        {
            "email": email,
            "client": client,
            "subscriptions": subscriptions,
            "total_monthly_usd": total_monthly_usd,
            "billing_portal_url": billing_portal_url,
            "fetch_error": fetch_error,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Routes — Marketing AI competition (Anthony-only)
# ──────────────────────────────────────────────────────────────────────────────

_ADMIN_EMAILS = {"astewart@klaravex.com", "anthony@klaravex.com", "astewart.tcml@gmail.com"}


@router.get("/admin/approvals", response_class=HTMLResponse)
async def admin_approvals(request: Request, email: str = Depends(current_user)):
    """One-stop view of everything waiting on operator approval."""
    if email.lower() not in {e.lower() for e in _ADMIN_EMAILS}:
        raise HTTPException(status_code=403, detail="admin only")

    pool = await get_pool()
    async with pool.acquire() as conn:
        social_drafts = await conn.fetch("""
            SELECT id::text, platform, status, content, approval_token, created_at
              FROM klaravex_social_drafts WHERE status='pending'
              ORDER BY created_at DESC LIMIT 30
        """)
        marketing_actions = await conn.fetch("""
            SELECT a.id::text, a.action_type, a.action_target, a.payload, a.created_at, t.team_code
              FROM klaravex_marketing_actions a
              JOIN klaravex_marketing_teams t ON t.id = a.team_id
             WHERE a.status='pending' AND a.approval_required
             ORDER BY a.created_at ASC LIMIT 30
        """)
        platform_bids = await conn.fetch("""
            SELECT b.id::text, b.platform, b.bid_amount, b.bid_currency, b.cover_letter,
                   b.created_at, p.title, p.url, p.fit_score
              FROM klaravex_platform_bids b
              JOIN klaravex_freelance_projects p ON p.id = b.project_id
             WHERE b.status='queued'
             ORDER BY p.fit_score DESC NULLS LAST, b.created_at ASC LIMIT 30
        """)
        milestone_signoffs = await conn.fetch("""
            SELECT m.id::text, m.title, m.budget_percentage, m.estimated_due_at,
                   p.title AS project_title, p.client_email, p.total_budget_usd, m.signoff_token
              FROM klaravex_project_milestones m
              JOIN klaravex_projects p ON p.id = m.project_id
             WHERE m.status='in_progress'
             ORDER BY m.estimated_due_at ASC NULLS LAST LIMIT 20
        """)
        export_requests = await conn.fetch("""
            SELECT id::text, email, status, byte_count, created_at
              FROM klaravex_data_export_requests
             WHERE status='building'
             ORDER BY created_at ASC LIMIT 10
        """)

    total_pending = (len(social_drafts) + len(marketing_actions) +
                     len(platform_bids) + len(milestone_signoffs) +
                     len(export_requests))

    return templates.TemplateResponse(
        request, "admin_approvals.html",
        {
            "email": email,
            "total_pending": total_pending,
            "social_drafts": [dict(r) for r in social_drafts],
            "marketing_actions": [dict(r) for r in marketing_actions],
            "platform_bids": [dict(r) for r in platform_bids],
            "milestone_signoffs": [dict(r) for r in milestone_signoffs],
            "export_requests": [dict(r) for r in export_requests],
        },
    )


@router.post("/admin/approvals/marketing-action/{action_id}", response_class=HTMLResponse)
async def admin_approve_marketing_action(
    request: Request, action_id: str,
    decision: str = Form(...),
    email: str = Depends(current_user),
):
    if email.lower() not in {e.lower() for e in _ADMIN_EMAILS}:
        raise HTTPException(status_code=403, detail="admin only")
    pool = await get_pool()
    new_status = "approved" if decision == "approve" else "blocked"
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE klaravex_marketing_actions
               SET status=$1, approved_by=$2, approved_at=now()
             WHERE id=$3
            """,
            new_status, email, action_id,
        )
    return RedirectResponse(url="/portal/admin/approvals", status_code=303)


@router.post("/admin/approvals/freelance-bid/{bid_id}", response_class=HTMLResponse)
async def admin_approve_freelance_bid(
    request: Request, bid_id: str,
    decision: str = Form(...),
    email: str = Depends(current_user),
):
    if email.lower() not in {e.lower() for e in _ADMIN_EMAILS}:
        raise HTTPException(status_code=403, detail="admin only")
    pool = await get_pool()
    if decision == "reject":
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE klaravex_platform_bids SET status='submit_failed', error_detail='operator_rejected' WHERE id=$1",
                bid_id,
            )
    else:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT b.bid_amount, b.cover_letter, p.platform_id, p.skills_required
                  FROM klaravex_platform_bids b
                  JOIN klaravex_freelance_projects p ON p.id = b.project_id
                 WHERE b.id=$1
            """, bid_id)
        if row:
            from ..freelance_bid import _submit_freelancer_bid
            project_payload = {
                "platform_id": row["platform_id"],
                "skills": row["skills_required"],
            }
            bid_payload = {"bid_amount": row["bid_amount"], "cover_letter": row["cover_letter"]}
            ok, err = await _submit_freelancer_bid(project_payload, bid_payload)
            async with pool.acquire() as conn:
                if ok:
                    await conn.execute(
                        "UPDATE klaravex_platform_bids SET status='submitted', submitted_at=now() WHERE id=$1",
                        bid_id,
                    )
                else:
                    await conn.execute(
                        "UPDATE klaravex_platform_bids SET status='submit_failed', error_detail=$1 WHERE id=$2",
                        err, bid_id,
                    )
    return RedirectResponse(url="/portal/admin/approvals", status_code=303)


@router.get("/admin/marketing-leaderboard", response_class=HTMLResponse)
async def marketing_leaderboard_page(request: Request, email: str = Depends(current_user)):
    if email.lower() not in {e.lower() for e in _ADMIN_EMAILS}:
        raise HTTPException(status_code=403, detail="admin only")
    pool = await get_pool()
    async with pool.acquire() as conn:
        teams = await conn.fetch("""
            SELECT
              t.id, t.team_code, t.display_name, t.personality_brief, t.status,
              t.budget_usd, t.spend_usd, t.daily_spend_cap_usd,
              t.mercury_card_last4, t.attribution_tag, t.activated_at,
              (SELECT COUNT(*) FROM klaravex_clients WHERE attribution_team=t.attribution_tag) AS clients,
              (SELECT COUNT(*) FROM klaravex_marketing_actions WHERE team_id=t.id) AS actions,
              (SELECT COUNT(*) FROM klaravex_marketing_runs WHERE team_id=t.id) AS runs,
              (SELECT COUNT(*) FROM klaravex_marketing_actions
                 WHERE team_id=t.id AND status='pending' AND approval_required) AS pending_approvals
            FROM klaravex_marketing_teams t
            ORDER BY t.team_code
        """)
        recent_runs = await conn.fetch("""
            SELECT r.*, t.team_code FROM klaravex_marketing_runs r
            JOIN klaravex_marketing_teams t ON t.id=r.team_id
            ORDER BY r.started_at DESC LIMIT 15
        """)
        pending_actions = await conn.fetch("""
            SELECT a.*, t.team_code FROM klaravex_marketing_actions a
            JOIN klaravex_marketing_teams t ON t.id=a.team_id
            WHERE a.status='pending' AND a.approval_required
            ORDER BY a.created_at DESC LIMIT 25
        """)
    teams_list = []
    for t in teams:
        spend = float(t["spend_usd"] or 0)
        clients = int(t["clients"] or 0)
        teams_list.append({
            **dict(t),
            "spend_usd_f": spend,
            "clients_acquired": clients,
            "cac_usd": round(spend / clients, 2) if clients else None,
            "budget_remaining": float(t["budget_usd"] or 0) - spend,
        })
    return templates.TemplateResponse(
        request, "marketing_leaderboard.html",
        {
            "email": email,
            "teams": teams_list,
            "recent_runs": [dict(r) for r in recent_runs],
            "pending_actions": [dict(r) for r in pending_actions],
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Routes — Onboarding checklist
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request, email: str = Depends(current_user)):
    from ..lib.onboarding import get_checklist, kickoff_cta_url
    checklist = await get_checklist(email)
    return templates.TemplateResponse(
        request, "onboarding.html",
        {
            "email": email,
            "checklist": checklist,
            "kickoff_url": kickoff_cta_url(),
        },
    )


@router.post("/onboarding/task/toggle", response_class=HTMLResponse)
async def onboarding_task_toggle(
    request: Request,
    task_key: str = Form(...),
    done: str = Form("on"),
    email: str = Depends(current_user),
):
    from ..lib.onboarding import toggle_task
    await toggle_task(email, task_key, done == "on")
    return RedirectResponse(url="/portal/onboarding", status_code=303)


@router.post("/onboarding/kickoff-request", response_class=HTMLResponse)
async def onboarding_kickoff_request(
    request: Request,
    preferred_times: str = Form(...),
    email: str = Depends(current_user),
):
    from ..lib.onboarding import request_kickoff
    await request_kickoff(email, preferred_times[:500])
    return RedirectResponse(url="/portal/onboarding?kickoff=requested", status_code=303)


# ──────────────────────────────────────────────────────────────────────────────
# Routes — B2B project workflow
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/projects", response_class=HTMLResponse)
async def projects_list(request: Request, email: str = Depends(current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, status, total_budget_usd, sow_accepted_at, created_at
              FROM klaravex_projects WHERE client_email=$1 ORDER BY created_at DESC
            """,
            email.lower(),
        )
    return templates.TemplateResponse(
        request, "projects_list.html",
        {"email": email, "projects": [dict(r) for r in rows]},
    )


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str, email: str = Depends(current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        p = await conn.fetchrow(
            "SELECT * FROM klaravex_projects WHERE id=$1 AND client_email=$2",
            project_id, email.lower(),
        )
        if not p:
            raise HTTPException(status_code=404, detail="project not found")
        milestones = await conn.fetch(
            "SELECT * FROM klaravex_project_milestones WHERE project_id=$1 ORDER BY sequence",
            project_id,
        )
    return templates.TemplateResponse(
        request, "project_detail.html",
        {
            "email": email,
            "project": dict(p),
            "milestones": [dict(m) for m in milestones],
        },
    )


@router.get("/projects/{project_id}/accept", response_class=HTMLResponse)
async def project_accept_sow(
    request: Request, project_id: str, token: str = "",
    email: str = Depends(current_user),
):
    from ..lib.projects import accept_sow
    result = await accept_sow(project_id, token)
    if not result.get("ok"):
        return HTMLResponse(
            f"<h2>Couldn't accept: {result.get('error')}</h2>"
            f"<p><a href='/portal/projects/{project_id}'>Back to project</a></p>",
            status_code=400,
        )
    return RedirectResponse(url=f"/portal/projects/{project_id}?accepted=1", status_code=303)


@router.post("/projects/milestone/signoff", response_class=HTMLResponse)
async def project_milestone_signoff(
    request: Request, token: str = Form(...),
    email: str = Depends(current_user),
):
    from ..lib.projects import sign_off_milestone
    result = await sign_off_milestone(token)
    if not result.get("ok"):
        return HTMLResponse(f"<h2>Sign-off failed: {result.get('error')}</h2>", status_code=400)
    return HTMLResponse(
        f"""<!doctype html><html><body style="font-family:sans-serif; max-width:600px; margin:3rem auto;">
            <h1>Milestone signed off ✓</h1>
            <p>An invoice has been queued for ${result.get('amount_cents',0)/100:.2f}. Stripe will email it shortly.</p>
            <p><a href="/portal/projects">Back to projects</a></p>
            </body></html>"""
        )


# ──────────────────────────────────────────────────────────────────────────────
# Routes — GDPR / CCPA data export self-service
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/data-export", response_class=HTMLResponse)
async def data_export_page(request: Request, email: str = Depends(current_user)):
    from ..lib.data_export import list_export_requests
    history = await list_export_requests(email)
    return templates.TemplateResponse(
        request, "data_export.html",
        {"email": email, "history": history},
    )


@router.post("/data-export/request", response_class=HTMLResponse)
async def data_export_request(request: Request, email: str = Depends(current_user)):
    from ..lib.data_export import request_export, list_export_requests
    result = await request_export(email)
    history = await list_export_requests(email)
    return templates.TemplateResponse(
        request, "data_export.html",
        {"email": email, "history": history, "result": result},
    )


@router.get("/data-export/download")
async def data_export_download(token: str):
    """Single-use, signed download link emailed to the user."""
    from fastapi.responses import Response
    from ..lib.data_export import resolve_download_token
    resolved = await resolve_download_token(token)
    if not resolved:
        return HTMLResponse(
            "<h2>Download link expired, already used, or invalid.</h2>"
            "<p><a href='/portal/data-export'>Request a fresh export</a></p>",
            status_code=410,
        )
    email_lc, file_bytes = resolved
    safe_name = "klaravex-data-export.json"
    return Response(
        content=file_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Routes — Cancellation intercept + save flow
# ──────────────────────────────────────────────────────────────────────────────


def _resolve_sub_plan_for_cancel(subscription_id: str) -> tuple[Optional[str], Optional[str]]:
    """Return (customer_id, plan_name) for a subscription. Used by cancel flow."""
    import stripe as _stripe
    _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    try:
        s = _stripe.Subscription.retrieve(subscription_id, expand=["items.data.price"])
        s_dict = s.to_dict() if hasattr(s, "to_dict") else dict(s)
        items = (s_dict.get("items") or {}).get("data") or []
        plan_name = None
        if items:
            price = items[0].get("price") or {}
            prod = price.get("product")
            if isinstance(prod, str):
                try:
                    p_obj = _stripe.Product.retrieve(prod)
                    p_dict = p_obj.to_dict() if hasattr(p_obj, "to_dict") else dict(p_obj)
                    plan_name = p_dict.get("name")
                except Exception:
                    pass
        return s_dict.get("customer"), plan_name
    except Exception as exc:
        log.warning("sub retrieve for cancel failed %s: %s", subscription_id, exc)
        return None, None


@router.get("/cancel/{subscription_id}", response_class=HTMLResponse)
async def cancel_page(
    request: Request,
    subscription_id: str,
    email: str = Depends(current_user),
):
    """Step 1: customer chooses an exit reason."""
    from ..lib.cancellation import REASON_LABELS
    customer_id, plan_name = _resolve_sub_plan_for_cancel(subscription_id)
    return templates.TemplateResponse(
        request,
        "cancel_reason.html",
        {
            "email": email,
            "subscription_id": subscription_id,
            "plan_name": plan_name or "your plan",
            "reason_labels": REASON_LABELS,
        },
    )


@router.post("/cancel/{subscription_id}/reason", response_class=HTMLResponse)
async def cancel_reason_submit(
    request: Request,
    subscription_id: str,
    reason_category: str = Form(...),
    reason_detail: str = Form(""),
    email: str = Depends(current_user),
):
    """Step 2: log the reason, present a save offer (or skip to confirm if quality issue)."""
    from ..lib.cancellation import offer_for_reason, REASON_LABELS, log_attempt
    customer_id, plan_name = _resolve_sub_plan_for_cancel(subscription_id)
    offer = offer_for_reason(reason_category)
    await log_attempt(
        subscription_id=subscription_id,
        customer_id=customer_id or "unknown",
        email=email,
        plan_name=plan_name,
        reason_category=reason_category,
        reason_detail=reason_detail[:500] if reason_detail else None,
        save_offer_shown=offer,
        final_outcome="abandoned",
    )
    return templates.TemplateResponse(
        request,
        "cancel_offer.html",
        {
            "email": email,
            "subscription_id": subscription_id,
            "plan_name": plan_name or "your plan",
            "reason_category": reason_category,
            "reason_label": REASON_LABELS.get(reason_category, reason_category),
            "offer": offer,
        },
    )


@router.post("/cancel/{subscription_id}/action", response_class=HTMLResponse)
async def cancel_action(
    request: Request,
    subscription_id: str,
    action: str = Form(...),
    reason_category: str = Form("other"),
    email: str = Depends(current_user),
):
    """Step 3: apply the chosen save action or confirm cancellation."""
    from ..lib.cancellation import (
        apply_pause_30d, apply_discount_25pct, confirm_cancel, log_attempt,
    )
    customer_id, plan_name = _resolve_sub_plan_for_cancel(subscription_id)
    customer_id = customer_id or "unknown"

    if action == "pause_30d":
        result = await apply_pause_30d(subscription_id)
        outcome = "saved" if result.get("ok") else "abandoned"
        offer = "pause_30d"
        offer_outcome = "accepted" if result.get("ok") else "declined"
        message_title = "Paused for 30 days"
        message_body = "Your subscription is paused. You won't be charged until it resumes. We'll email you a few days before."
    elif action == "discount_25pct":
        result = await apply_discount_25pct(subscription_id, customer_id)
        outcome = "saved" if result.get("ok") else "abandoned"
        offer = "discount_25pct"
        offer_outcome = "accepted" if result.get("ok") else "declined"
        message_title = "25% off applied for 3 months"
        message_body = "Your next 3 invoices will be 25% off. Welcome back."
    elif action == "confirm_cancel":
        result = await confirm_cancel(subscription_id)
        outcome = "cancelled" if result.get("ok") else "abandoned"
        offer = "none"
        offer_outcome = "declined"
        message_title = "Cancellation scheduled"
        message_body = "Your subscription will end at the close of the current billing period. You'll keep full access until then."
    else:
        return templates.TemplateResponse(
            request, "cancel_offer.html",
            {"email": email, "subscription_id": subscription_id, "plan_name": plan_name,
             "reason_category": reason_category, "offer": "none", "error": "Unknown action."},
            status_code=400,
        )

    await log_attempt(
        subscription_id=subscription_id,
        customer_id=customer_id,
        email=email,
        plan_name=plan_name,
        reason_category=reason_category,
        save_offer_shown=offer,
        save_offer_outcome=offer_outcome,
        final_outcome=outcome,
    )

    return templates.TemplateResponse(
        request,
        "cancel_done.html",
        {
            "email": email,
            "subscription_id": subscription_id,
            "title": message_title,
            "body": message_body,
            "result": result,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Routes — operator/internal JSON endpoints (used by KB reindex + tests)
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/internal/kb/reindex", include_in_schema=False)
async def kb_reindex(request: Request):
    # Protected by a shared secret. NOT exposed in the OpenAPI schema.
    expected = os.environ.get("LOKI_INTERNAL_SECRET", "")
    presented = request.headers.get("x-loki-internal-secret", "")
    if not expected or not secrets.compare_digest(expected, presented):
        raise HTTPException(status_code=403, detail="forbidden")
    stats = await kb_lib.reindex_all()
    return JSONResponse(stats)


@router.get("/internal/escalations", include_in_schema=False)
async def open_escalations(request: Request):
    expected = os.environ.get("LOKI_INTERNAL_SECRET", "")
    presented = request.headers.get("x-loki-internal-secret", "")
    if not expected or not secrets.compare_digest(expected, presented):
        raise HTTPException(status_code=403, detail="forbidden")
    rows = await escalation_lib.list_unacknowledged()
    return JSONResponse({"open": rows})
