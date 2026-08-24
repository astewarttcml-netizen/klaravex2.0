"""
app/api/suppression_admin.py
────────────────────────────
Admin endpoint for the email suppression list (phase4-005).

  GET /api/v1/admin/suppression-list           — paginated list, optional search

Requires X-API-Key.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.email_suppression import EmailSuppression

logger = structlog.get_logger(__name__)
router = APIRouter()


class SuppressionEntry(BaseModel):
    id: str
    email: str
    source: str
    reason: Optional[str]
    suppressed_at: datetime


class SuppressionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[SuppressionEntry]


@router.get("", response_model=SuppressionListResponse)
async def list_suppressed(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    search: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> SuppressionListResponse:
    base = select(EmailSuppression)
    count_base = select(func.count(EmailSuppression.id))

    if search:
        like = f"%{search.lower()}%"
        base = base.where(EmailSuppression.email.like(like))
        count_base = count_base.where(EmailSuppression.email.like(like))

    total_q = await db.execute(count_base)
    total = int(total_q.scalar() or 0)

    rows_q = await db.execute(
        base.order_by(EmailSuppression.suppressed_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
    )
    rows = list(rows_q.scalars().all())

    return SuppressionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[
            SuppressionEntry(
                id=r.id,
                email=r.email,
                source=r.source,
                reason=r.reason,
                suppressed_at=r.suppressed_at,
            )
            for r in rows
        ],
    )
