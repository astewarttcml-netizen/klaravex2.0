"""
app/api/portal/auth.py
───────────────────────
Portal authentication endpoints.

Passwordless (magic link) — primary auth method:
  POST /api/v1/portal/auth/request-link  — email → magic link email
  GET  /api/v1/portal/auth/verify-link   — ?token=<raw> → JWT + redirect

Legacy password auth (kept for backward compat, can be removed later):
  POST /api/v1/portal/auth/login  — email + password → JWT

Session:
  GET  /api/v1/portal/auth/me     — return current client info
  POST /api/v1/portal/auth/logout — client-side token invalidation note

Magic link security:
  - Raw token never stored — only SHA-256 hash in portal_magic_links.
  - Single-use: used_at stamped on first verification.
  - 15-minute TTL.
  - Rate limited: 1 request per email per 5 minutes (Redis).
  - Email enumeration prevention: request-link always returns 200.
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import get_settings
from app.core.portal_auth import (
    create_portal_token,
    get_current_portal_client,
    verify_password,
)
from klara.rarv.runtime import get_db
from klara.rarv.audit import AuditLog
from klara.rarv.portal import Client
from klara.rarv.runtime.magic_link_service import _mask_email, peek_link, request_link, verify_link

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client_id: str
    client_name: str
    client_email: str
    expires_in_hours: int


class MeResponse(BaseModel):
    id: str
    name: str
    email: str
    company: str | None


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkRequestResponse(BaseModel):
    """Always returned — never reveals whether the email exists."""
    detail: str = (
        "If that email matches a portal account, you'll receive a login "
        "link within a few seconds. Check your inbox — it expires in 15 minutes."
    )


class PeekResponse(BaseModel):
    """
    Read-only token validity check — never burns the token.

    valid=True  → token exists, not expired, not used; email_hint is set.
    valid=False → token invalid/expired/used; reason is set.

    Always returned with HTTP 200 regardless of token state — giving scanners
    error codes would leak information about token existence.
    """
    valid: bool
    email_hint: Optional[str] = None   # only when valid=True
    reason: Optional[str] = None       # only when valid=False: "invalid_or_expired" | "already_used"


class MagicLinkVerifyRequest(BaseModel):
    token: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _log_audit(
    db: AsyncSession,
    event_type: str,
    client_id: str,
    ip: str | None = None,
    success: bool = True,
    error: str | None = None,
) -> None:
    """Write an audit log entry for portal auth events."""
    import uuid
    log = AuditLog(
        id=str(uuid.uuid4()),
        event_type=event_type,
        agent_name="portal_auth",
        lead_id=None,
        ip_address=ip,
        success=success,
        error_message=error,
        details=f"client_id={client_id}",
    )
    db.add(log)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse, summary="Client portal login")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate a client and return a JWT.

    - 401 if email not found, password wrong, or account inactive.
    - Updates last_login_at on success.
    - Writes audit log entry in both success and failure cases.

    The generic error message is intentional — don't reveal whether the email
    exists or not (prevents account enumeration).
    """
    from klara.rarv.runtime import get_settings

    ip = request.client.host if request.client else None
    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Look up client
    result = await db.execute(
        select(Client).where(Client.email == body.email.lower())
    )
    client: Client | None = result.scalar_one_or_none()

    # Passwordless accounts (hashed_password IS NULL) cannot use password login.
    # Direct them to use the magic link flow instead.
    if client is None or client.hashed_password is None or not verify_password(body.password, client.hashed_password):
        await _log_audit(
            db, "portal.login_failed", _mask_email(body.email), ip=ip, success=False,
            error="invalid_credentials"
        )
        logger.warning("portal.login_failed", email=_mask_email(body.email), ip=ip)
        raise generic_error

    if not client.is_active:
        await _log_audit(
            db, "portal.login_failed", client.id, ip=ip, success=False,
            error="account_inactive"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Please contact support.",
        )

    # Update last login timestamp
    await db.execute(
        update(Client)
        .where(Client.id == client.id)
        .values(last_login_at=datetime.now(timezone.utc))
    )

    token = create_portal_token(client)

    await _log_audit(db, "portal.login_success", client.id, ip=ip, success=True)
    logger.info("portal.login_success", client_id=client.id)

    settings = get_settings()
    return TokenResponse(
        access_token=token,
        client_id=client.id,
        client_name=client.name,
        client_email=client.email,
        expires_in_hours=settings.portal_jwt_expire_hours,
    )


