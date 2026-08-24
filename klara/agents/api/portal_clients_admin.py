"""
app/api/portal_clients_admin.py
────────────────────────────────
Admin-only endpoints for managing portal client accounts (portal-311).

  GET    /api/v1/admin/portal/clients            — list all clients
  POST   /api/v1/admin/portal/clients            — create a new client
  GET    /api/v1/admin/portal/clients/{id}       — get one client
  PATCH  /api/v1/admin/portal/clients/{id}       — update name/email/company/notes/language/is_active
  POST   /api/v1/admin/portal/clients/{id}/reset-password — set a new password
  POST   /api/v1/admin/portal/clients/{id}/deactivate     — soft-disable account
  POST   /api/v1/admin/portal/clients/{id}/activate       — re-enable account

Design notes:
- hashed_password is NEVER returned in any response schema.
- Password hashing uses bcrypt directly (not passlib — incompatible with bcrypt ≥4.x).
- Email uniqueness conflicts return HTTP 409.
- All write operations log to structlog with agent="portal_clients_admin".
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import bcrypt
import structlog
from asyncpg import UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.portal import Client

logger = structlog.get_logger(__name__).bind(agent="portal_clients_admin")

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class ClientCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, description="Plain-text password — will be hashed before storage.")
    company: Optional[str] = Field(None, max_length=255)
    language_preference: str = Field("en", pattern="^(en|de)$")
    internal_notes: Optional[str] = None
    is_active: bool = True


class ClientPatchRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    company: Optional[str] = Field(None, max_length=255)
    language_preference: Optional[str] = Field(None, pattern="^(en|de)$")
    internal_notes: Optional[str] = None
    is_active: Optional[bool] = None


class ClientResetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8, description="New plain-text password — will be hashed before storage.")


class ClientAdminResponse(BaseModel):
    """Admin view of a client — hashed_password is intentionally absent."""
    id: str
    name: str
    email: str
    company: Optional[str]
    is_active: bool
    language_preference: str
    internal_notes: Optional[str]
    created_at: str
    updated_at: str
    last_login_at: Optional[str]


def _to_response(c: Client) -> ClientAdminResponse:
    return ClientAdminResponse(
        id=c.id,
        name=c.name,
        email=c.email,
        company=c.company,
        is_active=c.is_active,
        language_preference=c.language_preference,
        internal_notes=c.internal_notes,
        created_at=c.created_at.isoformat(),
        updated_at=c.updated_at.isoformat(),
        last_login_at=c.last_login_at.isoformat() if c.last_login_at else None,
    )


def _hash_password(plain: str) -> str:
    """Hash a plain-text password with bcrypt (direct — not passlib)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def _get_client_or_404(client_id: str, db: AsyncSession) -> Client:
    result = await db.execute(select(Client).where(Client.id == client_id))
    client: Client | None = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found.",
        )
    return client


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[ClientAdminResponse],
    dependencies=[Depends(verify_api_key)],
    summary="List all portal clients (admin)",
)
async def list_clients(
    is_active: Optional[bool] = Query(None, description="Filter by active status."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Client).order_by(Client.created_at.desc())
    if is_active is not None:
        query = query.where(Client.is_active == is_active)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.scalars().all()

    logger.info("admin.clients.listed", count=len(rows))
    return [_to_response(c) for c in rows]


@router.post(
    "",
    response_model=ClientAdminResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
    summary="Create a new portal client",
)
async def create_client(
    req: ClientCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a portal client account.  Password is hashed with bcrypt before storage.
    Returns HTTP 409 if the email address is already registered.
    """
    client = Client(
        name=req.name,
        email=req.email.lower(),
        hashed_password=_hash_password(req.password),
        company=req.company,
        language_preference=req.language_preference,
        internal_notes=req.internal_notes,
        is_active=req.is_active,
    )
    db.add(client)

    try:
        await db.commit()
        await db.refresh(client)
    except IntegrityError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower() or (
            exc.orig and "UniqueViolation" in type(exc.orig).__name__
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A client with email '{req.email}' already exists.",
            )
        raise

    logger.info(
        "admin.client.created",
        client_id=client.id,
        email=client.email,
        company=client.company,
    )
    return _to_response(client)


@router.get(
    "/{client_id}",
    response_model=ClientAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Get a single portal client",
)
async def get_client(
    client_id: str,
    db: AsyncSession = Depends(get_db),
):
    client = await _get_client_or_404(client_id, db)
    return _to_response(client)


@router.patch(
    "/{client_id}",
    response_model=ClientAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Update portal client details",
)
async def patch_client(
    client_id: str,
    req: ClientPatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Partial update.  Only supplied fields are changed.
    Email change is subject to uniqueness constraint (409 on collision).
    """
    client = await _get_client_or_404(client_id, db)

    updates: dict = req.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No fields provided for update.",
        )

    for field, value in updates.items():
        if field == "email" and value:
            value = value.lower()
        setattr(client, field, value)

    try:
        await db.commit()
        await db.refresh(client)
    except IntegrityError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower() or (
            exc.orig and "UniqueViolation" in type(exc.orig).__name__
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{req.email}' is already registered to another client.",
            )
        raise

    logger.info(
        "admin.client.updated",
        client_id=client_id,
        fields=list(updates.keys()),
    )
    return _to_response(client)


@router.post(
    "/{client_id}/reset-password",
    response_model=ClientAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Reset a client's portal password",
)
async def reset_client_password(
    client_id: str,
    req: ClientResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Set a new bcrypt-hashed password on the client account.
    The old password is not required — admin override.
    The plain-text password is never stored or logged.
    """
    client = await _get_client_or_404(client_id, db)
    client.hashed_password = _hash_password(req.password)

    await db.commit()
    await db.refresh(client)

    logger.info("admin.client.password_reset", client_id=client_id)
    return _to_response(client)


@router.post(
    "/{client_id}/deactivate",
    response_model=ClientAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Deactivate a portal client account",
)
async def deactivate_client(
    client_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Soft-disable the client account.  The JWT issued before deactivation will
    still technically be valid until expiry, but the portal auth middleware
    checks is_active on every request and rejects inactive accounts.
    """
    client = await _get_client_or_404(client_id, db)
    if not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client account is already inactive.",
        )

    client.is_active = False
    await db.commit()
    await db.refresh(client)

    logger.info("admin.client.deactivated", client_id=client_id)
    return _to_response(client)


@router.post(
    "/{client_id}/activate",
    response_model=ClientAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Activate (re-enable) a portal client account",
)
async def activate_client(
    client_id: str,
    db: AsyncSession = Depends(get_db),
):
    client = await _get_client_or_404(client_id, db)
    if client.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client account is already active.",
        )

    client.is_active = True
    await db.commit()
    await db.refresh(client)

    logger.info("admin.client.activated", client_id=client_id)
    return _to_response(client)
