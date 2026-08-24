"""
app/api/sales_division_admin.py
────────────────────────────────
Admin endpoints for the SalesDivisionAgent.

All routes require X-API-Key authentication.

POST /api/v1/admin/sales-division/run
    Trigger any sales division flow with a JSON body.

GET  /api/v1/admin/sales-division/triggers
    List all valid triggers and their required inputs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

import structlog

from app.core.portal_auth import require_admin
from app.agents.base import AgentContext
from app.agents.registry import registry
from app.config import get_settings
from app.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


class SalesDivisionRunRequest(BaseModel):
    trigger: str = Field(
        ...,
        description=(
            "Pipeline to execute. One of: inbound_lead | proposal_request | "
            "followup | reactivation | discovery_call_prep | cold_nurture"
        ),
        examples=["inbound_lead"],
    )
    lead_id: str | None = Field(None, description="Lead ID — required for most triggers")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional input passed directly to the agent",
    )
    request_id: str | None = Field(None, description="Idempotency / tracing key")


class DivisionRunResponse(BaseModel):
    success: bool
    trigger: str
    output: Any = None
    error: str | None = None
    approval_required: bool = False
    approval_id: str | None = None


@router.post(
    "/run",
    response_model=DivisionRunResponse,
    summary="Run a sales division pipeline",
)
async def run_sales_division(
    body: SalesDivisionRunRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """
    Trigger a sales division flow.  Returns immediately with the agent result.
    For flows that require human approval (P4 proposal requests), the response
    will have `approval_required=True` and an `approval_id`.
    """
    settings = get_settings()
    import uuid

    context = AgentContext(
        db=db,
        settings=settings,
        lead_id=body.lead_id,
        request_id=body.request_id or str(uuid.uuid4()),
    )

    agent = registry.get("sales_division")
    result = await agent(context, {"trigger": body.trigger, **body.payload, "lead_id": body.lead_id})

    logger.info(
        "sales_division_admin.run",
        trigger=body.trigger,
        lead_id=body.lead_id,
        success=result.success,
        approval_required=result.approval_required,
    )

    return DivisionRunResponse(
        success=result.success,
        trigger=body.trigger,
        output=result.output,
        error=result.error,
        approval_required=result.approval_required,
        approval_id=result.approval_id,
    )


@router.get(
    "/triggers",
    summary="List valid sales division triggers",
)
async def list_sales_triggers(_: str = Depends(require_admin)):
    """Return all supported triggers and their required/optional input fields."""
    return {
        "triggers": [
            {
                "trigger": "inbound_lead",
                "description": "Full qualification pipeline: qualify → score → route",
                "required": [],
                "optional": ["message", "name", "email", "company", "phone"],
            },
            {
                "trigger": "proposal_request",
                "description": "Direct proposal generation (P4 gate in production)",
                "required": ["lead_id"],
                "optional": ["justification", "services"],
            },
            {
                "trigger": "followup",
                "description": "Nurture sequence for existing warm leads",
                "required": ["lead_id"],
                "optional": [],
            },
            {
                "trigger": "reactivation",
                "description": "Re-engage cold/stale leads",
                "required": ["lead_id"],
                "optional": [],
            },
            {
                "trigger": "discovery_call_prep",
                "description": "Pre-call intelligence: enrichment + call prep briefing",
                "required": ["lead_id"],
                "optional": ["company", "services_interest"],
            },
            {
                "trigger": "cold_nurture",
                "description": "3-touch cold nurture sequence",
                "required": ["lead_id"],
                "optional": [],
            },
        ]
    }
