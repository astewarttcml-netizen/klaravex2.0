"""
app/api/portal/contracts.py
────────────────────────────
Client-facing contract endpoints (phase11-002).

GET /api/v1/portal/contracts          — list contracts for the current client
GET /api/v1/portal/contracts/{id}     — get one contract markdown body

Contracts in Klara AI are stored as the JSON payload of ApprovalRequest rows
with action_name='contract.send' (created by phase6-001's contract_trigger).
The payload carries the markdown and metadata we need.

Authorization: client_id ownership enforced via Lead.email matching the
authenticated portal client's email.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_auth import get_current_portal_client
from app.database import get_db
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.lead import Lead

logger = structlog.get_logger(__name__)
router = APIRouter()


class ContractSummary(BaseModel):
    id: str
    lead_id: str
    company: Optional[str]
    status: str
    created_at: datetime


class ContractDetail(ContractSummary):
    body_markdown: Optional[str]


@router.get("", response_model=List[ContractSummary])
async def list_contracts(
    client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
) -> List[ContractSummary]:
    """Return all contract approval requests linked to leads owned by the client."""
    # Find the client's leads (by email match)
    leads_q = await db.execute(
        select(Lead.id, Lead.company).where(Lead.email == client.email)
    )
    leads = list(leads_q.all())
    if not leads:
        return []

    lead_ids = [l[0] for l in leads]
    company_by_lead = {l[0]: l[1] for l in leads}

    approvals_q = await db.execute(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.action_name == "contract.send",
            ApprovalRequest.lead_id.in_(lead_ids),
        )
        .order_by(ApprovalRequest.created_at.desc())
    )
    out: List[ContractSummary] = []
    for a in approvals_q.scalars():
        out.append(ContractSummary(
            id=a.id,
            lead_id=a.lead_id or "",
            company=company_by_lead.get(a.lead_id) if a.lead_id else None,
            status=a.status,
            created_at=a.created_at,
        ))
    return out


@router.get("/{contract_id}", response_model=ContractDetail)
async def get_contract(
    contract_id: str,
    client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
) -> ContractDetail:
    a_q = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == contract_id,
            ApprovalRequest.action_name == "contract.send",
        )
    )
    a = a_q.scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Ownership: lead must belong to client
    if a.lead_id:
        lead_q = await db.execute(
            select(Lead).where(Lead.id == a.lead_id, Lead.email == client.email)
        )
        lead = lead_q.scalar_one_or_none()
        if lead is None:
            raise HTTPException(status_code=404, detail="Contract not found")
    else:
        raise HTTPException(status_code=404, detail="Contract not found")

    body = None
    try:
        payload = json.loads(a.payload) if a.payload else {}
        body = payload.get("body_markdown") or payload.get("contract_markdown")
    except Exception:
        body = None

    return ContractDetail(
        id=a.id,
        lead_id=a.lead_id or "",
        company=lead.company if lead else None,
        status=a.status,
        created_at=a.created_at,
        body_markdown=body,
    )
