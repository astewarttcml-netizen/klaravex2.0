"""
app/api/website_deploy_admin.py
────────────────────────────────
Admin endpoints for the WebsiteDeployAgent (P3).

All endpoints require X-API-Key authentication.

Routes (mounted under /api/v1/admin/website-deploy):

  POST /queue
      Queue a new page content update job.
      Creates a WebsiteDeployJob with status=PENDING.
      Returns job_id and approval_required=True.
      The actual WP write is NOT performed — a human must call /approve/{job_id}.

  GET /jobs
      List all deploy jobs, optionally filtered by status.

  POST /approve/{job_id}
      Approve and immediately execute a PENDING job.
      Calls WebsiteDeployAgent with action='execute'.
      Returns the WP API result.

  POST /flush-rewrites
      Flush WordPress rewrite rules by submitting the permalink settings form
      via cookie-based session auth.  Equivalent to visiting wp-admin →
      Settings → Permalinks → Save Changes.  Non-destructive, no approval gate.
      Use after renaming page slugs to clear the stale rewrite_rules cache.

Safety invariants enforced here:
  - The approve endpoint will refuse to execute a job that is not PENDING.
  - The agent itself double-checks status before calling WP.
  - The agent NEVER sets status: publish — always draft.
"""
from __future__ import annotations

from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import AgentContext
from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.website_deploy import DeployJobStatus, WebsiteDeployJob

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class QueueJobRequest(BaseModel):
    page_id: int = Field(..., description="WordPress page ID (integer, not slug).")
    page_title: str = Field(..., min_length=1, max_length=500, description="Human-readable page title for the audit trail.")
    new_content: str = Field(..., min_length=1, description="Full HTML/block content to write to the WP page as a draft.")
    queued_by: str = Field(default="api", max_length=255, description="Who is requesting this change (username, email, or system identifier).")


class QueueJobResponse(BaseModel):
    job_id: str
    page_id: int
    page_title: str
    status: str
    approval_required: bool
    message: str


class JobListItem(BaseModel):
    job_id: str
    page_id: int
    page_title: str
    status: str
    queued_by: str
    queued_at: str
    approved_at: Optional[str]
    executed_at: Optional[str]
    error_message: Optional[str]


class JobListResponse(BaseModel):
    count: int
    items: list[JobListItem]


class ApproveJobResponse(BaseModel):
    job_id: str
    page_id: int
    page_title: str
    status: str
    wp_draft_id: Optional[int]
    executed_at: Optional[str]
    error: Optional[str]


class FlushRewritesResponse(BaseModel):
    flushed: bool
    permalink_structure: str
    message: str


# ── 1. Queue a job ────────────────────────────────────────────────────────────

