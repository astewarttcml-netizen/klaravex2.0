"""
app/api/portal/nps_feedback.py
───────────────────────────────
phase14-004 — Net Promoter Score feedback endpoint.

  POST /api/v1/portal/feedback/nps   {score: 0-10, comment?: str}

Authenticated via portal_auth (client_id ownership). One client may
submit multiple times — each is stored as a new row (rolling sentiment).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_auth import get_current_portal_client
from app.database import get_db
from app.models.experiments import NpsResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


class NpsSubmission(BaseModel):
    score: int = Field(ge=0, le=10)
    comment: Optional[str] = Field(default=None, max_length=2000)


class NpsAck(BaseModel):
    id: str
    submitted_at: datetime
    score: int


@router.post("/nps", response_model=NpsAck)
async def submit_nps(
    body: NpsSubmission,
    client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
) -> NpsAck:
    row = NpsResponse(
        id=str(uuid4()),
        client_id=client.id if hasattr(client, "id") else None,
        score=body.score,
        comment=body.comment,
    )
    db.add(row)
    await db.commit()

    logger.info(
        "portal.nps_submitted",
        client_id=getattr(client, "id", None),
        score=body.score,
        has_comment=bool(body.comment),
    )

    # row.submitted_at is server_default — refresh to get the value back
    await db.refresh(row)
    return NpsAck(id=row.id, submitted_at=row.submitted_at, score=row.score)
