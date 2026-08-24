"""
app/api/leads.py
────────────────
Lead management endpoints.

POST /api/v1/leads/           — create lead from contact form (public)
GET  /api/v1/leads/           — list leads (requires API key)
GET  /api/v1/leads/{id}       — get lead detail (requires API key)
PATCH /api/v1/leads/{id}      — update lead status/notes (requires API key)
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from klara.rarv.runtime import AgentContext
from app.agents.registry import registry
from klara.rarv.runtime import get_settings, Settings
from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.lead import Lead, LeadStatus
from klara.rarv.runtime.notifications import on_lead_created

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class LeadCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=50)
    company: Optional[str] = Field(None, max_length=255)
    message: str = Field(..., min_length=10, max_length=5000)
    services_interest: list[str] = Field(default_factory=list)
    budget_range: Optional[str] = None
    timeline: Optional[str] = None
    gdpr_consent: bool = Field(..., description="Must be true.")


class LeadResponse(BaseModel):
    id: str
    name: Optional[str]
    email: Optional[str]
    company: Optional[str]
    status: str
    score: Optional[float]
    source: str
    created_at: str

    class Config:
        from_attributes = True


class LeadUpdateRequest(BaseModel):
    status: Optional[LeadStatus] = None
    notes: Optional[str] = None
    score: Optional[float] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def create_lead(
    req: LeadCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Called by the WordPress contact form via REST.
    Runs the form pipeline: form_intake → qualify → score → route.
    """
    if not req.gdpr_consent:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="GDPR consent required.",
        )

    client_ip = request.client.host if request.client else None
    context = AgentContext(db=db, settings=settings)

    loki = registry.get("loki_orchestrator")
    result = await loki(
        context,
        {
            "pipeline": "form",
            "payload": {
                "session_token": f"form-{req.email}",
                "name": req.name,
                "email": str(req.email),
                "phone": req.phone,
                "company": req.company,
                "message": req.message,
                "services_interest": req.services_interest,
                "budget_range": req.budget_range,
                "timeline": req.timeline,
                "gdpr_consent": True,
                "gdpr_consent_ip": client_ip,
                "channel": "form",
            },
        },
    )

    # ── Transactional confirmation email (non-critical — does not raise) ──────
    if context.lead_id:
        from sqlalchemy import select as _select
        lead_row = await db.execute(_select(Lead).where(Lead.id == context.lead_id))
        lead_obj = lead_row.scalar_one_or_none()
        if lead_obj and lead_obj.status != "spam":
            await on_lead_created(settings, lead_obj)

    return {
        "status": "received",
        "message": "Thank you! We'll be in touch within one business day.",
        "lead_id": context.lead_id,
        "approval_required": result.approval_required,
    }


@router.get("/", dependencies=[Depends(verify_api_key)])
async def list_leads(
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List leads. Requires X-API-Key header. Internal use only."""
    query = select(Lead).order_by(Lead.created_at.desc()).limit(limit).offset(offset)
    if status_filter:
        query = query.where(Lead.status == status_filter)
    result = await db.execute(query)
    leads = result.scalars().all()
    return [
        {
            "id": l.id, "name": l.name, "email": l.email,
            "company": l.company, "status": l.status,
            "score": l.score, "source": l.source,
            "created_at": l.created_at.isoformat(),
        }
        for l in leads
    ]


@router.get("/{lead_id}", dependencies=[Depends(verify_api_key)])
async def get_lead(lead_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single lead. Requires X-API-Key header."""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    return {
        "id": lead.id, "name": lead.name, "email": lead.email,
        "phone": lead.phone, "company": lead.company,
        "message": lead.message, "status": lead.status,
        "score": lead.score, "score_reason": lead.score_reason,
        "services_interest": lead.services_interest,
        "budget_range": lead.budget_range, "timeline": lead.timeline,
        "source": lead.source, "gdpr_consent": lead.gdpr_consent,
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.updated_at.isoformat(),
    }


@router.patch("/{lead_id}", dependencies=[Depends(verify_api_key)])
async def update_lead(
    lead_id: str,
    req: LeadUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update lead status / notes. Requires X-API-Key header."""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    if req.status is not None:
        lead.status = req.status
    if req.notes is not None:
        lead.notes = req.notes
    if req.score is not None:
        lead.score = req.score

    return {"id": lead.id, "status": lead.status, "updated": True}
