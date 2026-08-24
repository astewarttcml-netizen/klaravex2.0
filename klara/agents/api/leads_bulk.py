"""
app/api/leads_bulk.py
──────────────────────
phase15-005 — bulk lead annotation.

  POST /api/v1/admin/leads/bulk-annotate
  {"lead_ids": ["...", "..."], "note": "..."}

Appends a timestamped note to lead.notes for each lead in the list.
Idempotent: the same note (first 80 chars) is not appended twice for
the same lead. Returns count of updated leads.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)
router = APIRouter()


class BulkAnnotateRequest(BaseModel):
    lead_ids: List[str] = Field(min_length=1, max_length=500)
    note: str = Field(min_length=1, max_length=1000)


class BulkAnnotateResponse(BaseModel):
    updated: int
    skipped_already_annotated: int
    skipped_anonymised: int


@router.post("/bulk-annotate", response_model=BulkAnnotateResponse)
async def bulk_annotate(
    body: BulkAnnotateRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> BulkAnnotateResponse:
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
    new_note = f"\n[{timestamp}] {body.note.strip()}"
    dedup_key = body.note.strip()[:80]

    rows_q = await db.execute(
        select(Lead).where(Lead.id.in_(body.lead_ids))
    )
    leads = list(rows_q.scalars().all())

    updated = 0
    skipped_dup = 0
    skipped_anon = 0

    for lead in leads:
        if lead.status == LeadStatus.anonymised.value:
            skipped_anon += 1
            continue
        existing = lead.notes or ""
        if dedup_key in existing:
            skipped_dup += 1
            continue
        lead.notes = existing + new_note
        updated += 1

    if updated > 0:
        await db.commit()

    logger.info(
        "leads.bulk_annotate",
        requested=len(body.lead_ids),
        found=len(leads),
        updated=updated,
        skipped_dup=skipped_dup,
        skipped_anon=skipped_anon,
    )

    return BulkAnnotateResponse(
        updated=updated,
        skipped_already_annotated=skipped_dup,
        skipped_anonymised=skipped_anon,
    )
