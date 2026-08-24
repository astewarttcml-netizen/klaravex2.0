"""
Calendly OAuth + webhook handling.

Flow:
  1. Anthony hits /api/v1/calendly/oauth/start → redirected to Calendly authorize page
  2. Anthony approves on Calendly → redirected back to /api/v1/calendly/oauth/callback?code=...
  3. We exchange code for access_token + refresh_token, store in klaravex_calendly_tokens
  4. We auto-create a webhook subscription pointing at /api/v1/calendly/webhook
  5. Calendly fires invitee.created when a customer books → we mark the kickoff task complete
"""

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .lib.db import get_pool
from .lib.onboarding import toggle_task

log = logging.getLogger("klaravex.calendly")
router = APIRouter()

CALENDLY_CLIENT_ID = os.environ.get("CALENDLY_CLIENT_ID", "")
CALENDLY_CLIENT_SECRET = os.environ.get("CALENDLY_CLIENT_SECRET", "")
CALENDLY_WEBHOOK_KEY = os.environ.get("CALENDLY_WEBHOOK_KEY", "")
CALENDLY_REDIRECT_URI = os.environ.get(
    "CALENDLY_REDIRECT_URI",
    "https://api.klaravex.com/api/v1/calendly/oauth/callback",
)
ANTHONY_EMAIL = os.environ.get("ANTHONY_EMAIL", "astewart@klaravex.com")

CALENDLY_AUTH_URL = "https://auth.calendly.com/oauth/authorize"
CALENDLY_TOKEN_URL = "https://auth.calendly.com/oauth/token"
CALENDLY_API = "https://api.calendly.com"


# ── Token storage ─────────────────────────────────────────────────────────────

async def _save_tokens(
    *,
    owner_email: str,
    access_token: str,
    refresh_token: str,
    expires_in: int,
    user_uri: Optional[str],
    org_uri: Optional[str],
    scope: Optional[str],
) -> None:
    expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=int(expires_in) - 60)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO klaravex_calendly_tokens
                (owner_email, calendly_user_uri, calendly_org_uri,
                 access_token, refresh_token, expires_at, scope, webhook_signing_key)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (owner_email) DO UPDATE
              SET calendly_user_uri = EXCLUDED.calendly_user_uri,
                  calendly_org_uri  = EXCLUDED.calendly_org_uri,
                  access_token  = EXCLUDED.access_token,
                  refresh_token = EXCLUDED.refresh_token,
                  expires_at    = EXCLUDED.expires_at,
                  scope         = EXCLUDED.scope,
                  webhook_signing_key = EXCLUDED.webhook_signing_key,
                  updated_at    = now()
            """,
            owner_email.lower(), user_uri, org_uri,
            access_token, refresh_token, expires_at, scope, CALENDLY_WEBHOOK_KEY or None,
        )


async def _load_tokens(owner_email: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM klaravex_calendly_tokens WHERE owner_email=$1",
            owner_email.lower(),
        )
    return dict(row) if row else None


async def get_valid_access_token(owner_email: str = ANTHONY_EMAIL) -> Optional[str]:
    """Returns a fresh access token, refreshing if expired."""
    tokens = await _load_tokens(owner_email)
    if not tokens:
        return None
    if tokens["expires_at"] > datetime.now(tz=timezone.utc):
        return tokens["access_token"]
    # Refresh
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                CALENDLY_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": CALENDLY_CLIENT_ID,
                    "client_secret": CALENDLY_CLIENT_SECRET,
                    "refresh_token": tokens["refresh_token"],
                },
            )
        if r.status_code != 200:
            log.warning("calendly refresh failed: %s %s", r.status_code, r.text[:200])
            return None
        data = r.json()
        await _save_tokens(
            owner_email=owner_email,
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", tokens["refresh_token"]),
            expires_in=data.get("expires_in", 7200),
            user_uri=tokens["calendly_user_uri"],
            org_uri=tokens["calendly_org_uri"],
            scope=data.get("scope", tokens["scope"]),
        )
        return data["access_token"]
    except Exception as exc:
        log.exception("calendly refresh exception: %s", exc)
        return None


# ── OAuth flow ────────────────────────────────────────────────────────────────

@router.get("/oauth/start")
async def oauth_start():
    """Step 1: redirect Anthony to Calendly's authorize page."""
    if not (CALENDLY_CLIENT_ID and CALENDLY_CLIENT_SECRET):
        return HTMLResponse(
            "<h2>Calendly OAuth not configured.</h2>"
            "<p>Set CALENDLY_CLIENT_ID and CALENDLY_CLIENT_SECRET env vars first.</p>",
            status_code=500,
        )
    state = secrets.token_urlsafe(32)
    params = (
        f"client_id={CALENDLY_CLIENT_ID}&"
        f"response_type=code&"
        f"redirect_uri={CALENDLY_REDIRECT_URI}&"
        f"state={state}"
    )
    return RedirectResponse(url=f"{CALENDLY_AUTH_URL}?{params}", status_code=303)


