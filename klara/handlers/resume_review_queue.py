"""
Resume review queue — T6.3.4.

FastAPI router at /api/v1/resume/queue.

  POST   /api/v1/resume/queue
      Adds a resume draft + client email to the review queue.
      Stores as a klaravex_tickets row with type='resume_review' (in metadata).
      Returns {ticket_id, status}.

  GET    /api/v1/resume/queue
      Lists all pending resume review items.
      Auth-gated: requires X-Admin-Token header matching APP_SECRET_KEY.

  PATCH  /api/v1/resume/queue/{ticket_id}/complete
      Marks a review as done, sends final draft to client via Resend.
      Auth-gated: requires X-Admin-Token header matching APP_SECRET_KEY.

Mount with:
    from infra.klara.handlers.resume_review_queue import router as resume_review_queue_router
    app.include_router(resume_review_queue_router, prefix="/api/v1/resume")
"""

import json
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field

from .lib import tickets as tickets_lib
from .lib.db import get_pool
from .lib.email import send_email

log = logging.getLogger("klaravex.resume_review_queue")
router = APIRouter()

APP_SECRET_KEY = os.environ.get("APP_SECRET_KEY", "")
APPROVAL_NOTIFY_EMAIL = os.environ.get(
    "APPROVAL_NOTIFY_EMAIL",
    os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com"),
)

RESUME_REVIEW_TYPE = "resume_review"


def _require_admin(x_admin_token: str) -> None:
    if not APP_SECRET_KEY:
        raise HTTPException(status_code=503, detail="APP_SECRET_KEY not configured on server")
    if x_admin_token != APP_SECRET_KEY:
        raise HTTPException(status_code=403, detail="invalid admin token")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class QueueSubmitRequest(BaseModel):
    client_email: EmailStr
    client_name: str | None = Field(default=None, max_length=120)
    draft_markdown: str = Field(min_length=10, description="Resume draft in Markdown")
    sku: str = Field(default="resume-premium")
    target_role: str | None = Field(default=None, max_length=200)


class CompleteReviewRequest(BaseModel):
    final_markdown: str = Field(min_length=10, description="Final (reviewed) resume in Markdown")
    reviewer_notes: str | None = Field(default=None, max_length=1000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _send_draft_email(to: str, name: str | None, final_markdown: str, ticket_id: str) -> None:
    display_name = name or "there"
    subject = "Your Klaravex Resume — Final Draft Ready"
    body = (
        f"Hi {display_name},\n\n"
        f"Your resume review is complete. Your final draft is attached below.\n\n"
        f"{'='*60}\n\n"
        f"{final_markdown}\n\n"
        f"{'='*60}\n\n"
        f"To convert to Word/PDF, paste the above into a Markdown editor or reply to this email and we'll send a formatted version.\n\n"
        f"Reference: {ticket_id}\n\n"
        f"— The Klaravex Team\n"
    )
    await send_email(to=to, subject=subject, body=body)
    log.info("Final draft email sent to %s (ticket %s)", to, ticket_id)


async def _notify_review_queued(client_email: str, ticket_id: str, sku: str) -> None:
    subject = f"[Klaravex] Resume review queued — {client_email}"
    body = (
        f"A resume has been queued for review.\n\n"
        f"Client: {client_email}\n"
        f"SKU:    {sku}\n"
        f"Ticket: {ticket_id}\n\n"
        f"Review queue: GET /api/v1/resume/queue\n"
    )
    await send_email(to=APPROVAL_NOTIFY_EMAIL, subject=subject, body=body)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/queue", status_code=201)
async def submit_to_review_queue(payload: QueueSubmitRequest) -> dict[str, str]:
    """Submit a resume draft for Anthony's review."""
    ticket_id: str | None = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=str(payload.client_email),
            subject=f"Resume review: {payload.sku} — {str(payload.client_email)}",
            severity="standard",
            status="waiting_client",  # waiting on reviewer
            source="workflow",
            archetype="A2",
            sku=payload.sku,
            summary=f"Resume review queued for {payload.target_role or 'unspecified role'}. Draft length: {len(payload.draft_markdown)} chars.",
            segment_hint="consumer",
            metadata={
                "type": RESUME_REVIEW_TYPE,
                "client_name": payload.client_name,
                "target_role": payload.target_role,
                "draft_markdown": payload.draft_markdown,
                "sku": payload.sku,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Failed to create resume review ticket: %s", e)
        raise HTTPException(status_code=500, detail="Failed to queue resume review")

    try:
        await _notify_review_queued(str(payload.client_email), ticket_id, payload.sku)
    except Exception as e:  # noqa: BLE001
        log.warning("Queue notify email failed (continuing): %s", e)

    return {"ticket_id": ticket_id, "status": "queued"}


@router.get("/queue")
async def list_review_queue(
    x_admin_token: str = Header(default="", alias="x-admin-token"),
) -> dict[str, Any]:
    """List all pending resume review tickets. Requires X-Admin-Token header."""
    _require_admin(x_admin_token)

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, client_email, subject, sku, status, created_at, metadata
              FROM klaravex_tickets
             WHERE metadata->>'type' = $1
               AND status NOT IN ('resolved', 'closed')
             ORDER BY created_at ASC
            """,
            RESUME_REVIEW_TYPE,
        )

    items = []
    for r in rows:
        meta = r["metadata"] if isinstance(r["metadata"], dict) else json.loads(r["metadata"] or "{}")
        items.append({
            "ticket_id": str(r["id"]),
            "client_email": r["client_email"],
            "subject": r["subject"],
            "sku": r["sku"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "target_role": meta.get("target_role"),
            "client_name": meta.get("client_name"),
            "draft_length_chars": len(meta.get("draft_markdown") or ""),
        })

    return {"count": len(items), "items": items}


@router.patch("/queue/{ticket_id}/complete")
async def complete_review(
    ticket_id: str,
    payload: CompleteReviewRequest,
    x_admin_token: str = Header(default="", alias="x-admin-token"),
) -> dict[str, str]:
    """Mark a resume review complete and send the final draft to the client."""
    _require_admin(x_admin_token)

    # Validate ticket ID format
    try:
        ticket_uuid = uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid ticket_id format")

    # Fetch the ticket to get client info
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, client_email, status, metadata, sku
              FROM klaravex_tickets
             WHERE id = $1
               AND metadata->>'type' = $2
            """,
            ticket_uuid,
            RESUME_REVIEW_TYPE,
        )

    if not row:
        raise HTTPException(status_code=404, detail="Resume review ticket not found")
    if row["status"] in ("resolved", "closed"):
        raise HTTPException(status_code=409, detail="Review already completed")

    meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
    client_name = meta.get("client_name")

    # Update ticket status to resolved
    try:
        await tickets_lib.update_status(
            ticket_id,
            status="resolved",
            resolution="Final resume draft delivered to client.",
        )
        await tickets_lib.append_event(
            ticket_id,
            "review_completed",
            {
                "reviewer_notes": payload.reviewer_notes,
                "final_markdown_length": len(payload.final_markdown),
            },
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Failed to update ticket status: %s", e)
        raise HTTPException(status_code=500, detail="Failed to mark review complete")

    # Send final draft to client
    try:
        await _send_draft_email(row["client_email"], client_name, payload.final_markdown, ticket_id)
    except Exception as e:  # noqa: BLE001
        log.exception("Final draft email failed: %s", e)
        raise HTTPException(status_code=500, detail="Review marked complete but email delivery failed")

    return {"ticket_id": ticket_id, "status": "resolved", "emailed_to": row["client_email"]}
