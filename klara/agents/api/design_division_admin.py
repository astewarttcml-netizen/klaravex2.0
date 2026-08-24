"""
app/api/design_division_admin.py
──────────────────────────────────
Admin endpoints for the DesignDivisionAgent.

POST /api/v1/admin/design-division/run
    Trigger any design/content flow with a JSON body.

GET  /api/v1/admin/design-division/triggers
    List all valid triggers and their required inputs.

Important: website_update and full_content_push will always return
approval_required=True in production, because WebsiteDeployAgent (P3)
never auto-publishes to WordPress.
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


class DesignDivisionRunRequest(BaseModel):
    trigger: str = Field(
        ...,
        description=(
            "Pipeline to execute. One of: seo_content_brief | social_post | "
            "website_update | translation_sync | full_content_push"
        ),
        examples=["seo_content_brief"],
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Trigger-specific input (see /triggers for details)",
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
    summary="Run a design division pipeline",
)
async def run_design_division(
    body: DesignDivisionRunRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """
    Trigger a design/content flow.

    Note on website_update / full_content_push:
    In production these always return approval_required=True because
    WebsiteDeployAgent never auto-publishes to WordPress.  The approval_id
    can be used with the /api/v1/approvals endpoint to approve publication.
    """
    settings = get_settings()
    import uuid

    context = AgentContext(
        db=db,
        settings=settings,
        request_id=body.request_id or str(uuid.uuid4()),
    )

    agent = registry.get("design_division")
    result = await agent(context, {"trigger": body.trigger, **body.payload})

    logger.info(
        "design_division_admin.run",
        trigger=body.trigger,
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
    summary="List valid design division triggers",
)
async def list_design_triggers(_: str = Depends(require_admin)):
    """Return all supported triggers and their required/optional input fields."""
    return {
        "triggers": [
            {
                "trigger": "seo_content_brief",
                "description": "Generate SEO content draft — stored in DB, not published automatically",
                "required": ["topic"],
                "optional": ["target_keyword", "language", "word_count", "meta_description"],
            },
            {
                "trigger": "social_post",
                "description": "Create and schedule a social media post (approval required)",
                "required": ["content OR topic"],
                "optional": ["platform", "scheduled_at", "image_url"],
            },
            {
                "trigger": "website_update",
                "description": "Push content to WordPress as a DRAFT (P3 approval required — never auto-publishes)",
                "required": ["page_slug OR page_id", "content"],
                "optional": ["title", "meta_description", "language"],
            },
            {
                "trigger": "translation_sync",
                "description": "Scan /de/ pages for untranslated English blocks. Read-only.",
                "required": [],
                "optional": [],
            },
            {
                "trigger": "full_content_push",
                "description": (
                    "End-to-end: SEO content → social post → WP draft. "
                    "Website step queues for P3 approval in production."
                ),
                "required": ["topic"],
                "optional": ["target_keyword", "language", "platform", "page_slug"],
            },
        ]
    }
