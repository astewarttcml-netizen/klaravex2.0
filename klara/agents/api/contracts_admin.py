"""
app/api/contracts_admin.py
───────────────────────────
phase17-004 — admin-side overview of contract approval requests.

  GET /api/v1/admin/contracts?status=<filter>    (X-API-Key)
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.approval import ApprovalRequest
from klara.rarv.lead import Lead

logger = structlog.get_logger(__name__)
router = APIRouter()


class ContractRow(BaseModel):
    id: str
    status: str
    lead_id: Optional[str]
    company: Optional[str]
    contact_email: Optional[str]
    created_at: datetime


@router.get("", response_model=List[ContractRow])
async def list_contracts(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> List[ContractRow]:
    q = select(ApprovalRequest).where(
        ApprovalRequest.action_name == "contract.send"
    )
    if status:
        q = q.where(ApprovalRequest.status == status)
    q = q.order_by(ApprovalRequest.created_at.desc()).limit(limit)

    rows = (await db.execute(q)).scalars().all()
    if not rows:
        return []

    lead_ids = list({r.lead_id for r in rows if r.lead_id})
    leads_by_id: dict[str, Lead] = {}
    if lead_ids:
        leads_q = await db.execute(select(Lead).where(Lead.id.in_(lead_ids)))
        leads_by_id = {l.id: l for l in leads_q.scalars()}

    return [
        ContractRow(
            id=r.id,
            status=r.status,
            lead_id=r.lead_id,
            company=leads_by_id.get(r.lead_id).company if leads_by_id.get(r.lead_id) else None,
            contact_email=leads_by_id.get(r.lead_id).email if leads_by_id.get(r.lead_id) else None,
            created_at=r.created_at,
        )
        for r in rows
    ]