@router.get("/oauth/callback")
async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Step 2: Calendly redirects here with code. We exchange for tokens."""
    if error:
        return HTMLResponse(f"<h2>Authorization failed: {error}</h2>", status_code=400)
    if not code:
        return HTMLResponse("<h2>Missing code parameter.</h2>", status_code=400)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                CALENDLY_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": CALENDLY_CLIENT_ID,
                    "client_secret": CALENDLY_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": CALENDLY_REDIRECT_URI,
                },
            )
        if r.status_code != 200:
            log.warning("calendly token exchange failed: %s %s", r.status_code, r.text[:300])
            return HTMLResponse(
                f"<h2>Token exchange failed.</h2><pre>{r.status_code} {r.text[:400]}</pre>",
                status_code=500,
            )
        td = r.json()
        access_token = td["access_token"]
        refresh_token = td["refresh_token"]
        expires_in = td.get("expires_in", 7200)
        scope = td.get("scope")

        # Look up user info to capture the URI
        async with httpx.AsyncClient(timeout=15) as client:
            me = await client.get(
                f"{CALENDLY_API}/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        user_uri = None
        org_uri = None
        if me.status_code == 200:
            user_data = me.json().get("resource", {})
            user_uri = user_data.get("uri")
            org_uri = user_data.get("current_organization")

        await _save_tokens(
            owner_email=ANTHONY_EMAIL,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            user_uri=user_uri,
            org_uri=org_uri,
            scope=scope,
        )

        # Try to create a webhook subscription for invitee.created
        webhook_created = await _ensure_invitee_webhook(access_token, org_uri, user_uri)

        return HTMLResponse(f"""
<!doctype html><html><head><title>Calendly connected</title>
<style>body{{font-family:sans-serif;max-width:600px;margin:3rem auto;padding:0 1rem}}.k{{color:#5eead4}}</style>
</head><body>
<h1 class="k">✓ Calendly connected to Klaravex</h1>
<p>Access token stored. Token will auto-refresh every ~2 hours.</p>
<p><strong>Your Calendly user URI:</strong> <code>{user_uri or 'unknown'}</code></p>
<p><strong>Webhook subscription:</strong> {webhook_created}</p>
<p>You can close this tab. Customer kickoff bookings will now auto-mark the onboarding task complete.</p>
</body></html>
""")
    except Exception as exc:
        log.exception("calendly oauth callback exception: %s", exc)
        return HTMLResponse(f"<h2>Internal error: {exc}</h2>", status_code=500)


async def _ensure_invitee_webhook(access_token: str, org_uri: Optional[str], user_uri: Optional[str]) -> str:
    """Create webhook subscription for invitee.created events if not already present."""
    if not org_uri:
        return "skipped (no org URI)"
    webhook_url = "https://api.klaravex.com/api/v1/calendly/webhook"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            existing = await client.get(
                f"{CALENDLY_API}/webhook_subscriptions",
                params={"organization": org_uri, "scope": "organization", "count": 100},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if existing.status_code == 200:
                for w in existing.json().get("collection", []):
                    if w.get("callback_url") == webhook_url:
                        return f"already exists ({w.get('uri','')})"

            r = await client.post(
                f"{CALENDLY_API}/webhook_subscriptions",
                json={
                    "url": webhook_url,
                    "events": ["invitee.created", "invitee.canceled"],
                    "organization": org_uri,
                    "scope": "organization",
                    **({"signing_key": CALENDLY_WEBHOOK_KEY} if CALENDLY_WEBHOOK_KEY else {}),
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if r.status_code in (200, 201):
            return f"created ({r.json().get('resource',{}).get('uri','')})"
        return f"failed: {r.status_code} {r.text[:200]}"
    except Exception as exc:
        return f"exception: {exc}"


# ── Webhook handler ───────────────────────────────────────────────────────────

def _verify_calendly_signature(payload: bytes, signature_header: str) -> bool:
    """Calendly sends signature like: t=TIMESTAMP,v1=SIGNATURE."""
    if not CALENDLY_WEBHOOK_KEY or not signature_header:
        return False
    parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
    timestamp = parts.get("t", "")
    expected_v1 = parts.get("v1", "")
    if not timestamp or not expected_v1:
        return False
    signed_payload = f"{timestamp}.{payload.decode('utf-8', errors='ignore')}".encode("utf-8")
    actual = hmac.new(CALENDLY_WEBHOOK_KEY.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(actual, expected_v1)


@router.post("/webhook")
async def calendly_webhook(request: Request):
    """Handle Calendly invitee.created → mark onboarding kickoff_call task complete."""
    payload = await request.body()
    sig = request.headers.get("calendly-webhook-signature", "")
    if CALENDLY_WEBHOOK_KEY and not _verify_calendly_signature(payload, sig):
        log.warning("calendly webhook signature invalid")
        raise HTTPException(status_code=401, detail="invalid signature")

    import json
    try:
        body = json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    event = body.get("event", "")
    payload_data = body.get("payload", {})
    invitee_email = payload_data.get("email")

    log.info("calendly webhook: event=%s invitee=%s", event, invitee_email)

    if event == "invitee.created" and invitee_email:
        # Mark the kickoff_call task complete if this invitee has an onboarding checklist
        pool = await get_pool()
        async with pool.acquire() as conn:
            has_checklist = await conn.fetchval(
                "SELECT 1 FROM klaravex_onboarding_checklists WHERE email=$1",
                invitee_email.lower(),
            )
            if has_checklist:
                # Also update kickoff_scheduled_at
                await conn.execute(
                    "UPDATE klaravex_onboarding_checklists SET kickoff_scheduled_at=now() WHERE email=$1",
                    invitee_email.lower(),
                )
        if has_checklist:
            result = await toggle_task(invitee_email, "kickoff_call", True)
            log.info("auto-marked kickoff_call complete for %s: %s", invitee_email, result)

    return {"status": "ok"}
