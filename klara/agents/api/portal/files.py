"""
app/api/portal/files.py
────────────────────────
Secure client file access.

GET /api/v1/portal/files              — list available files
GET /api/v1/portal/files/{id}/download — serve file content

Security rules enforced here:
1. client_id ownership check on every request — no cross-client access.
2. file_path is NEVER returned in list or detail responses.
3. Download serves file bytes directly through FastAPI — no public URL.
4. Audit log entry written on every download.
5. If the file doesn't exist on disk, returns 404 (not 500).

File storage for Phase 1:
  Files are stored on the Hetzner server at a configured base path.
  The admin uploads files manually (sftp / scp) and then creates the
  ClientFile record via the admin API or directly in Postgres.

Phase 2 extension point:
  Replace the FileResponse with a signed S3/DigitalOcean Spaces URL
  to offload bandwidth from the API server.
"""
import os
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_auth import get_current_portal_client
from app.database import get_db
from app.models.portal import CLIENT_VISIBLE_FILE_LABELS, Client, ClientFile

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class FileListItem(BaseModel):
    id: str
    title: str
    description: Optional[str]
    project_id: Optional[str]
    original_filename: Optional[str]
    file_size_bytes: Optional[int]
    mime_type: Optional[str]
    uploaded_at: str
    # Lifecycle label rendered as a badge in the portal UI.
    # Always one of CLIENT_VISIBLE_FILE_LABELS for client-facing responses.
    label: str
    # file_path is deliberately excluded — never exposed via API


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[FileListItem], summary="List client files")
async def list_files(
    project_id: Optional[str] = None,
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all files available to the authenticated client.

    Optional query param: ?project_id=<uuid> to filter by project.
    File paths are never included in the response.

    Draft files are filtered out at the SQL layer — clients only see
    files labelled `approved` or `delivered` (portal-241).
    """
    query = (
        select(ClientFile)
        .where(ClientFile.client_id == client.id)
        .where(ClientFile.label.in_(CLIENT_VISIBLE_FILE_LABELS))
    )

    if project_id:
        query = query.where(ClientFile.project_id == project_id)

    query = query.order_by(ClientFile.uploaded_at.desc())
    result = await db.execute(query)
    files = result.scalars().all()

    return [
        FileListItem(
            id=f.id,
            title=f.title,
            description=f.description,
            project_id=f.project_id,
            original_filename=f.original_filename,
            file_size_bytes=f.file_size_bytes,
            mime_type=f.mime_type,
            uploaded_at=f.uploaded_at.isoformat(),
            label=f.label,
        )
        for f in files
    ]


@router.get(
    "/{file_id}/download",
    summary="Download a file",
    response_class=FileResponse,
)
async def download_file(
    file_id: str,
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream a file to the authenticated client.

    Authorization: client must own the file (client_id match) AND the file
    must be in a client-visible label (approved/delivered) — drafts are
    never downloadable through the portal (portal-241).
    Returns 404 for missing records, draft files, or files not on disk.
    Writes an audit log entry on every successful download.
    """
    # ── Ownership + visibility check ──────────────────────────────────────────
    # Draft files share the 404 response with truly-missing rows so a client
    # cannot probe for the existence of internal drafts by enumerating ids.
    result = await db.execute(
        select(ClientFile).where(
            ClientFile.id == file_id,
            ClientFile.client_id == client.id,  # ← ownership enforced here
            ClientFile.label.in_(CLIENT_VISIBLE_FILE_LABELS),
        )
    )
    client_file: ClientFile | None = result.scalar_one_or_none()

    if client_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found.",
        )

    # ── Disk check ────────────────────────────────────────────────────────────
    if not os.path.isfile(client_file.file_path):
        logger.error(
            "portal.file_missing_on_disk",
            file_id=file_id,
            client_id=client.id,
            path=client_file.file_path,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File is not currently available. Please contact support.",
        )

    # ── Audit log ─────────────────────────────────────────────────────────────
    import uuid as _uuid
    from app.models.audit import AuditLog
    audit = AuditLog(
        id=str(_uuid.uuid4()),
        event_type="portal.file_downloaded",
        agent_name="portal_files",
        lead_id=None,
        success=True,
        details=f"client_id={client.id} file_id={file_id} title={client_file.title!r}",
    )
    db.add(audit)

    logger.info(
        "portal.file_downloaded",
        client_id=client.id,
        file_id=file_id,
        title=client_file.title,
    )

    # ── Serve file ────────────────────────────────────────────────────────────
    download_name = client_file.original_filename or client_file.title
    return FileResponse(
        path=client_file.file_path,
        media_type=client_file.mime_type or "application/octet-stream",
        filename=download_name,
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "Cache-Control": "no-store",   # never cache private files
            "X-Content-Type-Options": "nosniff",
        },
    )
