"""
app/api/outreach_sequences_admin.py
────────────────────────────────────
Sequence-level approval admin endpoints (phase3-005).

  GET    /api/v1/admin/outreach-sequences            — list pending sequences
  GET    /api/v1/admin/outreach-sequences/{id}       — detail with prospect summary
  POST   /api/v1/admin/outreach-sequences/{id}/approve
  POST   /api/v1/admin/outreach-sequences/{id}/reject

Contract: one approval gates the entire sequence. When the operator clicks
"Approve sequence", we flip the parent ApprovalRequest to status="approved"
— the Day-3 follow-up Celery sweep then picks up every OutreachSequence row
that shares the approval_id and sends it. Rejection cancels every linked row.

All endpoints require X-API-Key. The dashboard sits behind Google OAuth
(/admin → oauth2-proxy) which is the operator-facing gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.approval import ApprovalRequest, ApprovalStatus
from klara.rarv.outreach_sequence import OutreachSequence, OutreachSequenceStatus
from klara.rarv.prospected_lead import ProspectedLead

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class SequenceSummary(BaseModel):
    sequence_id:     str
    prospect_id:     str
    approval_id:     Optional[str]
    step_number:     int
    status:          str
    scheduled_at:    Optional[datetime]
    sent_at:         Optional[datetime]
    company_name:    Optional[str]
    contact_email:   Optional[str]
    contact_first:   Optional[str]
    subject_en:      Optional[str]
    subject_de:      Optional[str]


class SequenceDetail(SequenceSummary):
    body_en:         Optional[str]
    body_de:         Optional[str]
    sibling_steps:   list[dict]   # other steps in the same sequence


class SequenceActionResponse(BaseModel):
    status:           str   # approved | rejected
    approval_id:      str
    affected_steps:   int   # number of OutreachSequence rows touched
    sequence_ids:     list[str]


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(verify_api_key)])
async def list_pending_sequences(
    status_filter: str = Query(
        default="pending_approval",
        alias="status",
        description="Filter by sequence status; default pending_approval",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[SequenceSummary]:
    """
    List sequences waiting for review. Returns the step row joined with a
    minimal prospect summary so the dashboard can render rows without
    follow-up requests.
    """
    rows = await db.execute(
        select(OutreachSequence, ProspectedLead)
        .outerjoin(ProspectedLead, ProspectedLead.id == OutreachSequence.prospect_id)
        .where(OutreachSequence.status == status_filter)
        .order_by(OutreachSequence.scheduled_at.desc())
        .limit(limit)
    )

    out: list[SequenceSummary] = []
    for seq, prospect in rows:
        out.append(SequenceSummary(
            sequence_id=seq.id,
            prospect_id=seq.prospect_id,
            approval_id=seq.approval_id,
            step_number=seq.step_number,
            status=seq.status,
            scheduled_at=seq.scheduled_at,
            sent_at=seq.sent_at,
            company_name=getattr(prospect, "company_name", None) if prospect else None,
            contact_email=getattr(prospect, "contact_email", None) if prospect else None,
            contact_first=getattr(prospect, "contact_first_name", None) if prospect else None,
            subject_en=seq.subject_en,
            subject_de=seq.subject_de,
        ))
    return out


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{sequence_id}", dependencies=[Depends(verify_api_key)])
async def get_sequence_detail(
    sequence_id: str,
    db: AsyncSession = Depends(get_db),
) -> SequenceDetail:
    seq_row = await db.execute(
        select(OutreachSequence).where(OutreachSequence.id == sequence_id)
    )
    seq = seq_row.scalar_one_or_none()
    if seq is None:
        raise HTTPException(status_code=404, detail="Sequence not found")

    prospect = None
    if seq.prospect_id:
        p_row = await db.execute(
            select(ProspectedLead).where(ProspectedLead.id == seq.prospect_id)
        )
        prospect = p_row.scalar_one_or_none()

    # Sibling steps in the same sequence (same approval_id)
    siblings: list[dict] = []
    if seq.approval_id:
        sib_rows = await db.execute(
            select(OutreachSequence).where(
                OutreachSequence.approval_id == seq.approval_id,
                OutreachSequence.id != seq.id,
            ).order_by(OutreachSequence.step_number)
        )
        for s in sib_rows.scalars():
            siblings.append({
                "sequence_id":  s.id,
                "step_number":  s.step_number,
                "status":       s.status,
                "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,
                "sent_at":      s.sent_at.isoformat() if s.sent_at else None,
                "subject_en":   s.subject_en,
            })

    return SequenceDetail(
        sequence_id=seq.id,
        prospect_id=seq.prospect_id,
        approval_id=seq.approval_id,
        step_number=seq.step_number,
        status=seq.status,
        scheduled_at=seq.scheduled_at,
        sent_at=seq.sent_at,
        company_name=getattr(prospect, "company_name", None) if prospect else None,
        contact_email=getattr(prospect, "contact_email", None) if prospect else None,
        contact_first=getattr(prospect, "contact_first_name", None) if prospect else None,
        subject_en=seq.subject_en,
        subject_de=seq.subject_de,
        body_en=seq.body_en,
        body_de=seq.body_de,
        sibling_steps=siblings,
    )


# ── Approve ───────────────────────────────────────────────────────────────────

@router.post("/{sequence_id}/approve", dependencies=[Depends(verify_api_key)])
async def approve_sequence(
    sequence_id: str,
    note: dict = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> SequenceActionResponse:
    """
    Approve the entire sequence. Flips the parent ApprovalRequest to
    'approved'. The Celery sweep picks up every OutreachSequence row
    that shares this approval_id and sends them.
    """
    seq = (await db.execute(
        select(OutreachSequence).where(OutreachSequence.id == sequence_id)
    )).scalar_one_or_none()
    if seq is None:
        raise HTTPException(status_code=404, detail="Sequence not found")
    if not seq.approval_id:
        raise HTTPException(status_code=409, detail="Sequence has no parent approval")

    approval = (await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == seq.approval_id)
    )).scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="ApprovalRequest not found")
    if approval.status != ApprovalStatus.pending.value:
        raise HTTPException(
            status_code=409,
            detail=f"Approval is already {approval.status!r}, cannot re-approve",
        )

    now = datetime.now(timezone.utc)
    approval.status      = ApprovalStatus.approved.value
    approval.reviewed_at = now
    approval.reviewed_by = note.get("reviewed_by", "admin")
    if note.get("note"):
        approval.review_note = note["note"][:5000]

    # Touch every sibling sequence row that shares this approval. The Celery
    # sweep will read approval.status='approved' and send each.
    affected = await db.execute(
        update(OutreachSequence)
        .where(
            OutreachSequence.approval_id == approval.id,
            OutreachSequence.status.in_([
                OutreachSequenceStatus.scheduled,
                OutreachSequenceStatus.pending_approval,
            ]),
        )
        .values(status=OutreachSequenceStatus.approved, updated_at=now)
        .returning(OutreachSequence.id)
    )
    sequence_ids = [row[0] for row in affected]
    await db.commit()

    logger.info(
        "outreach_sequences.approved",
        approval_id=approval.id,
        affected=len(sequence_ids),
    )
    return SequenceActionResponse(
        status="approved",
        approval_id=approval.id,
        affected_steps=len(sequence_ids),
        sequence_ids=sequence_ids,
    )


# ── Reject ────────────────────────────────────────────────────────────────────

@router.post("/{sequence_id}/reject", dependencies=[Depends(verify_api_key)])
async def reject_sequence(
    sequence_id: str,
    note: dict = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> SequenceActionResponse:
    """
    Reject the entire sequence. Flips the parent ApprovalRequest to
    'rejected' and marks every linked sequence row 'cancelled'.
    """
    seq = (await db.execute(
        select(OutreachSequence).where(OutreachSequence.id == sequence_id)
    )).scalar_one_or_none()
    if seq is None:
        raise HTTPException(status_code=404, detail="Sequence not found")
    if not seq.approval_id:
        raise HTTPException(status_code=409, detail="Sequence has no parent approval")

    approval = (await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == seq.approval_id)
    )).scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="ApprovalRequest not found")
    if approval.status != ApprovalStatus.pending.value:
        raise HTTPException(
            status_code=409,
            detail=f"Approval is already {approval.status!r}, cannot re-reject",
        )

    now = datetime.now(timezone.utc)
    approval.status      = ApprovalStatus.rejected.value
    approval.reviewed_at = now
    approval.reviewed_by = note.get("reviewed_by", "admin")
    if note.get("note"):
        approval.review_note = note["note"][:5000]

    affected = await db.execute(
        update(OutreachSequence)
        .where(
            OutreachSequence.approval_id == approval.id,
            OutreachSequence.status.in_([
                OutreachSequenceStatus.scheduled,
                OutreachSequenceStatus.pending_approval,
            ]),
        )
        .values(status=OutreachSequenceStatus.cancelled, updated_at=now)
        .returning(OutreachSequence.id)
    )
    sequence_ids = [row[0] for row in affected]
    await db.commit()

    logger.info(
        "outreach_sequences.rejected",
        approval_id=approval.id,
        affected=len(sequence_ids),
    )
    return SequenceActionResponse(
        status="rejected",
        approval_id=approval.id,
        affected_steps=len(sequence_ids),
        sequence_ids=sequence_ids,
    )