@router.post(
    "/request-link",
    response_model=MagicLinkRequestResponse,
    summary="Request a passwordless magic login link",
)
async def request_magic_link(
    body: MagicLinkRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a magic login link to the given email address.

    Always returns HTTP 200 with the same message — never reveals whether
    an account exists for this email (prevents enumeration attacks).

    Rate limited to 1 request per email per 5 minutes via Redis.
    The link expires in 15 minutes and is single-use.
    """
    settings = get_settings()
    await request_link(email=body.email, db=db, settings=settings)
    # Fire-and-forget: any failure is logged in the service — caller always sees 200.
    return MagicLinkRequestResponse()


@router.get(
    "/verify-link",
    summary="Verify a magic link token and issue a session JWT",
)
async def verify_magic_link(
    token: str = Query(..., description="Raw magic link token from the email URL"),
    db: AsyncSession = Depends(get_db),
):
    """
    Validate the raw token from the magic link email.

    On success:
    - Stamps the link as used (prevents replay).
    - Issues a portal JWT.
    - Returns TokenResponse JSON.
    - Optionally redirects to the portal frontend if PORTAL_FRONTEND_URL is set.

    On failure (expired, used, not found): returns HTTP 401.

    Note: this endpoint is called by the browser following the email link.
    The JWT is returned as JSON; the client-side portal app should pick it up
    from the URL fragment or response body and store it in memory (not localStorage).
    """
    settings = get_settings()
    client = await verify_link(raw_token=token, db=db)

    if client is None:
        logger.warning("portal.magic_link_verify_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This login link is invalid, expired, or has already been used. "
                   "Please request a new one.",
        )

    # Update last_login_at
    await db.execute(
        update(Client)
        .where(Client.id == client.id)
        .values(last_login_at=datetime.now(timezone.utc))
    )

    jwt_token = create_portal_token(client)

    await _log_audit(db, "portal.magic_link_login", client.id, success=True)
    logger.info("portal.magic_link_login_success", client_id=client.id)

    # If a frontend URL is configured, redirect with token in fragment
    # (fragments are not sent to the server — safe for token delivery)
    portal_frontend_url = getattr(settings, "portal_frontend_url", "")
    if portal_frontend_url:
        redirect_url = f"{portal_frontend_url.rstrip('/')}#token={jwt_token}"
        return RedirectResponse(url=redirect_url, status_code=302)

    # Fallback: return JSON (API clients / headless portal)
    return TokenResponse(
        access_token=jwt_token,
        client_id=client.id,
        client_name=client.name,
        client_email=client.email,
        expires_in_hours=settings.portal_jwt_expire_hours,
    )


@router.get(
    "/magic-link/peek",
    response_model=PeekResponse,
    summary="Peek at a magic-link token without consuming it",
)
async def peek_magic_link(
    token: str = Query(..., description="Raw magic link token from the email URL"),
    db: AsyncSession = Depends(get_db),
):
    """
    Non-destructive token validity check.

    Returns whether the token is valid (exists, not expired, not used) and a
    masked email hint so the SPA can show "Signing in as a*****@example.com".

    This endpoint is STRICTLY read-only — it never stamps used_at.
    Email security scanners (Gmail, Microsoft Defender) may pre-fetch GET URLs
    from incoming emails.  Because this endpoint only reads, a scanner hit is
    harmless — the token is not burned.

    Always returns HTTP 200 regardless of token state.  Returning 4xx would
    leak information about token existence to scanners and attackers.
    """
    result = await peek_link(raw_token=token, db=db)
    logger.info(
        "portal.magic_link_peek",
        valid=result["valid"],
        reason=result.get("reason"),
    )
    return PeekResponse(**result)


@router.post(
    "/magic-link/verify",
    response_model=TokenResponse,
    summary="Consume a magic-link token and issue a session JWT",
)
async def consume_magic_link(
    body: MagicLinkVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Consume a magic-link token and return a portal JWT.

    This is the token-burning step — used_at is stamped here.  Called only
    after the user explicitly clicks "Sign in" in the SPA, so email scanners
    (which only fire GET requests and do not execute JavaScript) cannot reach
    this endpoint.

    On success: returns TokenResponse with access_token, client details.
    On failure (expired, already used, not found): returns HTTP 401.
    """
    ip = request.client.host if request.client else None
    client = await verify_link(raw_token=body.token, db=db)

    if client is None:
        logger.warning("portal.magic_link_consume_failed", ip=ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This login link is invalid, expired, or has already been used. "
                   "Please request a new one.",
        )

    # Update last_login_at
    await db.execute(
        update(Client)
        .where(Client.id == client.id)
        .values(last_login_at=datetime.now(timezone.utc))
    )

    jwt_token = create_portal_token(client)
    settings = get_settings()

    await _log_audit(db, "portal.magic_link_login", client.id, ip=ip, success=True)
    logger.info("portal.magic_link_consume_success", client_id=client.id)

    return TokenResponse(
        access_token=jwt_token,
        client_id=client.id,
        client_name=client.name,
        client_email=client.email,
        expires_in_hours=settings.portal_jwt_expire_hours,
    )


@router.get("/me", response_model=MeResponse, summary="Get current client info")
async def me(
    client: Client = Depends(get_current_portal_client),
):
    """Return basic info about the authenticated client."""
    return MeResponse(
        id=client.id,
        name=client.name,
        email=client.email,
        company=client.company,
    )


@router.post("/logout", summary="Log out (client-side token invalidation)")
async def logout(
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Phase 1 logout — instructs the client to discard the JWT.

    JWTs are stateless; server-side invalidation requires a token denylist
    (Phase 2 enhancement using Redis). For now, the client deletes the token
    from localStorage on receipt of this response.
    """
    await _log_audit(db, "portal.logout", client.id, success=True)
    logger.info("portal.logout", client_id=client.id)
    return {"detail": "Logged out. Please discard your session token."}
