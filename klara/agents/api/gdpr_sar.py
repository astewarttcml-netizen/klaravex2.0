"""
app/api/gdpr_sar.py
────────────────────
phase8-005 — GDPR Subject Access Request export endpoint.

  POST /api/v1/admin/gdpr/sar
       Body: { "email": "...", "requested_by": "operator@klaravex.de" }
       Returns a JSON dump of every row containing the email across all
       tables Klara AI holds personal data in.

Every SAR is audit-logged for compliance (Art. 30 GDPR — records of
processing activities). The endpoint is P3 — it returns personal data
and should be gated to operators only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.audit import AuditLog
from klara.rarv.email_suppression import EmailSuppression
from klara.rarv.lead import Lead
from klara.rarv.prospected_lead import ProspectedLead
from klara.rarv.proposal import Proposal
from klara.rarv.reply_classification import ReplyClassification
from klara.rarv.reply_draft import ReplyDraft

logger = structlog.get_logger(__name__)
router = APIRouter()


class SARRequest(BaseModel):
    email: EmailStr
    requested_by: str
    reason: Optional[str] = None


class SARResponse(BaseModel):
    email: str
    requested_at: datetime
    leads: list[dict]
    prospected_leads: list[dict]
    proposals: list[dict]
    reply_classifications: list[dict]
    reply_drafts: list[dict]
    suppressions: list[dict]


def _row_to_dict(row) -> dict:
    """Best-effort row → dict via SQLAlchemy column inspection.

    Avoids the ORM's __dict__ which includes internal SQLAlchemy state.
    """
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


@router.post("", response_model=SARResponse)
async def submit_sar(
    req: SARRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> SARResponse:
    target_email = req.email.lower()
    now = datetime.now(timezone.utc)

    # Leads — match on lowercased email
    leads_q = await db.execute(
        select(Lead).where(Lead.email.ilike(target_email))
    )
    leads = [_row_to_dict(r) for r in leads_q.scalars().all()]

    # ProspectedLeads
    prospects_q = await db.execute(
        select(ProspectedLead).where(ProspectedLead.contact_email.ilike(target_email))
    )
    prospects = [_row_to_dict(r) for r in prospects_q.scalars().all()]

    # Proposals — by linked lead_id
    lead_ids = [l["id"] for l in leads]
    proposals: list[dict] = []
    if lead_ids:
        proposals_q = await db.execute(
            select(Proposal).where(Proposal.lead_id.in_(lead_ids))
        )
        proposals = [_row_to_dict(r) for r in proposals_q.scalars().all()]

    # ReplyClassification + ReplyDraft — by ProspectedLead.id
    prospect_ids = [p["id"] for p in prospects]
    classifications: list[dict] = []
    drafts: list[dict] = []
    if prospect_ids:
        cls_q = await db.execute(
            select(ReplyClassification).where(
                ReplyClassification.prospected_lead_id.in_(prospect_ids)
            )
        )
        classifications = [_row_to_dict(r) for r in cls_q.scalars().all()]

        drafts_q = await db.execute(
            select(ReplyDraft).where(ReplyDraft.prospected_lead_id.in_(prospect_ids))
        )
        drafts = [_row_to_dict(r) for r in drafts_q.scalars().all()]

    # Suppression list
    supp_q = await db.execute(
        select(EmailSuppression).where(EmailSuppression.email == target_email)
    )
    suppressions = [_row_to_dict(r) for r in supp_q.scalars().all()]

    # Audit log
    audit = AuditLog(
        id=str(uuid4()),
        event_type="gdpr.sar_executed",
        action_name="export_subject_data",
        details=json.dumps({
            "subject_email": target_email,
            "requested_by": req.requested_by,
            "reason": req.reason,
            "rows_returned": {
                "leads": len(leads),
                "prospected_leads": len(prospects),
                "proposals": len(proposals),
                "reply_classifications": len(classifications),
                "reply_drafts": len(drafts),
                "suppressions": len(suppressions),
            },
        }),
    )
    db.add(audit)
    await db.commit()

    logger.info(
        "gdpr.sar_executed",
        subject_email=target_email,
        requested_by=req.requested_by,
        total_rows=len(leads) + len(prospects) + len(proposals)
                   + len(classifications) + len(drafts) + len(suppressions),
    )

    return SARResponse(
        email=target_email,
        requested_at=now,
        leads=_serialise(leads),
        prospected_leads=_serialise(prospects),
        proposals=_serialise(proposals),
        reply_classifications=_serialise(classifications),
        reply_drafts=_serialise(drafts),
        suppressions=_serialise(suppressions),
    )


def _serialise(rows: list[dict]) -> list[dict]:
    """JSON-friendly serialisation — coerces datetimes and UUIDs to strings."""
    out = []
    for r in rows:
        clean: dict = {}
        for k, v in r.items():
            if isinstance(v, datetime):
                clean[k] = v.isoformat()
            elif hasattr(v, "isoformat"):
                clean[k] = v.isoformat()
            elif hasattr(v, "value"):
                clean[k] = v.value
            else:
                clean[k] = v
        out.append(clean)
    return out
