"""
app/api/inbox_admin.py
───────────────────────
phase19-004 — admin Inbox endpoint.

  GET /api/v1/admin/inbound-emails?category=&limit=&offset=

phase19-009 — surface matched_prospect_id / matched_prospect_company /
suppression_count by lower-case-joining InboundEmail.from_email to
ProspectedLead.contact_email at query time. No schema migration: the
existing `from_email` and `contact_email` columns are already indexed.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.inbound_email import InboundEmail
from klara.rarv.outreach_sequence import OutreachSequence, OutreachSequenceStatus
from klara.rarv.prospected_lead import ProspectedLead

logger = structlog.get_logger(__name__)
router = APIRouter()


class InboxItem(BaseModel):
    id: str
    from_email: str
    subject: Optional[str]
    category: Optional[str]
    confidence: Optional[float]
    summary: Optional[str]
    received_at: datetime
    lead_id: Optional[str]
    # phase19-009 — non-null only when from_email matches an existing
    # ProspectedLead.contact_email (case-insensitive).
    matched_prospect_id:      Optional[str] = None
    matched_prospect_company: Optional[str] = None
    # Count of OutreachSequence rows for that prospect that were
    # auto-suppressed by phase19-006 because the prospect replied. Zero
    # when matched_prospect_id is null or when no follow-ups were cancelled.
    suppression_count: int = 0


class InboxResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[InboxItem]


@router.get("", response_model=InboxResponse)
async def list_inbox(
    category: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> InboxResponse:
    # ── Correlated subqueries: matched prospect + suppression count ──
    matched_id_sq = (
        select(ProspectedLead.id)
        .where(
            func.lower(ProspectedLead.contact_email)
            == func.lower(InboundEmail.from_email)
        )
        .limit(1)
        .correlate(InboundEmail)
        .scalar_subquery()
    )
    matched_company_sq = (
        select(ProspectedLead.company_name)
        .where(
            func.lower(ProspectedLead.contact_email)
            == func.lower(InboundEmail.from_email)
        )
        .limit(1)
        .correlate(InboundEmail)
        .scalar_subquery()
    )
    # Count of suppressions where the prospect's id matches the resolved id.
    # Wrapping in select(...) so we can reuse matched_id_sq inside WHERE.
    suppression_count_sq = (
        select(func.count(OutreachSequence.id))
        .where(
            OutreachSequence.prospect_id == matched_id_sq,
            OutreachSequence.status == OutreachSequenceStatus.suppressed,
            OutreachSequence.suppress_reason == "inbound_reply",
        )
        .correlate(InboundEmail)
        .scalar_subquery()
    )

    base = select(
        InboundEmail,
        matched_id_sq.label("matched_prospect_id"),
        matched_company_sq.label("matched_prospect_company"),
        suppression_count_sq.label("suppression_count"),
    )
    count_base = select(func.count(InboundEmail.id))
    if category:
        base = base.where(InboundEmail.category == category)
        count_base = count_base.where(InboundEmail.category == category)

    total_q = await db.execute(count_base)
    total = int(total_q.scalar() or 0)

    rows_q = await db.execute(
        base.order_by(InboundEmail.received_at.desc()).offset(offset).limit(limit)
    )
    items: List[InboxItem] = []
    for row in rows_q.all():
        r = row[0]  # InboundEmail
        items.append(InboxItem(
            id=r.id, from_email=r.from_email, subject=r.subject,
            category=r.category, confidence=r.confidence, summary=r.summary,
            received_at=r.received_at, lead_id=r.lead_id,
            matched_prospect_id=row.matched_prospect_id,
            matched_prospect_company=row.matched_prospect_company,
            suppression_count=int(row.suppression_count or 0),
        ))
    return InboxResponse(total=total, limit=limit, offset=offset, items=items)
