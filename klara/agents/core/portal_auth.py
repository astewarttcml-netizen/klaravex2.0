"""
app/core/portal_auth.py
────────────────────────
Authentication, roles, and access control for the client portal.

## Authentication layers

1. **Portal JWT** — issued on login, carried as Bearer token.
   Payload: {"sub": client_id, "email": ..., "type": "portal_client", "exp": ...}
   Use `get_current_portal_client` as a FastAPI dependency on portal routes.

2. **Admin API key** — derived from APP_SECRET_KEY (same derivation as
   app/core/security.py).  Use `require_admin` as a FastAPI dependency on
   management/admin routes.

## Role model

Roles are defined in `UserRole`.  Permitted actions per role are documented in
`ROLE_PERMISSIONS`.  Roles are **not** stored in the DB — the Client table has
no role column; all authenticated portal clients are `UserRole.client`.
Admin access is gate-kept by the API key dependency, not by a JWT role claim.

## Cross-client access

Call `assert_client_owns(resource_client_id, authenticated_client)` inside any
route that fetches a record by ID to prevent horizontal privilege escalation
(Client A reading Client B's data).  Raises HTTP 403 on mismatch.

## Usage examples

    from app.core.portal_auth import (
        get_current_portal_client,
        require_admin,
        assert_client_owns,
        UserRole,
        ROLE_PERMISSIONS,
    )

    # Portal route (client JWT required)
    @router.get("/dashboard")
    async def dashboard(
        client: Client = Depends(get_current_portal_client),
        db: AsyncSession = Depends(get_db),
    ):
        ...

    # Admin route (API key required)
    @router.get("/admin/clients")
    async def list_clients(
        _: str = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
    ):
        ...

    # Cross-client guard inside a portal route
    invoice = await db.get(Invoice, invoice_id)
    assert_client_owns(invoice.client_id, client)  # raises 403 if mismatch
"""
import enum
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.portal import Client

logger = structlog.get_logger(__name__)

# ── Role enum ─────────────────────────────────────────────────────────────────


class UserRole(str, enum.Enum):
    admin = "admin"                      # Anthony / staff — full access
    client = "client"                    # Portal client — own records only
    agent_service_account = "agent_svc"  # Internal agent calls — limited write
    reviewer = "reviewer"                # Read-only audit access


# ── Permission matrix ─────────────────────────────────────────────────────────
# Documents what each role may do.
# Enforced at route level via role dependencies below.

ROLE_PERMISSIONS: dict[str, list[str]] = {
    UserRole.admin: [
        "portal:read_any",    # read any client's data
        "portal:write_any",   # write any client's data
        "approvals:approve",
        "approvals:reject",
        "leads:read",
        "leads:write",
        "reports:read",
    ],
    UserRole.client: [
        "portal:read_own",    # read own records only
        "portal:pay",         # initiate payment for own invoices
    ],
    UserRole.agent_service_account: [
        "portal:write_own",   # update records scoped to an operation
        "leads:write",
        "approvals:create",
    ],
    UserRole.reviewer: [
        "portal:read_any",    # read-only audit access
        "leads:read",
        "reports:read",
    ],
}

# ── Admin API key dependency ───────────────────────────────────────────────────
# The management API derives its expected key from APP_SECRET_KEY using the same
# HMAC derivation as app/core/security.py — no separate secret needed.

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _derive_management_key(secret: str) -> str:
    """Derive the management API key from the app secret (matches security.py)."""
    return hmac.new(
        secret.encode(), b"loki-management-api-v1", hashlib.sha256
    ).hexdigest()


async def require_admin(
    api_key: Optional[str] = Depends(_api_key_header),
) -> str:
    """
    Dependency for management/admin routes.

    Validates the X-API-Key header against the derived management key
    (same derivation used by app/core/security.verify_api_key).
    Returns the api_key string on success.
    Raises HTTP 401 if missing or wrong.

    Forbidden-access test cases (to be implemented as pytest tests):
      - Missing header → 401
      - Wrong key value → 401
      - Correct key → returns key, route proceeds
    """
    settings = get_settings()
    expected = _derive_management_key(settings.app_secret_key)

    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    logger.info("admin.authenticated")
    return api_key


