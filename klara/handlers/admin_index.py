"""Klaravex admin console — Google + Microsoft 365 OAuth at /admin.

Replaces the on-demand ?secret= URLs and the earlier magic-link iteration.
Workflow:
  1. Anthony visits https://api.klaravex.com/admin
  2. If session cookie missing → tiny HTML page with "Sign in with Google"
     and "Sign in with Microsoft 365" buttons
  3. Provider redirect → OAuth flow → /admin/auth/<provider>/callback
  4. Email is verified + checked against ADMIN_EMAILS allowlist
  5. Session cookie set; /admin/ renders the approval-queue console

Reuses the SAME Google OAuth client that backs klaravex.com
(env: GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET — values copied
from /opt/loki-agents/.env's OAUTH2_PROXY_* keys).

Microsoft side uses the existing MS_GRAPH_CLIENT_ID against the Klaravex
Entra tenant (MS_GRAPH_TENANT_ID). Requires "Sign in users" permission +
the /admin/auth/microsoft/callback redirect URI added to the Entra app.

Session cookie: HMAC-SHA256(email|expiry) keyed by LOKI_INTERNAL_SECRET,
HttpOnly, Secure, SameSite=Lax, 24h max_age, path=/admin (so it scopes to
every /admin/* sub-router).

T14.3: the legacy ?secret=<LOKI_INTERNAL_SECRET> query-string auth on the
inbox + social dashboards has been removed. /admin/* routers now consume
the session cookie via `lib.admin_auth.require_admin_session`.
"""

import datetime
import hashlib
import hmac
import logging
import os
import secrets as pysecrets
import time
from pathlib import Path
from secrets import compare_digest
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

log = logging.getLogger("klaravex.admin_index")
router = APIRouter()

_templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)


def _user_initials(email: str) -> str:
    name = email.split("@")[0]
    parts = name.replace(".", " ").replace("_", " ").split()
    return "".join(p[0].upper() for p in parts[:2]) or "A"


