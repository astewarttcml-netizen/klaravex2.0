"""
app/api/gdpr_erase.py
──────────────────────
phase11-004 — GDPR right-to-erasure endpoint.

  POST /api/v1/admin/gdpr/erase  {email, requested_by, reason}

Hard-deletes or anonymises every row containing the subject's email
across all PII tables. Distinct from the phase8-005 SAR endpoint which
is read-only.

Strategy:
  - leads: anonymise (set name='[erased]', email=NULL, phone=NULL,
    status='anonymised', anonymised_at=now) — keeps lead row for FK
    integrity but strips all PII
  - prospected_leads: same anonymisation pattern
  - email_suppression_list: hard delete (no need to keep)
  - reply_classifications + reply_drafts: cascade via lead deletion
    not applicable (separate FK); hard delete those rows
  - audit_logs: do NOT delete — Art. 30 GDPR REQUIRES retention of
    processing records. Add an erasure-completion entry instead.

Every erasure is itself audit-logged for compliance.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.audit import AuditLog
from klara.rarv.email_suppression import EmailSuppression
from klara.rarv.lead import Lead, LeadStatus
from klara.rarv.prospected_lead import ProspectedLead
from klara.rarv.reply_classification import ReplyClassification
from klara.rarv.reply_draft import ReplyDraft

logger = structlog.get_logger(__name__)
router = APIRouter()


class EraseRequest(BaseModel):
    email: EmailStr
    requested_by: str
    reason: Optional[str] = None


class EraseResponse(BaseModel):
    email: str
    erased_at: datetime
    leads_anonymised: int
    prospects_anonymised: int
    reply_classifications_deleted: int
    reply_drafts_deleted: int
    suppression_entries_deleted: int


@router.post("", response_model=EraseResponse)
async def erase_subject(
    req: EraseRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> EraseResponse:
    target = req.email.lower()
    now = datetime.now(timezone.utc)

    # ── Leads — anonymise ────────────────────────────────────────────
    leads_q = await db.execute(
        select(Lead).where(Lead.email.ilike(target))
    )
    leads = list(leads_q.scalars().all())
    lead_ids = [l.id for l in leads]
    for l in leads:
        l.name = "[erased]"
        l.email = None
        l.phone = None
        l.message = None
        l.notes = None
        l.status = LeadStatus.anonymised.value
        l.anonymised_at = now

    # ── ProspectedLeads — anonymise ──────────────────────────────────
    prospects_q = await db.execute(
        select(ProspectedLead).where(ProspectedLead.contact_email.ilike(target))
    )
    prospects = list(prospects_q.scalars().all())
    prospect_ids = [p.id for p in prospects]
    for p in prospects:
        p.contact_first_name = "[erased]"
        p.contact_last_name = None
        p.contact_email = None
        p.contact_linkedin = None

    # ── ReplyClassification + ReplyDraft — hard delete ───────────────
    cls_deleted = 0
    drafts_deleted = 0
    if prospect_ids:
        cls_d = await db.execute(
            delete(ReplyClassification).where(
                ReplyClassification.prospected_lead_id.in_(prospect_ids)
            )
        )
        cls_deleted = cls_d.rowcount or 0

        drafts_d = await db.execute(
            delete(ReplyDraft).where(ReplyDraft.prospected_lead_id.in_(prospect_ids))
        )
        drafts_deleted = drafts_d.rowcount or 0

    # ── Suppression list — hard delete ───────────────────────────────
    supp_d = await db.execute(
        delete(EmailSuppression).where(EmailSuppression.email == target)
    )
    supp_deleted = supp_d.rowcount or 0

    # ── Audit trail (Art. 30 GDPR) ──────────────────────────────────
    audit = AuditLog(
        id=str(uuid4()),
        event_type="gdpr.erase_executed",
        action_name="erase_subject_data",
        details=json.dumps({
            "subject_email": target,
            "requested_by": req.requested_by,
            "reason": req.reason,
            "counts": {
                "leads_anonymised": len(leads),
                "prospects_anonymised": len(prospects),
                "reply_classifications_deleted": cls_deleted,
                "reply_drafts_deleted": drafts_deleted,
                "suppression_entries_deleted": supp_deleted,
            },
        }),
    )
    db.add(audit)
    await db.commit()

    logger.info(
        "gdpr.erase_executed",
        subject_email=target,
        requested_by=req.requested_by,
        leads=len(leads),
        prospects=len(prospects),
    )

    return EraseResponse(
        email=target,
        erased_at=now,
        leads_anonymised=len(leads),
        prospects_anonymised=len(prospects),
        reply_classifications_deleted=cls_deleted,
        reply_drafts_deleted=drafts_deleted,
        suppression_entries_deleted=supp_deleted,
    )
