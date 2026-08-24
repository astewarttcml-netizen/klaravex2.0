"""
app/api/engineering_division_admin.py
──────────────────────────────────────
Admin endpoints for the EngineeringDivisionAgent.

POST /api/v1/admin/engineering-division/run
    Trigger any engineering delivery flow with a JSON body.

GET  /api/v1/admin/engineering-division/triggers
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


class EngineeringDivisionRunRequest(BaseModel):
    trigger: str = Field(
        ...,
        description=(
            "Pipeline to execute. One of: client_onboarding | project_kickoff | "
            "network_monitor_setup | patch_report | security_scoping | "
            "kb_lookup | task_automation | post_call"
        ),
        examples=["client_onboarding"],
    )
    lead_id: str | None = Field(None, description="Lead/client ID")
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
    summary="Run an engineering division pipeline",
)
async def run_engineering_division(
    body: EngineeringDivisionRunRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """
    Trigger an engineering delivery flow.  Returns immediately with the agent result.
    Flows that touch external systems (network_monitor_setup, task_automation) may
    return `approval_required=True` with an `approval_id` in production.
    """
    settings = get_settings()
    import uuid

    context = AgentContext(
        db=db,
        settings=settings,
        lead_id=body.lead_id,
        request_id=body.request_id or str(uuid.uuid4()),
    )

    agent = registry.get("engineering_division")
    result = await agent(context, {"trigger": body.trigger, **body.payload, "lead_id": body.lead_id})

    logger.info(
        "engineering_division_admin.run",
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
    summary="List valid engineering division triggers",
)
async def list_engineering_triggers(_: str = Depends(require_admin)):
    """Return all supported triggers and their required/optional input fields."""
    return {
        "triggers": [
            {
                "trigger": "client_onboarding",
                "description": "Full onboarding: client_onboarding → project_kickoff → portal_notifier",
                "required": ["lead_id"],
                "optional": [],
            },
            {
                "trigger": "project_kickoff",
                "description": "Stand-alone project kickoff for already-onboarded clients",
                "required": ["lead_id"],
                "optional": ["project_name", "kickoff_date"],
            },
            {
                "trigger": "network_monitor_setup",
                "description": "Set up network monitoring for a client site (P3 approval)",
                "required": ["lead_id"],
                "optional": ["site_address", "device_count", "monitoring_type"],
            },
            {
                "trigger": "patch_report",
                "description": "Generate patch compliance report for a client environment",
                "required": [],
                "optional": ["lead_id", "environment", "report_period"],
            },
            {
                "trigger": "security_scoping",
                "description": "Security scope assessment",
                "required": [],
                "optional": ["lead_id", "scope_type", "environment_details"],
            },
            {
                "trigger": "kb_lookup",
                "description": "Knowledge base lookup (P1 — always available)",
                "required": ["query"],
                "optional": ["category"],
            },
            {
                "trigger": "task_automation",
                "description": "Delegate a structured IT task to TaskAutomatorAgent",
                "required": ["task_type"],
                "optional": ["task_payload", "lead_id"],
            },
            {
                "trigger": "post_call",
                "description": "Post-call processing — transcript analysis and CRM update",
                "required": ["call_transcript OR vapi_call_id"],
                "optional": ["lead_id", "call_outcome"],
            },
        ]
    }
