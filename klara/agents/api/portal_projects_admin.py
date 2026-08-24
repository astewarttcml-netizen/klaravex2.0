"""
app/api/portal_projects_admin.py
─────────────────────────────────
Admin-only endpoints for portal projects and their status event log (portal-312).

Projects
  GET    /api/v1/admin/portal/projects                   — list projects (filterable)
  POST   /api/v1/admin/portal/projects                   — create a project
  GET    /api/v1/admin/portal/projects/{id}              — get one project
  PATCH  /api/v1/admin/portal/projects/{id}              — update project fields

Status events  (INSERT-only — events are never patched or deleted)
  GET    /api/v1/admin/portal/projects/{id}/events       — list events for a project
  POST   /api/v1/admin/portal/projects/{id}/events       — record a stage transition

Design notes:
- Project.status is kept in sync with the new_stage of any recorded event.
  Callers must use the events endpoint to advance status — direct PATCH on
  status is intentionally excluded so there is always an audit trail.
- ALLOWED_TRANSITIONS is enforced: a 422 is returned for invalid progressions.
  The `force` query parameter bypasses the whitelist (admin override).
- ProjectStatusEvent rows are INSERT-only — no PATCH/DELETE endpoints exposed.
"""
from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.portal import Client, Project, ProjectStatus
from klara.rarv.project_event import (
    ALLOWED_TRANSITIONS,
    VALID_STAGES,
    ActorType,
    ProjectStatusEvent,
)

logger = structlog.get_logger(__name__).bind(agent="portal_projects_admin")

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProjectCreateRequest(BaseModel):
    client_id: str = Field(..., description="UUID of the portal client that owns this project.")
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    next_action: Optional[str] = Field(None, description="Client-facing plain-English next step.")
    latest_update: Optional[str] = Field(None, description="Client-facing summary of recent work.")
    # Initial status defaults to new_request; use events to advance it.
    initial_status: str = Field(
        ProjectStatus.new_request.value,
        description="Starting status. Defaults to new_request.",
    )


class ProjectPatchRequest(BaseModel):
    """
    Mutable project fields that don't require an audit trail.
    Use the /events endpoint to change project status.
    """
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    next_action: Optional[str] = None
    latest_update: Optional[str] = None


class ProjectAdminResponse(BaseModel):
    id: str
    client_id: str
    title: str
    description: Optional[str]
    status: str
    next_action: Optional[str]
    latest_update: Optional[str]
    created_at: str
    updated_at: str


class ProjectEventCreateRequest(BaseModel):
    new_stage: str = Field(
        ...,
        description=(
            "Target stage. Must be reachable from the current stage via "
            "ALLOWED_TRANSITIONS unless `force=true`."
        ),
    )
    actor_type: str = Field(
        ActorType.admin.value,
        description="system | admin | agent",
    )
    actor_id: Optional[str] = Field(
        None,
        max_length=255,
        description="Identifier of the actor (agent name, admin user id, etc.).",
    )
    note: Optional[str] = Field(
        None,
        description="Human-readable reason or context for the transition (shown in admin view).",
    )
    client_visible: bool = Field(
        True,
        description="Whether this event appears in the client-facing timeline.",
    )


class ProjectEventResponse(BaseModel):
    id: str
    project_id: str
    client_id: str
    old_stage: Optional[str]
    new_stage: str
    actor_type: str
    actor_id: Optional[str]
    note: Optional[str]
    client_visible: bool
    recorded_at: str


def _project_to_response(p: Project) -> ProjectAdminResponse:
    return ProjectAdminResponse(
        id=p.id,
        client_id=p.client_id,
        title=p.title,
        description=p.description,
        status=p.status,
        next_action=p.next_action,
        latest_update=p.latest_update,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )


def _event_to_response(e: ProjectStatusEvent) -> ProjectEventResponse:
    return ProjectEventResponse(
        id=e.id,
        project_id=e.project_id,
        client_id=e.client_id,
        old_stage=e.old_stage,
        new_stage=e.new_stage,
        actor_type=e.actor_type,
        actor_id=e.actor_id,
        note=e.note,
        client_visible=e.client_visible,
        recorded_at=e.recorded_at.isoformat(),
    )


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project: Project | None = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    return project


# ── Project endpoints ─────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[ProjectAdminResponse],
    dependencies=[Depends(verify_api_key)],
    summary="List portal projects (admin, filterable by client/status)",
)
async def list_projects(
    client_id: Optional[str] = Query(None, description="Filter by client UUID."),
    project_status: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by ProjectStatus value.",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    if project_status and project_status not in VALID_STAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid status '{project_status}'. Allowed: {sorted(VALID_STAGES)}",
        )

    query = select(Project).order_by(Project.created_at.desc())
    if client_id:
        query = query.where(Project.client_id == client_id)
    if project_status:
        query = query.where(Project.status == project_status)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.scalars().all()

    logger.info("admin.projects.listed", count=len(rows))
    return [_project_to_response(p) for p in rows]