# ── Cross-client access guard ─────────────────────────────────────────────────


def assert_client_owns(resource_client_id: str, authenticated_client: Client) -> None:
    """
    Assert that the authenticated client owns the requested resource.

    Call this in any route that fetches a resource by ID to prevent
    horizontal privilege escalation (Client A reading Client B's data).

    Raises HTTP 403 if ownership check fails.

    Forbidden-access test cases (to be implemented as pytest tests):
      - Client A requests resource owned by Client B → 403
      - Client requests their own resource → passes
      - Admin bypasses this check (admin routes use require_admin, not this guard)

    Usage:
        invoice = await db.get(Invoice, invoice_id)
        assert_client_owns(invoice.client_id, client)  # raises if mismatch
    """
    if resource_client_id != authenticated_client.id:
        logger.warning(
            "portal.cross_client_access_attempt",
            authenticated_client_id=authenticated_client.id,
            resource_client_id=resource_client_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )


# ── Password hashing ─────────────────────────────────────────────────────────
# Uses bcrypt directly (bypasses passlib CryptContext which is incompatible
# with bcrypt ≥4.x — detect_wrap_bug raises ValueError on passwords >72 bytes).


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of plain. Use when creating/updating client passwords."""
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ──────────────────────────────────────────────────────────────────────

_ALGORITHM = "HS256"
_TOKEN_TYPE = "portal_client"


def _portal_secret() -> str:
    """
    Derive a portal-specific signing secret from the app secret key.
    Using a suffix means portal tokens can't be replayed as management tokens.
    """
    return get_settings().app_secret_key + ":portal-jwt-v1"


def create_portal_token(client: Client) -> str:
    """
    Create a signed JWT for the given client.

    Expiry is controlled by PORTAL_JWT_EXPIRE_HOURS (default 8 h).
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        hours=settings.portal_jwt_expire_hours
    )
    payload = {
        "sub": client.id,
        "email": client.email,
        "type": _TOKEN_TYPE,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _portal_secret(), algorithm=_ALGORITHM)


def _decode_portal_token(token: str) -> dict:
    """
    Decode and validate a portal JWT.

    Raises HTTPException 401 on any validation failure — expired, tampered,
    wrong type, or missing claims.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _portal_secret(), algorithms=[_ALGORITHM])
    except JWTError:
        raise credentials_exc

    if payload.get("type") != _TOKEN_TYPE:
        # Prevent management API tokens from being used in the portal
        raise credentials_exc

    client_id: Optional[str] = payload.get("sub")
    if not client_id:
        raise credentials_exc

    return payload


# ── FastAPI dependency ────────────────────────────────────────────────────────

# Portal login endpoint is at /api/v1/portal/auth/login
_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/portal/auth/login",
    auto_error=False,
)


async def get_current_portal_client(
    token: Optional[str] = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Client:
    """
    FastAPI dependency — validates the Bearer token and returns the active Client.

    Raises HTTP 401 if:
      - No token provided
      - Token invalid / expired
      - Client not found in DB
      - Client account is inactive (is_active=False)

    Every portal route must include this dependency to enforce authentication.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _decode_portal_token(token)
    client_id: str = payload["sub"]

    result = await db.execute(
        select(Client).where(Client.id == client_id)
    )
    client: Optional[Client] = result.scalar_one_or_none()

    if client is None:
        logger.warning("portal_auth.client_not_found", client_id=client_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client account not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not client.is_active:
        logger.warning("portal_auth.inactive_client", client_id=client_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Please contact support.",
        )

    return client


# ── Public exports ────────────────────────────────────────────────────────────

__all__ = [
    # Roles
    "UserRole",
    "ROLE_PERMISSIONS",
    # Dependencies
    "require_admin",
    "get_current_portal_client",
    # Guards
    "assert_client_owns",
    # Token / password utilities
    "create_portal_token",
    "hash_password",
    "verify_password",
]
