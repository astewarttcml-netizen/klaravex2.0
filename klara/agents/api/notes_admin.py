"""
app/api/notes_admin.py
───────────────────────
Admin-only endpoints for internal project notes (portal-232).

  GET    /api/v1/admin/projects/{project_id}/notes         — list notes
  POST   /api/v1/admin/projects/{project_id}/notes         — create note
  PATCH  /api/v1/admin/projects/{project_id}/notes/{id}    — update body
  DELETE /api/v1/admin/projects/{project_id}/notes/{id}    — delete note

Authorization: X-API-Key (verify_api_key dependency).

These endpoints are INTENTIONALLY NOT registered under the portal router.
The portal router (app/api/portal/) is JWT-authenticated and client-facing.
Admin notes must never appear in any portal response.

Design notes:
- updated_at is managed by the DB (server_default + trigger-like onupdate).
  The PATCH endpoint issues a direct UPDATE so the DB updates the column.
- PATCH returns the full updated note so the frontend can refresh in-place.
- DELETE returns 204 No Content — nothing to send back.
- 404 is returned for any note that doesn't belong to the given project_id
  (prevents cross-project note access even within the admin token scope).
"""
from __future__ import annotations

from typing import List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.portal import Project
from app.models.project_note import ProjectNote

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class NoteResponse(BaseModel):
    id: str
    project_id: str
    invoice_id: Optional[str]
    body: str
    created_at: str
    updated_at: str


class CreateNoteRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=50_000)
    invoice_id: Optional[str] = Field(None, description="Optional — link to a specific invoice")


class UpdateNoteRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=50_000)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_response(note: ProjectNote) -> NoteResponse:
    return NoteResponse(
        id=note.id,
        project_id=note.project_id,
        invoice_id=note.invoice_id,
        body=note.body,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat(),
    )


async def _get_project(project_id: str, db: AsyncSession) -> Project:
    """Load project. Raises 404 if missing."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project: Project | None = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    return project


async def _get_note(note_id: str, project_id: str, db: AsyncSession) -> ProjectNote:
    """Load note, enforcing project scope. Raises 404 on miss or wrong project."""
    result = await db.execute(
        select(ProjectNote).where(
            ProjectNote.id == note_id,
            ProjectNote.project_id == project_id,
        )
    )
    note: ProjectNote | None = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found.",
        )
    return note


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get(
    "/{project_id}/notes",
    response_model=List[NoteResponse],
    dependencies=[Depends(verify_api_key)],
    summary="List internal notes for a project",
)
async def list_notes(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return all admin notes for a project, newest-first.

    Verifies the project exists before querying notes to give a clean 404
    rather than an empty list when the project_id is wrong.
    """
    await _get_project(project_id, db)

    result = await db.execute(
        select(ProjectNote)
        .where(ProjectNote.project_id == project_id)
        .order_by(ProjectNote.created_at.desc())
    )
    notes = list(result.scalars().all())

    logger.info(
        "admin.notes.listed",
        project_id=project_id,
        count=len(notes),
    )
    return [_to_response(n) for n in notes]


@router.post(
    "/{project_id}/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
    summary="Create an internal note for a project",
)
async def create_note(
    project_id: str,
    req: CreateNoteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Attach a new internal note to a project.

    Optionally link to a specific invoice via `invoice_id`.  The note is
    owned by the project — deleting the project cascades the note.
    """
    await _get_project(project_id, db)

    note = ProjectNote(
        id=str(uuid4()),
        project_id=project_id,
        invoice_id=req.invoice_id,
        body=req.body.strip(),
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    logger.info(
        "admin.notes.created",
        project_id=project_id,
        note_id=note.id,
        invoice_id=req.invoice_id,
        body_length=len(req.body),
    )
    return _to_response(note)


@router.patch(
    "/{project_id}/notes/{note_id}",
    response_model=NoteResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Update an internal note",
)
async def update_note(
    project_id: str,
    note_id: str,
    req: UpdateNoteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Replace the body of a note.  `updated_at` is bumped automatically by
    the DB server_default / onupdate mechanism.

    Returns the full updated note.
    """
    note = await _get_note(note_id, project_id, db)

    note.body = req.body.strip()
    await db.commit()
    await db.refresh(note)

    logger.info(
        "admin.notes.updated",
        project_id=project_id,
        note_id=note_id,
        body_length=len(req.body),
    )
    return _to_response(note)


@router.delete(
    "/{project_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_api_key)],
    summary="Delete an internal note",
)
async def delete_note(
    project_id: str,
    note_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a note permanently.  204 No Content on success."""
    note = await _get_note(note_id, project_id, db)

    await db.delete(note)
    await db.commit()

    logger.info(
        "admin.notes.deleted",
        project_id=project_id,
        note_id=note_id,
    )
