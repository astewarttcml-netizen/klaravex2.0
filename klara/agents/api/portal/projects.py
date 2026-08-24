"""
app/api/portal/projects.py
───────────────────────────
Client-facing project endpoints.

GET /api/v1/portal/projects                  — list all client's projects
GET /api/v1/portal/projects/{id}             — get one project detail (with timeline)
GET /api/v1/portal/projects/{id}/updates     — Updates feed (portal-212)

Authorization: every query is filtered by client.id from the JWT.
A client cannot retrieve another client's project even if they guess the UUID.

portal-211 detail response contract:
  - `stages` is the static ordered list of all defined stages with the current
    one flagged — used to render the progress indicator.
  - `timeline` is the chronological list of past transitions for THIS project
    where `client_visible=true` — used to show real history (when the project
    moved from "In assessment" to "Draft ready", etc.). Sourced from the
    project_status_events table, which is INSERT-only (see
    app/services/project_stage.py).

portal-212 Updates feed contract:
  - Same source data as the timeline (project_status_events filtered by
    client_visible) but ordered NEWEST FIRST and shaped for feed rendering.
  - Each entry carries a past-tense human-readable `message` so the frontend
    can render directly: "Assessment started", "Draft delivered", etc.
  - Future slices may broaden the feed to include file-upload and payment
    events; the response shape is designed to absorb that without a break.
"""
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Query

from app.core.portal_auth import get_current_portal_client
from klara.rarv.runtime import get_db
from klara.rarv.portal import Client, Project, ProjectStatus, PROJECT_STATUS_LABELS
from klara.rarv.project_event import ProjectStatusEvent


# ─────────────────────────────────────────────────────────────────────────────
# Past-tense client-facing messages for the Updates feed (portal-212).
#
# Lookup by *destination* stage. These read as "what happened" rather than
# "what is happening" so the feed renders naturally as a sequence of completed
# events (matching the PRD examples: "Assessment completed", "Draft delivered").
#
# Anything not in this map falls through to a generic "Status updated" — that
# keeps the feed working if a new stage value is added before this map is.
# ─────────────────────────────────────────────────────────────────────────────
_UPDATE_MESSAGES: dict[str, str] = {
    ProjectStatus.new_request.value:        "Request received",
    ProjectStatus.in_assessment.value:      "Assessment started",
    ProjectStatus.draft_ready.value:        "Draft delivered",
    ProjectStatus.awaiting_approval.value:  "Waiting for your approval",
    ProjectStatus.in_progress.value:        "Work in progress",
    ProjectStatus.waiting_on_client.value:  "Waiting for your feedback",
    ProjectStatus.complete.value:           "Project completed",
}


def _update_message(new_stage: str) -> str:
    return _UPDATE_MESSAGES.get(new_stage, "Status updated")

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class TimelineEntry(BaseModel):
    """One row in the client-visible project timeline (portal-211)."""
    new_stage: str
    new_stage_label: str
    new_stage_description: str
    old_stage: Optional[str]
    note: Optional[str]
    recorded_at: str


class ProjectResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    status: str
    status_label: str
    status_description: str
    next_action: Optional[str]
    latest_update: Optional[str]
    created_at: str
    updated_at: str
    # All defined stages with current position highlighted
    stages: List[dict]


class ProjectDetailResponse(ProjectResponse):
    """
    Detail view (GET /{id}) — adds the chronological client-visible timeline.

    The timeline is sourced from project_status_events filtered by
    `client_visible=true` and ordered oldest → newest, so the frontend can
    render it top-to-bottom as "what has happened so far".
    """
    timeline: List[TimelineEntry]


class UpdateEntry(BaseModel):
    """One row in the Updates feed (portal-212)."""
    message: str           # past-tense human-readable, e.g. "Draft delivered"
    new_stage: str         # destination stage (used by the UI for badges/icons)
    note: Optional[str]    # optional admin note attached to the transition
    recorded_at: str       # ISO 8601 timestamp


class UpdatesFeedResponse(BaseModel):
    """
    Paginated feed payload. Includes the count of items returned in this page.
    Frontend can append more by calling again with a higher offset.
    """
    project_id: str
    items: List[UpdateEntry]
    count: int             # number of items in this page
    has_more: bool         # whether there are more items beyond `count`


def _build_stages(current_status: str) -> List[dict]:
    """
    Return the ordered list of project stages with a flag showing which
    is current.  Used to render the progress indicator in the UI.
    """
    stage_order = [
        ProjectStatus.new_request,
        ProjectStatus.in_assessment,
        ProjectStatus.draft_ready,
        ProjectStatus.awaiting_approval,
        ProjectStatus.in_progress,
        ProjectStatus.waiting_on_client,
        ProjectStatus.complete,
    ]
    return [
        {
            "key": s.value,
            "label": PROJECT_STATUS_LABELS[s]["label"],
            "is_current": s.value == current_status,
        }
        for s in stage_order
    ]


def _stage_meta(stage: str) -> dict:
    """Resolve the {label, description} pair for a stage value, with fallback."""
    try:
        return PROJECT_STATUS_LABELS[ProjectStatus(stage)]
    except (ValueError, KeyError):
        return {"label": stage, "description": ""}


