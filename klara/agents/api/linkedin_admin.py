"""
app/api/linkedin_admin.py
──────────────────────────
phase20-003 — LinkedIn drafts admin endpoints.

  GET  /api/v1/admin/linkedin-drafts                    list pending drafts
  POST /api/v1/admin/linkedin-drafts/{id}/mark-sent     record that Anthony sent
  POST /api/v1/admin/linkedin-drafts/{id}/log-reply     record an incoming reply
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.linkedin_draft import LinkedinDraft, LinkedinDraftStatus
from app.models.prospected_lead import ProspectedLead

logger = structlog.get_logger(__name__)
router = APIRouter()


class DraftRow(BaseModel):
    id: str
    prospect_id: str
    company: Optional[str]
    contact_name: Optional[str]
    contact_linkedin: Optional[str]
    draft_body: str
    status: str
    created_at: datetime
    sent_at: Optional[datetime]
    replied_at: Optional[datetime]


class LogReplyRequest(BaseModel):
    reply_text: str = Field(min_length=1, max_length=5000)


@router.get("", response_model=List[DraftRow])
async def list_drafts(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> List[DraftRow]:
    base = select(LinkedinDraft).order_by(LinkedinDraft.created_at.desc()).limit(limit)
    if status:
        base = base.where(LinkedinDraft.status == status)

    drafts = list((await db.execute(base)).scalars().all())
    if not drafts:
        return []

    prospect_ids = list({d.prospected_lead_id for d in drafts})
    prospects_q = await db.execute(
        select(ProspectedLead).where(ProspectedLead.id.in_(prospect_ids))
    )
    by_id = {p.id: p for p in prospects_q.scalars()}

    return [
        DraftRow(
            id=d.id,
            prospect_id=d.prospected_lead_id,
            company=by_id.get(d.prospected_lead_id).company_name if by_id.get(d.prospected_lead_id) else None,
            contact_name=by_id.get(d.prospected_lead_id).contact_name if by_id.get(d.prospected_lead_id) else None,
            contact_linkedin=by_id.get(d.prospected_lead_id).contact_linkedin if by_id.get(d.prospected_lead_id) else None,
            draft_body=d.draft_body,
            status=d.status,
            created_at=d.created_at,
            sent_at=d.sent_at,
            replied_at=d.replied_at,
        )
        for d in drafts
    ]


@router.post("/{draft_id}/mark-sent", response_model=DraftRow)
async def mark_sent(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> DraftRow:
    q = await db.execute(select(LinkedinDraft).where(LinkedinDraft.id == draft_id))
    d = q.scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if d.status != LinkedinDraftStatus.sent:
        d.status = LinkedinDraftStatus.sent
        d.sent_at = datetime.now(timezone.utc)
        await db.commit()
    logger.info("linkedin_admin.marked_sent", draft_id=draft_id)
    return DraftRow(
        id=d.id, prospect_id=d.prospected_lead_id,
        company=None, contact_name=None, contact_linkedin=None,
        draft_body=d.draft_body, status=d.status,
        created_at=d.created_at, sent_at=d.sent_at, replied_at=d.replied_at,
    )


@router.post("/{draft_id}/log-reply", response_model=DraftRow)
async def log_reply(
    draft_id: str,
    body: LogReplyRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> DraftRow:
    q = await db.execute(select(LinkedinDraft).where(LinkedinDraft.id == draft_id))
    d = q.scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if d.status not in (LinkedinDraftStatus.sent, LinkedinDraftStatus.replied):
        raise HTTPException(status_code=400, detail="Cannot log reply on unsent draft")
    d.status = LinkedinDraftStatus.replied
    d.replied_at = datetime.now(timezone.utc)
    d.reply_text = body.reply_text[:5000]
    await db.commit()
    logger.info("linkedin_admin.logged_reply", draft_id=draft_id)
    return DraftRow(
        id=d.id, prospect_id=d.prospected_lead_id,
        company=None, contact_name=None, contact_linkedin=None,
        draft_body=d.draft_body, status=d.status,
        created_at=d.created_at, sent_at=d.sent_at, replied_at=d.replied_at,
    )
