"""
app/api/portal/dashboard.py
────────────────────────────
Client dashboard summary endpoint.

GET /api/v1/portal/dashboard

Returns a single response containing:
  - Client info
  - Active projects (non-complete)
  - Outstanding invoices (unpaid/overdue)
  - Recent files (last 5)

Everything is scoped to the authenticated client — no cross-client leakage.
"""
from decimal import Decimal
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_auth import get_current_portal_client
from klara.rarv.runtime import get_db
from klara.rarv.portal import (
    Client,
    ClientFile,
    Invoice,
    InvoiceStatus,
    Project,
    ProjectStatus,
    PROJECT_STATUS_LABELS,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class ProjectSummary(BaseModel):
    id: str
    title: str
    status: str
    status_label: str
    status_description: str
    next_action: Optional[str]
    latest_update: Optional[str]


class InvoiceSummary(BaseModel):
    id: str
    reference: str
    amount: Decimal
    currency: str
    status: str
    due_date: Optional[str]
    has_payment_link: bool


class FileSummary(BaseModel):
    id: str
    title: str
    description: Optional[str]
    project_id: Optional[str]
    uploaded_at: str


class DashboardResponse(BaseModel):
    client_name: str
    client_company: Optional[str]
    active_projects: List[ProjectSummary]
    outstanding_invoices: List[InvoiceSummary]
    recent_files: List[FileSummary]
    has_outstanding_payment: bool
    has_action_needed: bool  # True if any project is "waiting_on_client"


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("", response_model=DashboardResponse, summary="Client dashboard summary")
async def get_dashboard(
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a complete dashboard summary for the authenticated client.

    Active projects = all non-complete projects.
    Outstanding invoices = unpaid + overdue invoices.
    Recent files = last 5 uploaded, newest first.
    """
    # ── Active projects ───────────────────────────────────────────────────────
    proj_result = await db.execute(
        select(Project)
        .where(
            Project.client_id == client.id,
            Project.status != ProjectStatus.complete,
        )
        .order_by(Project.updated_at.desc())
    )
    projects = proj_result.scalars().all()

    active_projects = [
        ProjectSummary(
            id=p.id,
            title=p.title,
            status=p.status,
            status_label=PROJECT_STATUS_LABELS[ProjectStatus(p.status)]["label"],
            status_description=PROJECT_STATUS_LABELS[ProjectStatus(p.status)]["description"],
            next_action=p.next_action,
            latest_update=p.latest_update,
        )
        for p in projects
    ]

    # ── Outstanding invoices ──────────────────────────────────────────────────
    inv_result = await db.execute(
        select(Invoice)
        .where(
            Invoice.client_id == client.id,
            Invoice.status.in_([InvoiceStatus.unpaid, InvoiceStatus.overdue, InvoiceStatus.sent]),
        )
        .order_by(Invoice.due_date.asc().nullslast())
    )
    invoices = inv_result.scalars().all()

    outstanding_invoices = [
        InvoiceSummary(
            id=inv.id,
            reference=inv.reference,
            amount=inv.amount,
            currency=inv.currency,
            status=inv.status,
            due_date=inv.due_date.isoformat() if inv.due_date else None,
            has_payment_link=bool(inv.payment_link),
        )
        for inv in invoices
    ]

    # ── Recent files ──────────────────────────────────────────────────────────
    file_result = await db.execute(
        select(ClientFile)
        .where(ClientFile.client_id == client.id)
        .order_by(ClientFile.uploaded_at.desc())
        .limit(5)
    )
    files = file_result.scalars().all()

    recent_files = [
        FileSummary(
            id=f.id,
            title=f.title,
            description=f.description,
            project_id=f.project_id,
            uploaded_at=f.uploaded_at.isoformat(),
        )
        for f in files
    ]

    # ── Derived flags ─────────────────────────────────────────────────────────
    has_outstanding_payment = len(outstanding_invoices) > 0
    has_action_needed = any(
        p.status == ProjectStatus.waiting_on_client for p in projects
    )

    logger.info(
        "portal.dashboard_viewed",
        client_id=client.id,
        projects=len(active_projects),
        invoices=len(outstanding_invoices),
    )

    return DashboardResponse(
        client_name=client.name,
        client_company=client.company,
        active_projects=active_projects,
        outstanding_invoices=outstanding_invoices,
        recent_files=recent_files,
        has_outstanding_payment=has_outstanding_payment,
        has_action_needed=has_action_needed,
    )