def _to_response(p: Project) -> ProjectResponse:
    status_meta = _stage_meta(p.status)
    return ProjectResponse(
        id=p.id,
        title=p.title,
        description=p.description,
        status=p.status,
        status_label=status_meta["label"],
        status_description=status_meta["description"],
        next_action=p.next_action,
        latest_update=p.latest_update,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
        stages=_build_stages(p.status),
    )


def _timeline_entry(event: ProjectStatusEvent) -> TimelineEntry:
    """Translate a stored event into the client-facing timeline entry."""
    meta = _stage_meta(event.new_stage)
    return TimelineEntry(
        new_stage=event.new_stage,
        new_stage_label=meta["label"],
        new_stage_description=meta["description"],
        old_stage=event.old_stage,
        note=event.note,
        recorded_at=event.recorded_at.isoformat(),
    )


def _to_detail_response(
    p: Project, events: List[ProjectStatusEvent]
) -> ProjectDetailResponse:
    base = _to_response(p)
    return ProjectDetailResponse(
        **base.model_dump(),
        timeline=[_timeline_entry(e) for e in events],
    )


def _update_entry(event: ProjectStatusEvent) -> UpdateEntry:
    """Translate a stored event into a feed entry (portal-212)."""
    return UpdateEntry(
        message=_update_message(event.new_stage),
        new_stage=event.new_stage,
        note=event.note,
        recorded_at=event.recorded_at.isoformat(),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[ProjectResponse], summary="List client projects")
async def list_projects(
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """Return all projects belonging to the authenticated client, newest first."""
    result = await db.execute(
        select(Project)
        .where(Project.client_id == client.id)
        .order_by(Project.updated_at.desc())
    )
    projects = result.scalars().all()
    return [_to_response(p) for p in projects]


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="Get project detail with timeline",
)
async def get_project(
    project_id: str,
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Return detail for a single project, including the client-visible
    timeline of stage transitions (portal-211).

    Returns 404 if the project does not exist OR belongs to a different client.
    This prevents enumeration — from the client's perspective, someone else's
    project simply doesn't exist.

    Only events with `client_visible=true` are exposed in the timeline.
    Internal-only transitions (e.g. assessment notes that aren't ready for
    the client to see) stay hidden.
    """
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.client_id == client.id,  # ← ownership check
        )
    )
    project: Project | None = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    # Load the client-visible timeline, oldest → newest, scoped to this project
    # AND this client (defence-in-depth — client_id is denormalised on the
    # event row so a single index lookup answers the ownership question).
    events_result = await db.execute(
        select(ProjectStatusEvent)
        .where(
            ProjectStatusEvent.project_id == project_id,
            ProjectStatusEvent.client_id == client.id,
            ProjectStatusEvent.client_visible.is_(True),
        )
        .order_by(ProjectStatusEvent.recorded_at.asc())
    )
    events: List[ProjectStatusEvent] = list(events_result.scalars().all())

    logger.info(
        "portal.project_viewed",
        client_id=client.id,
        project_id=project_id,
        timeline_events=len(events),
    )
    return _to_detail_response(project, events)


@router.get(
    "/{project_id}/updates",
    response_model=UpdatesFeedResponse,
    summary="Updates feed for a project (portal-212)",
)
async def list_project_updates(
    project_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the project's Updates feed: client-visible status events shaped
    into past-tense human-readable messages and ordered NEWEST FIRST.

    Returns 404 if the project doesn't exist or belongs to a different
    client (same enumeration-prevention rule as the detail endpoint).

    The feed reuses project_status_events. Future slices may broaden the
    source to include file uploads and payment events; the response shape
    is stable so existing frontends continue to work.

    `has_more` is computed by fetching one extra row beyond the requested
    page; the extra is dropped before serialisation. The frontend can
    paginate by calling again with offset += count.
    """
    # 1. Ownership check — same pattern as get_project. Cheaper than a JOIN
    # because the ownership index on portal_projects is hot.
    project_result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.client_id == client.id,
        )
    )
    project: Project | None = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    # 2. Fetch limit+1 so we can answer has_more without a COUNT(*) round trip
    events_result = await db.execute(
        select(ProjectStatusEvent)
        .where(
            ProjectStatusEvent.project_id == project_id,
            ProjectStatusEvent.client_id == client.id,
            ProjectStatusEvent.client_visible.is_(True),
        )
        .order_by(ProjectStatusEvent.recorded_at.desc())
        .limit(limit + 1)
        .offset(offset)
    )
    events: List[ProjectStatusEvent] = list(events_result.scalars().all())
    has_more = len(events) > limit
    page = events[:limit]

    logger.info(
        "portal.project_updates_viewed",
        client_id=client.id,
        project_id=project_id,
        count=len(page),
        has_more=has_more,
        offset=offset,
    )
    return UpdatesFeedResponse(
        project_id=project_id,
        items=[_update_entry(e) for e in page],
        count=len(page),
        has_more=has_more,
    )