@router.post(
    "/queue",
    dependencies=[Depends(verify_api_key)],
    response_model=QueueJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a WordPress page content update (requires approval before execution)",
)
async def queue_deploy_job(
    payload: QueueJobRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Queue a new page content update job.

    The job is stored with status=PENDING.  The WP REST API is NOT called yet.
    A human operator must call POST /approve/{job_id} to execute the write.

    Returns 202 Accepted with the job_id and approval_required=True.
    """
    from app.agents.registry import registry
    from klara.rarv.runtime import get_settings

    settings = get_settings()
    agent = registry.get("website_deploy")
    request_id = str(uuid4())

    context = AgentContext(
        db=db,
        settings=settings,
        request_id=request_id,
    )

    log = logger.bind(
        endpoint="website_deploy.queue",
        page_id=payload.page_id,
        queued_by=payload.queued_by,
        request_id=request_id,
    )
    log.info("website_deploy_admin.queue_received")

    result = await agent(
        context,
        {
            "action": "queue",
            "page_id": payload.page_id,
            "page_title": payload.page_title,
            "new_content": payload.new_content,
            "queued_by": payload.queued_by,
        },
    )

    if not result.approval_required and not result.success:
        log.error("website_deploy_admin.queue_failed", error=result.error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "Failed to queue deploy job.",
        )

    job_id = result.approval_id
    log.info("website_deploy_admin.queue_ok", job_id=job_id)

    return QueueJobResponse(
        job_id=job_id,
        page_id=payload.page_id,
        page_title=payload.page_title,
        status=DeployJobStatus.PENDING,
        approval_required=True,
        message=(
            f"Job {job_id} queued. Human approval required before the WP page will be updated. "
            f"Call POST /api/v1/admin/website-deploy/approve/{job_id} to execute."
        ),
    )


# ── 2. List all jobs ──────────────────────────────────────────────────────────

@router.get(
    "/jobs",
    dependencies=[Depends(verify_api_key)],
    response_model=JobListResponse,
    summary="List website deploy jobs with optional status filter",
)
async def list_deploy_jobs(
    job_status: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by job status: PENDING, APPROVED, EXECUTING, COMPLETED, FAILED",
    ),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """
    List all website deploy jobs, newest-first.
    Optionally filter by status.
    """
    stmt = select(WebsiteDeployJob).order_by(WebsiteDeployJob.queued_at.desc())

    if job_status:
        valid_statuses = {s.value for s in DeployJobStatus}
        if job_status.upper() not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid status '{job_status}'. Valid values: {', '.join(sorted(valid_statuses))}",
            )
        stmt = stmt.where(WebsiteDeployJob.status == job_status.upper())

    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    items = [
        JobListItem(
            job_id=j.id,
            page_id=j.page_id,
            page_title=j.page_title,
            status=j.status,
            queued_by=j.queued_by,
            queued_at=j.queued_at.isoformat(),
            approved_at=j.approved_at.isoformat() if j.approved_at else None,
            executed_at=j.executed_at.isoformat() if j.executed_at else None,
            error_message=j.error_message,
        )
        for j in jobs
    ]

    return JobListResponse(count=len(items), items=items)


# ── 3. Approve and execute a job ──────────────────────────────────────────────

@router.post(
    "/approve/{job_id}",
    dependencies=[Depends(verify_api_key)],
    response_model=ApproveJobResponse,
    summary="Approve and execute a pending deploy job (triggers WP REST API write)",
)
async def approve_deploy_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Approve a PENDING deploy job and immediately execute it.

    This is the P3 approval gate.  When you call this endpoint:
      1. The agent fetches the job from the DB.
      2. Status transitions: PENDING → APPROVED → EXECUTING → COMPLETED | FAILED
      3. WP REST API PATCH is called with status=draft (NEVER publish).
      4. The result is logged to audit_logger.

    Returns 200 with job status and WP draft ID on success.
    Returns 422 if the job is not in PENDING status.
    Returns 500 if the WP API call fails (job is marked FAILED in DB).
    """
    from app.agents.registry import registry
    from klara.rarv.runtime import get_settings

    settings = get_settings()
    request_id = str(uuid4())

    log = logger.bind(
        endpoint="website_deploy.approve",
        job_id=job_id,
        request_id=request_id,
    )

    # Pre-flight: confirm the job exists and is PENDING before invoking the agent
    stmt = select(WebsiteDeployJob).where(WebsiteDeployJob.id == job_id)
    result = await db.execute(stmt)
    job: WebsiteDeployJob | None = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deploy job '{job_id}' not found.",
        )

    if job.status not in (DeployJobStatus.PENDING, DeployJobStatus.APPROVED):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Job '{job_id}' has status '{job.status}'. "
                f"Only PENDING or APPROVED jobs can be executed."
            ),
        )

    log.info(
        "website_deploy_admin.approve_triggered",
        page_id=job.page_id,
        page_title=job.page_title,
        queued_by=job.queued_by,
    )

    agent = registry.get("website_deploy")
    context = AgentContext(
        db=db,
        settings=settings,
        request_id=request_id,
    )

    agent_result = await agent(
        context,
        {
            "action": "execute",
            "job_id": job_id,
        },
    )

    if agent_result.success:
        out = agent_result.output or {}
        return ApproveJobResponse(
            job_id=job_id,
            page_id=out.get("page_id", job.page_id),
            page_title=out.get("page_title", job.page_title),
            status=out.get("status", DeployJobStatus.COMPLETED),
            wp_draft_id=out.get("wp_draft_id"),
            executed_at=out.get("executed_at"),
            error=None,
        )
    else:
        log.error(
            "website_deploy_admin.approve_failed",
            error=agent_result.error,
            job_id=job_id,
        )
        # Job is now FAILED in the DB — return 500 so caller knows to investigate
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=agent_result.error or "WP API call failed. Job marked FAILED.",
        )


# ── 4. Flush WordPress rewrite rules ─────────────────────────────────────────

@router.post(
    "/flush-rewrites",
    dependencies=[Depends(verify_api_key)],
    response_model=FlushRewritesResponse,
    summary="Flush WordPress rewrite rules (equivalent to Permalinks → Save Changes)",
)
async def flush_rewrite_rules(
    db: AsyncSession = Depends(get_db),
):
    """
    Flush WordPress rewrite rules by submitting the permalink settings form
    via an authenticated browser-session-equivalent HTTP flow.

    This resolves 404 errors that appear after renaming page slugs via the
    WP REST API.  WordPress caches compiled rewrite rules in the database;
    calling this endpoint clears that cache without changing any settings.

    No approval gate — this operation is non-destructive and idempotent.

    Returns 200 with flushed=True on success.
    Returns 500 with an error detail if the WP auth or form submission fails.
    """
    from app.agents.registry import registry
    from klara.rarv.runtime import get_settings

    settings = get_settings()
    agent = registry.get("website_deploy")
    request_id = str(uuid4())

    log = logger.bind(
        endpoint="website_deploy.flush_rewrites",
        request_id=request_id,
    )
    log.info("website_deploy_admin.flush_rewrites_triggered")

    context = AgentContext(
        db=db,
        settings=settings,
        request_id=request_id,
    )

    result = await agent(context, {"action": "flush_rewrites"})

    if result.success:
        out = result.output or {}
        log.info("website_deploy_admin.flush_rewrites_ok")
        return FlushRewritesResponse(
            flushed=out.get("flushed", True),
            permalink_structure=out.get("permalink_structure", ""),
            message=out.get("message", "WordPress rewrite rules flushed successfully."),
        )
    else:
        log.error("website_deploy_admin.flush_rewrites_failed", error=result.error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "Failed to flush WordPress rewrite rules.",
        )