def _time_ago(dt: datetime.datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    delta = datetime.datetime.now(datetime.timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"

# ── Config from env ────────────────────────────────────────────────────────────
_LOKI_SECRET = os.environ.get("LOKI_INTERNAL_SECRET", "")
_ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get(
        "ADMIN_EMAILS",
        "astewart.tcml@gmail.com,astewar86@gmail.com,astewart@klaravex.com",
    ).split(",")
    if e.strip()
}
_APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://api.klaravex.com").rstrip("/")

# Google OAuth — read from env first, then fall back to settings if available
_GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
_GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
_GOOGLE_REDIRECT_URI = f"{_APP_BASE_URL}/admin/auth/google/callback"

_MS_TENANT_ID = os.environ.get("MS_GRAPH_TENANT_ID", "")
_MS_CLIENT_ID = os.environ.get("ADMIN_OAUTH_MS_CLIENT_ID", os.environ.get("MS_GRAPH_CLIENT_ID", ""))
_MS_CLIENT_SECRET = os.environ.get(
    "ADMIN_OAUTH_MS_CLIENT_SECRET", os.environ.get("MS_GRAPH_CLIENT_SECRET", "")
)
_MS_REDIRECT_URI = f"{_APP_BASE_URL}/admin/auth/microsoft/callback"

SESSION_COOKIE = "klaravex_admin_session"
STATE_COOKIE = "klaravex_admin_oauth_state"
SESSION_TTL_S = 24 * 3600
STATE_TTL_S = 10 * 60


def _google_oauth_configured() -> bool:
    """Return True when Google OAuth client credentials are present."""
    return bool(_GOOGLE_CLIENT_ID and _GOOGLE_CLIENT_SECRET)


def _microsoft_oauth_configured() -> bool:
    """Return True when Microsoft OAuth client credentials are present."""
    return bool(_MS_CLIENT_ID and _MS_TENANT_ID)


def _safe_log_field(value: str) -> str:
    # CWE-117: strip CR/LF/TAB so attacker-controlled OAuth claims (email, etc.)
    # cannot forge log lines when interpolated via %s into text-sink loggers.
    return value.replace("\r", "").replace("\n", "").replace("\t", "")


# ── Session token signing ──────────────────────────────────────────────────────
def _sign(email: str, expires_at: int) -> str:
    if not _LOKI_SECRET:
        raise HTTPException(503, "admin auth not configured (LOKI_INTERNAL_SECRET unset)")
    msg = f"{email}|{expires_at}".encode()
    sig = hmac.new(_LOKI_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:32]
    return f"{email}|{expires_at}|{sig}"


def verify_session(token: str | None) -> str | None:
    """Return the email if the session token is valid + unexpired + allowlisted."""
    if not token or not _LOKI_SECRET:
        return None
    try:
        email, expires_at_s, sig = token.split("|")
        expires_at = int(expires_at_s)
    except (ValueError, TypeError):
        return None
    if expires_at < int(time.time()):
        return None
    expected_sig = _sign(email, expires_at).split("|")[2]
    if not compare_digest(expected_sig, sig):
        return None
    if email.lower() not in _ADMIN_EMAILS:
        return None
    return email


def _login_page(error: str | None = None) -> HTMLResponse:
    tmpl = _templates.env.get_template("admin_login.html")
    return HTMLResponse(tmpl.render(error=error))


async def _check_health(url: str, timeout: float = 5.0) -> dict:
    """Best-effort HTTP health check. Returns {ok, status, latency_ms}."""
    import time as _time
    try:
        t0 = _time.monotonic()
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
        latency = int((_time.monotonic() - t0) * 1000)
        return {"ok": r.status_code == 200, "status": r.status_code, "latency_ms": latency}
    except Exception as e:
        return {"ok": False, "status": 0, "latency_ms": 0, "error": str(e)[:60]}


async def _dashboard_data(email: str) -> dict:
    """Fetch all data for the dashboard template. Best-effort — failures yield zeros."""
    from .lib.db import get_pool

    stats: dict = {
        "open_tickets": 0, "pending_approvals": 0, "active_projects": 0,
        "nps_avg": None, "nps_count": 0, "loki_running": 0, "loki_today": 0,
        "pending_action_requests": 0,
        # New: socials, freelancer, leads
        "social_published_24h": 0, "social_failed_24h": 0, "social_pending": 0,
        "freelancer_bids_24h": 0, "freelancer_matches_pending": 0,
        "leads_total": 0, "leads_hot": 0, "leads_24h": 0,
        "active_clients": 0,
    }
    loki_activity: list[dict] = []
    recent_tickets: list[dict] = []
    social_recent: list[dict] = []
    freelancer_recent: list[dict] = []
    leads_recent: list[dict] = []
    health_checks: dict = {}

    # ── Health checks (parallel, non-blocking) ────────────────────────────────
    import asyncio as _aio
    # Only check publicly-reachable services server-side. Tailscale-only
    # services (worker_usa, admin-api, rig) are checked client-side from
    # the browser, which has Tailscale access — see admin_dashboard.html.
    health_tasks = {
        "api": _check_health("https://api.klaravex.com/health"),
        "site": _check_health("https://klaravex.com/"),
    }
    health_results = await _aio.gather(*health_tasks.values(), return_exceptions=True)
    for key, result in zip(health_tasks.keys(), health_results):
        if isinstance(result, Exception):
            health_checks[key] = {"ok": False, "status": 0, "error": str(result)[:60]}
        else:
            health_checks[key] = result

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            stats["open_tickets"] = await conn.fetchval(
                "SELECT COUNT(*) FROM klaravex_tickets WHERE status IN ('open','in_progress','escalated')"
            ) or 0
            stats["active_projects"] = await conn.fetchval(
                "SELECT COUNT(*) FROM klaravex_projects WHERE status IN ('active','final_signoff')"
            ) or 0
            stats["active_clients"] = await conn.fetchval(
                "SELECT COUNT(*) FROM klaravex_clients WHERE status = 'active'"
            ) or 0
            nps_row = await conn.fetchrow(
                "SELECT ROUND(AVG(score)::numeric, 1) AS avg_score, COUNT(*) AS n "
                "FROM klaravex_portal_nps WHERE created_at > now() - interval '90 days'"
            )
            if nps_row and nps_row["n"]:
                stats["nps_avg"] = float(nps_row["avg_score"])
                stats["nps_count"] = int(nps_row["n"])
            social = await conn.fetchval(
                "SELECT COUNT(*) FROM klaravex_social_drafts WHERE status='pending'"
            ) or 0
            marketing = await conn.fetchval(
                "SELECT COUNT(*) FROM klaravex_marketing_actions WHERE status='pending' AND approval_required"
            ) or 0
            bids = await conn.fetchval(
                "SELECT COUNT(*) FROM klaravex_platform_bids WHERE status='queued'"
            ) or 0
            outreach = await conn.fetchval(
                "SELECT COUNT(*) FROM klaravex_outreach_approvals "
                "WHERE status='pending' OR (status='approved' AND sent_at IS NULL)"
            ) or 0
            kb = await conn.fetchval(
                "SELECT COUNT(*) FROM klaravex_kb_drafts WHERE status='pending'"
            ) or 0
            stats["pending_approvals"] = social + marketing + bids + outreach + kb

            stats["pending_action_requests"] = await conn.fetchval(
                "SELECT COUNT(*) FROM klaravex.approval_requests "
                "WHERE status='pending' AND NOT (action_name = ANY($1::varchar[]))",
                ["contract.send", "contract.generate", "contract.renewal",
                 "deal.send_contract", "deal.generate_contract"],
            ) or 0

            # ── Socials (all activity, not just pending) ──────────────────────
            try:
                stats["social_pending"] = social
                stats["social_published_24h"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM klaravex_social_drafts "
                    "WHERE status='published' AND updated_at > now() - interval '24h'"
                ) or 0
                stats["social_failed_24h"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM klaravex_social_drafts "
                    "WHERE status='rejected' AND updated_at > now() - interval '24h'"
                ) or 0
                social_rows = await conn.fetch(
                    "SELECT platform, status, content, created_at, updated_at "
                    "FROM klaravex_social_drafts "
                    "ORDER BY created_at DESC LIMIT 6"
                )
                for r in social_rows:
                    social_recent.append({
                        "platform": r["platform"] or "—",
                        "status": r["status"],
                        "content": (r["content"] or "")[:80],
                        "created_ago": _time_ago(r["created_at"]),
                    })
            except Exception:  # noqa: BLE001
                pass

            # ── Freelancer bids + matches ─────────────────────────────────────
            try:
                stats["freelancer_bids_24h"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM klaravex_platform_bids "
                    "WHERE created_at > now() - interval '24h'"
                ) or 0
                stats["freelancer_matches_pending"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM klaravex_freelance_matches WHERE status='pending'"
                ) or 0
                fl_rows = await conn.fetch(
                    "SELECT platform, project_title, status, created_at "
                    "FROM klaravex_platform_bids "
                    "ORDER BY created_at DESC LIMIT 4"
                )
                for r in fl_rows:
                    freelancer_recent.append({
                        "platform": r["platform"] or "—",
                        "title": (r["project_title"] or "")[:60],
                        "status": r["status"],
                        "created_ago": _time_ago(r["created_at"]),
                    })
            except Exception:  # noqa: BLE001
                pass

            # ── Leads ─────────────────────────────────────────────────────────
            try:
                stats["leads_total"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM klaravex_leads"
                ) or 0
                stats["leads_hot"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM klaravex_leads WHERE score >= 60"
                ) or 0
                stats["leads_24h"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM klaravex_leads WHERE created_at > now() - interval '24h'"
                ) or 0
                lead_rows = await conn.fetch(
                    "SELECT name, email, source, score, status, created_at "
                    "FROM klaravex_leads "
                    "ORDER BY created_at DESC LIMIT 4"
                )
                for r in lead_rows:
                    leads_recent.append({
                        "name": r["name"] or "—",
                        "email": r["email"] or "",
                        "source": r["source"] or "—",
                        "score": r["score"] or 0,
                        "status": r["status"] or "new",
                        "created_ago": _time_ago(r["created_at"]),
                    })
            except Exception:  # noqa: BLE001
                pass

            # ── Klara AI activity ─────────────────────────────────────────────────
            try:
                loki_rows = await conn.fetch(
                    "SELECT agent_id, topic, surface, action_summary, created_at "
                    "FROM note_submissions "
                    "WHERE topic IN ('loki-agent','deployment','code-edit') "
                    "ORDER BY created_at DESC LIMIT 4"
                )
                for r in loki_rows:
                    loki_activity.append({
                        "topic_slug": r["topic"],
                        "agent_id": r["agent_id"] or "—",
                        "content": r["action_summary"] or "",
                        "surface": r["surface"] or "",
                        "created_ago": _time_ago(r["created_at"]),
                    })
                stats["loki_today"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM note_submissions "
                    "WHERE created_at > now() - interval '24h'"
                ) or 0
            except Exception:  # noqa: BLE001
                pass

            # ── Recent tickets ────────────────────────────────────────────────
            try:
                ticket_rows = await conn.fetch(
                    "SELECT title, status, created_at, "
                    "       COALESCE(client_name, '') AS client_name "
                    "FROM klaravex_tickets "
                    "WHERE status IN ('open','in_progress','escalated') "
                    "ORDER BY created_at DESC LIMIT 4"
                )
                for r in ticket_rows:
                    stripe = "crit" if r["status"] == "escalated" else (
                        "warn" if r["status"] == "in_progress" else "info"
                    )
                    recent_tickets.append({
                        "title": r["title"] or "Untitled",
                        "status": r["status"],
                        "client_name": r["client_name"],
                        "stripe_class": stripe,
                        "created_ago": _time_ago(r["created_at"]),
                    })
            except Exception:  # noqa: BLE001
                pass

    except Exception as e:  # noqa: BLE001
        log.warning("dashboard stats query failed (showing zeros): %s", e)

    return {
        "stats": stats,
        "pending_approvals": stats["pending_approvals"],
        "loki_activity": loki_activity,
        "recent_tickets": recent_tickets,
        "social_recent": social_recent,
        "freelancer_recent": freelancer_recent,
        "leads_recent": leads_recent,
        "health_checks": health_checks,
        "user_email": email,
        "user_initials": _user_initials(email),
        "content_badge": stats["pending_approvals"] or None,
        "approvals_badge": stats["pending_action_requests"] or None,
    }


async def _console_page(email: str) -> HTMLResponse:
    ctx = await _dashboard_data(email)
    tmpl = _templates.env.get_template("admin_dashboard.html")
    return HTMLResponse(tmpl.render(**ctx))


async def _require_session(klaravex_admin_session: str | None = Cookie(default=None)) -> str:
    email = verify_session(klaravex_admin_session)
    if not email:
        raise HTTPException(status_code=401, detail="admin session required — sign in at /admin/")
    return email


# ── Stub pages (sidebar links without full implementations yet) ───────────────
@router.get("/billing", response_class=HTMLResponse, include_in_schema=False)
async def admin_billing(
    email: str = Depends(_require_session),
) -> HTMLResponse:
    tmpl = _templates.env.get_template("admin_stub.html")
    return HTMLResponse(tmpl.render(
        page_title="Billing",
        nav_key="billing",
        user_email=email,
        user_initials=_user_initials(email),
    ))


@router.get("/reports", response_class=HTMLResponse, include_in_schema=False)
async def admin_reports(
    email: str = Depends(_require_session),
) -> HTMLResponse:
    tmpl = _templates.env.get_template("admin_stub.html")
    return HTMLResponse(tmpl.render(
        page_title="Reports",
        nav_key="reports",
        user_email=email,
        user_initials=_user_initials(email),
    ))


# ── Index / login / logout ─────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_index(
    klaravex_admin_session: str | None = Cookie(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    email = verify_session(klaravex_admin_session)
    if email:
        return await _console_page(email)
    # Map query-param error codes to human-readable messages
    error_messages = {
        "google_oauth_not_configured": (
            "Google sign-in is not configured. "
            "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in the environment."
        ),
        "microsoft_oauth_not_configured": (
            "Microsoft 365 sign-in is not configured. "
            "Set ADMIN_OAUTH_MS_CLIENT_ID and MS_GRAPH_TENANT_ID in the environment."
        ),
    }
    display_error = error_messages.get(error, error)
    return _login_page(error=display_error)


@router.get("/logout", include_in_schema=False)
async def admin_logout() -> RedirectResponse:
    resp = RedirectResponse("/admin/", status_code=302)
    resp.delete_cookie(SESSION_COOKIE, path="/admin")
    return resp


# ── Google OAuth ───────────────────────────────────────────────────────────────
@router.get("/login/google", include_in_schema=False)
async def login_google() -> RedirectResponse:
    if not _google_oauth_configured():
        log.warning("admin_oauth.google_not_configured")
        # Graceful fallback: redirect back to login page with a clear error
        # instead of raising a raw 503 HTTPException.
        return RedirectResponse(
            "/admin/?error=google_oauth_not_configured", status_code=302
        )
    state = pysecrets.token_urlsafe(24)
    params = {
        "client_id": _GOOGLE_CLIENT_ID,
        "redirect_uri": _GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    resp = RedirectResponse(auth_url, status_code=302)
    resp.set_cookie(
        STATE_COOKIE, value=f"google:{state}",
        httponly=True, secure=True, samesite="lax",
        max_age=STATE_TTL_S, path="/admin",
    )
    return resp


@router.get("/auth/google/callback", include_in_schema=False, response_model=None)
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    klaravex_admin_oauth_state: str | None = Cookie(default=None),
) -> RedirectResponse | HTMLResponse:
    expected = klaravex_admin_oauth_state or ""
    if not expected.startswith("google:") or not compare_digest(expected.split(":", 1)[1], state):
        log.warning("admin_oauth.state_mismatch provider=google")
        return _login_page(error="OAuth state mismatch — try signing in again.")
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": _GOOGLE_CLIENT_ID,
                "client_secret": _GOOGLE_CLIENT_SECRET,
                "redirect_uri": _GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            log.error("admin_oauth.token_exchange_failed",
                      provider="google", status=token_resp.status_code, body=token_resp.text[:200])
            return _login_page(error="Could not complete Google sign-in.")
        access_token = token_resp.json().get("access_token", "")
        ui_resp = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if ui_resp.status_code != 200:
            return _login_page(error="Could not retrieve Google user info.")
        userinfo = ui_resp.json()
    email = (userinfo.get("email") or "").lower()
    email_verified = userinfo.get("email_verified", False)
    if not email or not email_verified:
        return _login_page(error="Google did not return a verified email.")
    if email not in _ADMIN_EMAILS:
        log.warning("admin_oauth.email_not_allowed provider=google email=%s", _safe_log_field(email))
        return _login_page(error=f"{email} is not an allowlisted admin.")
    return _set_session_and_redirect(email)


# ── Microsoft 365 OAuth ────────────────────────────────────────────────────────
@router.get("/login/microsoft", include_in_schema=False)
async def login_microsoft() -> RedirectResponse:
    if not _microsoft_oauth_configured():
        log.warning("admin_oauth.microsoft_not_configured")
        # Graceful fallback: redirect back to login page with a clear error
        # instead of raising a raw 503 HTTPException.
        return RedirectResponse(
            "/admin/?error=microsoft_oauth_not_configured", status_code=302
        )
    state = pysecrets.token_urlsafe(24)
    params = {
        "client_id": _MS_CLIENT_ID,
        "redirect_uri": _MS_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile User.Read",
        "state": state,
        "prompt": "select_account",
    }
    auth_url = (
        f"https://login.microsoftonline.com/{_MS_TENANT_ID}/oauth2/v2.0/authorize?"
        + urlencode(params)
    )
    resp = RedirectResponse(auth_url, status_code=302)
    resp.set_cookie(
        STATE_COOKIE, value=f"microsoft:{state}",
        httponly=True, secure=True, samesite="lax",
        max_age=STATE_TTL_S, path="/admin",
    )
    return resp


@router.get("/auth/microsoft/callback", include_in_schema=False, response_model=None)
async def microsoft_callback(
    code: str = Query(...),
    state: str = Query(...),
    klaravex_admin_oauth_state: str | None = Cookie(default=None),
) -> RedirectResponse | HTMLResponse:
    expected = klaravex_admin_oauth_state or ""
    if not expected.startswith("microsoft:") or not compare_digest(expected.split(":", 1)[1], state):
        log.warning("admin_oauth.state_mismatch provider=microsoft")
        return _login_page(error="OAuth state mismatch — try signing in again.")
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            f"https://login.microsoftonline.com/{_MS_TENANT_ID}/oauth2/v2.0/token",
            data={
                "code": code,
                "client_id": _MS_CLIENT_ID,
                "client_secret": _MS_CLIENT_SECRET,
                "redirect_uri": _MS_REDIRECT_URI,
                "grant_type": "authorization_code",
                "scope": "openid email profile User.Read",
            },
        )
        if token_resp.status_code != 200:
            log.error("admin_oauth.token_exchange_failed",
                      provider="microsoft", status=token_resp.status_code, body=token_resp.text[:200])
            return _login_page(error="Could not complete Microsoft sign-in.")
        access_token = token_resp.json().get("access_token", "")
        ui_resp = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if ui_resp.status_code != 200:
            return _login_page(error="Could not retrieve Microsoft user info.")
        userinfo = ui_resp.json()
    email = (userinfo.get("mail") or userinfo.get("userPrincipalName") or "").lower()
    if not email:
        return _login_page(error="Microsoft did not return an email address.")
    if email not in _ADMIN_EMAILS:
        log.warning("admin_oauth.email_not_allowed provider=microsoft email=%s", _safe_log_field(email))
        return _login_page(error=f"{email} is not an allowlisted admin.")
    return _set_session_and_redirect(email)


# ── Shared: set session cookie + redirect ──────────────────────────────────────
def _set_session_and_redirect(email: str) -> RedirectResponse:
    session_expires = int(time.time()) + SESSION_TTL_S
    session_token = _sign(email, session_expires)
    resp = RedirectResponse("/admin/", status_code=302)
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=SESSION_TTL_S,
        path="/admin",
    )
    resp.delete_cookie(STATE_COOKIE, path="/admin")
    log.info("admin_oauth.session_created email=%s", _safe_log_field(email))
    return resp
