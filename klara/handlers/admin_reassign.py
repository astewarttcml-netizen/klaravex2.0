"""Admin reassignment view — /admin/reassign

Allows administrators to reassign tickets to different assignees.
Auth via session cookie (require_admin_session dependency).
"""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .lib.admin_auth import require_admin_session
from .lib.db import get_pool
from .lib.tickets import _notify_status_change

log = logging.getLogger("klaravex.admin_reassign")
router = APIRouter()

_templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)


async def _bulk_update_assignees(assignments: dict[str, str]) -> list[tuple[str, dict]]:
    """Bulk update assignees for multiple tickets in a single query.
    
    Args:
        assignments: Dict mapping ticket_id -> new_assignee
        
    Returns:
        List of (ticket_id, row_data) tuples for notifications where row_data
        includes client_email, subject, status, assignee
    """
    if not assignments:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Prepare parameters for assignment and ticket_id
        assignees_params = []
        ticket_id_params = []
        for ticket_id_str, new_assignee in assignments.items():
            try:
                ticket_id = uuid.UUID(ticket_id_str)
                ticket_id_params.append(ticket_id)
                # Sanitize assignee value one more time for safety
                assignees_params.append(new_assignee.strip())
            except ValueError:
                log.warning("Invalid ticket ID format: %s", ticket_id_str)
                continue

        if not ticket_id_params:
            return []

        # Use unnest for efficient bulk update with parameterized query
        # Return rows for notifications
        query = """
            UPDATE klaravex_tickets AS kt
            SET
                assignee = new_assignments.new_assignee,
                updated_at = NOW()
            FROM (
                SELECT * FROM UNNEST($1::uuid[], $2::text[]) AS t(ticket_id, new_assignee)
            ) AS new_assignments
            WHERE kt.id = new_assignments.ticket_id
            RETURNING kt.id::text, kt.client_email, kt.subject, kt.status, kt.assignee;
        """

        try:
            rows = await conn.fetch(query, ticket_id_params, assignees_params)
            return [(row["id"], dict(row)) for row in rows]
        except Exception as e:
            log.error("Bulk update failed: %s", e)
            raise


async def _fetch_valid_assignees() -> set[str]:
    """Fetches all valid assignee emails from the 'users' table."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user_rows = await conn.fetch("SELECT email FROM users")
        return {r["email"] for r in user_rows}


@router.get("/reassign", response_class=HTMLResponse, include_in_schema=False)
async def admin_reassign(
    email: str = Depends(require_admin_session),
) -> HTMLResponse:
    """Show reassignment UI with list of tickets and available assignees."""
    items = []
    users = []
    
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Fetch tickets that can be reassigned (open, in_progress, escalated)
            ticket_rows = await conn.fetch(
                """
                SELECT id, subject, status, assignee, client_email, created_at
                FROM klaravex_tickets
                WHERE status IN ('open', 'in_progress', 'escalated')
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
            
            # Fetch available assignees (all users)
            user_rows = await conn.fetch(
                """
                SELECT email, name
                FROM users
                ORDER BY name
                """
            )
            
            items = [
                {
                    "id": str(row["id"]),
                    "title": row["subject"] or "(untitled)",
                    "current_assignee": row["assignee"] or "unassigned",
                    "client_email": row["client_email"],
                    "created_at": row["created_at"],
                }
                for row in ticket_rows
            ]
            
            users = [
                {
                    "email": row["email"],
                    "name": row["name"] or row["email"].split("@")[0],
                }
                for row in user_rows
            ]
            
    except Exception as e:
        log.warning("reassign query failed: %s", e)
    
    tmpl = _templates.env.get_template("admin_reassign.html")
    return HTMLResponse(tmpl.render(
        items=items,
        users=users,
        user_email=email,
    ))


@router.post("/reassign/submit", response_class=JSONResponse, include_in_schema=False)
async def admin_reassign_submit(
    request: Request,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    """Handle reassignment form submission."""
    form_data = await request.form()
    
    try:
        valid_assignees = await _fetch_valid_assignees()
        # Collect all assignments for bulk update, filtering out invalid assignees
        assignments = {}
        for key, new_assignee in form_data.items():
            if key.startswith("new_assignee_") and new_assignee:
                # Sanitize and validate new_assignee
                new_assignee = new_assignee.strip()
                if not new_assignee:
                    continue
                    
                # Validate assignee length and format
                if len(new_assignee) > 255:
                    log.warning("Assignee email too long: %s", new_assignee)
                    continue
                    
                # Check for potential injection patterns (simple check)
                if any(char in new_assignee for char in [";", "'", "\"", "\\", "--"]):
                    log.warning("Potentially unsafe assignee characters: %s", new_assignee)
                    continue
                    
                if new_assignee not in valid_assignees:
                    log.warning("Attempted to assign to invalid email: %s", new_assignee)
                    continue
                
                ticket_id_str = key.replace("new_assignee_", "")
                # Validate ticket ID format
                try:
                    # This will raise ValueError if not a valid UUID
                    uuid.UUID(ticket_id_str)
                    assignments[ticket_id_str] = new_assignee
                except ValueError:
                    log.warning("Invalid ticket ID format: %s", ticket_id_str)
                    continue
        
        # Use bulk update for all assignments
        if assignments:
            updated_rows = await _bulk_update_assignees(assignments)
            
            # Send notifications for each reassignment (best-effort)
            for ticket_id, row_data in updated_rows:
                try:
                    await _notify_status_change(ticket_id, row_data)
                except Exception as e:
                    log.warning("Failed to send notification for ticket %s: %s", ticket_id, e)
                
                log.info("Ticket %s reassigned to %s by %s", ticket_id, row_data["assignee"], email)
        
        return JSONResponse({"success": True, "message": "Reassignment successful"})
    
    except Exception as e:
        log.error("Reassignment failed: %s", e)
        # Return generic error message to avoid leaking internal information
        return JSONResponse({"success": False, "message": "An error occurred during reassignment. Please try again."})
