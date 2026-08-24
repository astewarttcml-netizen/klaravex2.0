"""
app/api/referrals_admin.py
───────────────────────────
phase18-003 — referral attribution admin endpoints.

  GET  /api/v1/admin/referrals       list all referrals
  POST /api/v1/admin/referrals       record a new referral
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.referral import Referral, ReferralSource

logger = structlog.get_logger(__name__)
router = APIRouter()


class ReferralCreate(BaseModel):
    referring_client_id: Optional[str] = None
    referring_lead_id: Optional[str] = None
    referred_lead_id: str
    source: str = ReferralSource.manual
    notes: Optional[str] = None


class ReferralRow(BaseModel):
    id: str
    referring_client_id: Optional[str]
    referring_lead_id: Optional[str]
    referred_lead_id: str
    source: str
    notes: Optional[str]
    created_at: datetime


@router.post("", response_model=ReferralRow, status_code=status.HTTP_201_CREATED)
async def create_referral(
    body: ReferralCreate,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> ReferralRow:
    # Idempotency: one referral per referred_lead_id (UNIQUE index)
    existing_q = await db.execute(
        select(Referral).where(Referral.referred_lead_id == body.referred_lead_id)
    )
    existing = existing_q.scalar_one_or_none()
    if existing is not None:
        return ReferralRow(
            id=existing.id,
            referring_client_id=existing.referring_client_id,
            referring_lead_id=existing.referring_lead_id,
            referred_lead_id=existing.referred_lead_id,
            source=existing.source,
            notes=existing.notes,
            created_at=existing.created_at,
        )

    row = Referral(
        id=str(uuid4()),
        referring_client_id=body.referring_client_id,
        referring_lead_id=body.referring_lead_id,
        referred_lead_id=body.referred_lead_id,
        source=body.source,
        notes=body.notes,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("referral.recorded", referred=body.referred_lead_id, source=body.source)
    return ReferralRow(
        id=row.id,
        referring_client_id=row.referring_client_id,
        referring_lead_id=row.referring_lead_id,
        referred_lead_id=row.referred_lead_id,
        source=row.source,
        notes=row.notes,
        created_at=row.created_at,
    )


@router.get("", response_model=List[ReferralRow])
async def list_referrals(
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> List[ReferralRow]:
    rows_q = await db.execute(
        select(Referral).order_by(Referral.created_at.desc()).limit(limit)
    )
    return [
        ReferralRow(
            id=r.id,
            referring_client_id=r.referring_client_id,
            referring_lead_id=r.referring_lead_id,
            referred_lead_id=r.referred_lead_id,
            source=r.source,
            notes=r.notes,
            created_at=r.created_at,
        )
        for r in rows_q.scalars().all()
    ]