@router.post(
    "",
    response_model=ProjectAdminResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
    summary="Create a portal project",
)
async def create_project(
    req: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new portal project for a client.

    Also inserts the initial ProjectStatusEvent (actor_type=admin, client_visible=False)
    so there is always a complete event log from project creation.
    """
    # Validate client exists
    client_result = await db.execute(select(Client).where(Client.id == req.client_id))
    if client_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{req.client_id}' not found.",
        )

    # Validate initial status
    if req.initial_status not in VALID_STAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid initial_status '{req.initial_status}'. Allowed: {sorted(VALID_STAGES)}",
        )

    project = Project(
        client_id=req.client_id,
        title=req.title,
        description=req.description,
        status=req.initial_status,
        next_action=req.next_action,
        latest_update=req.latest_update,
    )
    db.add(project)
    await db.flush()  # get project.id before creating the event

    # Creation event — not client-visible (admin housekeeping)
    creation_event = ProjectStatusEvent(
        project_id=project.id,
        client_id=req.client_id,
        old_stage=None,
        new_stage=req.initial_status,
        actor_type=ActorType.admin.value,
        actor_id="admin",
        note="Project created.",
        client_visible=False,
    )
    db.add(creation_event)

    await db.commit()
    await db.refresh(project)

    logger.info(
        "admin.project.created",
        project_id=project.id,
        client_id=req.client_id,
        status=req.initial_status,
    )
    return _project_to_response(project)


@router.get(
    "/{project_id}",
    response_model=ProjectAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Get a single portal project",
)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project_or_404(project_id, db)
    return _project_to_response(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Update portal project fields (title, description, next_action, latest_update)",
)
async def patch_project(
    project_id: str,
    req: ProjectPatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Update mutable descriptive fields on a project.

    To change the project's status use POST /{id}/events — this produces
    an audit trail entry and keeps Project.status in sync atomically.
    """
    project = await _get_project_or_404(project_id, db)

    updates = req.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No fields provided for update.",
        )

    for field, value in updates.items():
        setattr(project, field, value)

    await db.commit()
    await db.refresh(project)

    logger.info("admin.project.updated", project_id=project_id, fields=list(updates.keys()))
    return _project_to_response(project)


# ── Status event endpoints ────────────────────────────────────────────────────

@router.get(
    "/{project_id}/events",
    response_model=List[ProjectEventResponse],
    dependencies=[Depends(verify_api_key)],
    summary="List all status events for a project",
)
async def list_project_events(
    project_id: str,
    client_visible_only: bool = Query(
        False,
        description="When True, return only client-visible events.",
    ),
    db: AsyncSession = Depends(get_db),
):
    # Verify project exists
    await _get_project_or_404(project_id, db)

    query = (
        select(ProjectStatusEvent)
        .where(ProjectStatusEvent.project_id == project_id)
        .order_by(ProjectStatusEvent.recorded_at.asc())
    )
    if client_visible_only:
        query = query.where(ProjectStatusEvent.client_visible.is_(True))

    result = await db.execute(query)
    rows = result.scalars().all()

    logger.info("admin.project.events.listed", project_id=project_id, count=len(rows))
    return [_event_to_response(e) for e in rows]


@router.post(
    "/{project_id}/events",
    response_model=ProjectEventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
    summary="Record a stage transition for a project",
)
async def create_project_event(
    project_id: str,
    req: ProjectEventCreateRequest,
    force: bool = Query(
        False,
        description=(
            "Bypass ALLOWED_TRANSITIONS whitelist. "
            "Use only for corrections or exceptional admin overrides."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Record a stage transition on a project.

    - Updates Project.status to new_stage atomically with the event insert.
    - Enforces ALLOWED_TRANSITIONS unless force=true.
    - actor_type must be one of: system, admin, agent.
    - ProjectStatusEvent rows are INSERT-only; no PATCH/DELETE is provided.
    """
    # Validate actor_type
    valid_actors = {a.value for a in ActorType}
    if req.actor_type not in valid_actors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid actor_type '{req.actor_type}'. Allowed: {sorted(valid_actors)}",
        )

    # Validate new_stage
    if req.new_stage not in VALID_STAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid new_stage '{req.new_stage}'. Allowed: {sorted(VALID_STAGES)}",
        )

    project = await _get_project_or_404(project_id, db)
    old_stage = project.status

    # Enforce ALLOWED_TRANSITIONS unless force=true
    if not force:
        allowed = ALLOWED_TRANSITIONS.get(old_stage, [])
        if req.new_stage not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Transition '{old_stage}' → '{req.new_stage}' is not permitted. "
                    f"Allowed from '{old_stage}': {allowed}. "
                    f"Pass force=true to override."
                ),
            )

    # Update project status
    project.status = req.new_stage

    # Insert event
    event = ProjectStatusEvent(
        project_id=project_id,
        client_id=project.client_id,
        old_stage=old_stage,
        new_stage=req.new_stage,
        actor_type=req.actor_type,
        actor_id=req.actor_id,
        note=req.note,
        client_visible=req.client_visible,
    )
    db.add(event)

    await db.commit()
    await db.refresh(event)

    logger.info(
        "admin.project.stage_changed",
        project_id=project_id,
        old_stage=old_stage,
        new_stage=req.new_stage,
        actor_type=req.actor_type,
        forced=force,
    )
    return _event_to_response(event)
