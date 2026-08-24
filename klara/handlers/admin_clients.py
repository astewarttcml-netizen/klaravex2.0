"""Admin Clients/Projects/Invoices portal — /admin/clients

Tabbed view of klaravex_clients, klaravex_projects, and klaravex_invoices.
Auth via session cookie (require_admin_session dependency).
Replaces the broken standalone portal at http://100.66.236.56:8010/admin/portal.
"""

import datetime
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .lib.admin_auth import require_admin_session
from .lib.db import get_pool

log = logging.getLogger("klaravex.admin_clients")
router = APIRouter()

_templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)


def _user_initials(email: str) -> str:
    name = email.split("@")[0]
    parts = name.replace(".", " ").replace("_", " ").split()
    return "".join(p[0].upper() for p in parts[:2]) or "A"


def _iso(dt: datetime.datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


# ── Page render ──────────────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_clients_page(
    email: str = Depends(require_admin_session),
) -> HTMLResponse:
    tmpl = _templates.env.get_template("admin_clients.html")
    return HTMLResponse(tmpl.render(
        user_email=email,
        user_initials=_user_initials(email),
    ))


# ── JSON API endpoints ──────────────────────────────────────────────────────
@router.get("/api/clients")
async def api_clients(
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, email, status, created_at "
                "FROM klaravex_clients "
                "ORDER BY created_at DESC"
            )
        data = [
            {
                "id": str(r["id"]),
                "name": r["name"] or "",
                "email": r["email"] or "",
                "status": r["status"] or "active",
                "created_at": _iso(r["created_at"]),
            }
            for r in rows
        ]
        return JSONResponse({"clients": data})
    except Exception as e:
        log.warning("api_clients query failed: %s", e)
        return JSONResponse({"clients": [], "error": str(e)[:200]})


@router.get("/api/projects")
async def api_projects(
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT p.id, p.title, p.status, p.total_budget_usd, p.created_at, "
                "       COALESCE(c.name, '') AS client_name "
                "FROM klaravex_projects p "
                "LEFT JOIN klaravex_clients c ON c.id = p.client_id "
                "ORDER BY p.created_at DESC"
            )
        data = [
            {
                "id": str(r["id"]),
                "title": r["title"] or "",
                "client_name": r["client_name"],
                "status": r["status"] or "intake",
                "total_budget_usd": float(r["total_budget_usd"]) if r["total_budget_usd"] else None,
                "created_at": _iso(r["created_at"]),
            }
            for r in rows
        ]
        return JSONResponse({"projects": data})
    except Exception as e:
        log.warning("api_projects query failed: %s", e)
        return JSONResponse({"projects": [], "error": str(e)[:200]})


@router.get("/api/invoices")
async def api_invoices(
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT i.id, i.invoice_number, i.amount_usd, i.status, "
                "       i.due_date, i.created_at, "
                "       COALESCE(c.name, '') AS client_name "
                "FROM klaravex_invoices i "
                "LEFT JOIN klaravex_clients c ON c.id = i.client_id "
                "ORDER BY i.created_at DESC"
            )
        data = [
            {
                "id": str(r["id"]),
                "invoice_number": r["invoice_number"] or "",
                "client_name": r["client_name"],
                "amount_usd": float(r["amount_usd"]) if r["amount_usd"] else 0,
                "status": r["status"] or "draft",
                "due_date": _iso(r["due_date"]),
                "created_at": _iso(r["created_at"]),
            }
            for r in rows
        ]
        return JSONResponse({"invoices": data})
    except Exception as e:
        log.warning("api_invoices query failed: %s", e)
        return JSONResponse({"invoices": [], "error": str(e)[:200]})


# ── Mutations ────────────────────────────────────────────────────────────────
class CreateClientRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=254)


@router.post("/api/clients")
async def api_create_client(
    req: CreateClientRequest,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO klaravex_clients (name, email, status) "
                "VALUES ($1, $2, 'active') RETURNING id",
                req.name, req.email,
            )
        return JSONResponse({"ok": True, "id": str(row["id"])})
    except Exception as e:
        log.warning("api_create_client failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/api/clients/{client_id}/deactivate")
async def api_deactivate_client(
    client_id: str,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE klaravex_clients SET status='inactive', updated_at=now() "
                "WHERE id=$1::uuid",
                client_id,
            )
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.warning("api_deactivate_client failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/api/clients/{client_id}/activate")
async def api_activate_client(
    client_id: str,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE klaravex_clients SET status='active', updated_at=now() "
                "WHERE id=$1::uuid",
                client_id,
            )
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.warning("api_activate_client failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:200])


# ── Projects — create + advance status ───────────────────────────────────────

_PROJECT_STATUS_FLOW = [
    "intake", "sow_draft", "sow_sent", "accepted",
    "active", "final_signoff", "invoiced", "closed",
]


class CreateProjectRequest(BaseModel):
    client_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=300)
    scope_summary: str | None = None
    total_budget_usd: float | None = None


@router.post("/api/projects")
async def api_create_project(
    req: CreateProjectRequest,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            client_row = await conn.fetchrow(
                "SELECT id, email FROM klaravex_clients WHERE id=$1::uuid",
                req.client_id,
            )
            if not client_row:
                raise HTTPException(status_code=400, detail="client not found")
            row = await conn.fetchrow(
                "INSERT INTO klaravex_projects "
                "  (client_id, client_email, title, scope_summary, total_budget_usd) "
                "VALUES ($1::uuid, $2, $3, $4, $5) RETURNING id",
                req.client_id,
                client_row["email"],
                req.title,
                req.scope_summary,
                req.total_budget_usd,
            )
        return JSONResponse({"ok": True, "id": str(row["id"])})
    except HTTPException:
        raise
    except Exception as e:
        log.warning("api_create_project failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/api/projects/{project_id}/advance")
async def api_advance_project(
    project_id: str,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    """Advance a project to the next status in the workflow."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status FROM klaravex_projects WHERE id=$1::uuid",
                project_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="project not found")
            current = row["status"]
            if current in ("closed", "cancelled"):
                return JSONResponse({"ok": False, "reason": "project already closed/cancelled"})
            try:
                idx = _PROJECT_STATUS_FLOW.index(current)
                next_status = _PROJECT_STATUS_FLOW[idx + 1]
            except (ValueError, IndexError):
                return JSONResponse({"ok": False, "reason": f"no next status after {current!r}"})
            await conn.execute(
                "UPDATE klaravex_projects SET status=$1, updated_at=now() WHERE id=$2::uuid",
                next_status, project_id,
            )
        return JSONResponse({"ok": True, "prev_status": current, "new_status": next_status})
    except HTTPException:
        raise
    except Exception as e:
        log.warning("api_advance_project failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/api/projects/{project_id}/cancel")
async def api_cancel_project(
    project_id: str,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE klaravex_projects SET status='cancelled', updated_at=now() "
                "WHERE id=$1::uuid",
                project_id,
            )
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.warning("api_cancel_project failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:200])


# ── Invoices — full CRUD ─────────────────────────────────────────────────────

class LineItem(BaseModel):
    description: str
    amount_usd: float


class CreateInvoiceRequest(BaseModel):
    client_id: str = Field(min_length=1)
    invoice_number: str | None = None
    amount_usd: float = Field(ge=0)
    due_date: str | None = None          # ISO date string YYYY-MM-DD
    line_items: list[LineItem] = []
    notes: str | None = None


@router.get("/api/invoices/{invoice_id}")
async def api_get_invoice(
    invoice_id: str,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT i.id, i.invoice_number, i.amount_usd, i.status, "
                "       i.due_date, i.paid_at, i.line_items, i.notes, i.created_at, "
                "       COALESCE(c.name, '') AS client_name "
                "FROM klaravex_invoices i "
                "LEFT JOIN klaravex_clients c ON c.id = i.client_id "
                "WHERE i.id=$1::uuid",
                invoice_id,
            )
        if not row:
            raise HTTPException(status_code=404, detail="invoice not found")
        import json as _json
        data = {
            "id": str(row["id"]),
            "invoice_number": row["invoice_number"] or "",
            "client_name": row["client_name"],
            "amount_usd": float(row["amount_usd"]) if row["amount_usd"] else 0,
            "status": row["status"] or "draft",
            "due_date": _iso(row["due_date"]),
            "paid_at": _iso(row["paid_at"]),
            "line_items": row["line_items"] if isinstance(row["line_items"], list)
                          else _json.loads(row["line_items"] or "[]"),
            "notes": row["notes"] or "",
            "created_at": _iso(row["created_at"]),
        }
        return JSONResponse(data)
    except HTTPException:
        raise
    except Exception as e:
        log.warning("api_get_invoice failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/api/invoices")
async def api_create_invoice(
    req: CreateInvoiceRequest,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    import json as _json
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            client_row = await conn.fetchrow(
                "SELECT id, email FROM klaravex_clients WHERE id=$1::uuid",
                req.client_id,
            )
            if not client_row:
                raise HTTPException(status_code=400, detail="client not found")
            due = None
            if req.due_date:
                import datetime as _dt
                due = _dt.date.fromisoformat(req.due_date)
            line_items_json = _json.dumps([li.model_dump() for li in req.line_items])
            row = await conn.fetchrow(
                "INSERT INTO klaravex_invoices "
                "  (client_id, client_email, invoice_number, amount_usd, due_date, line_items, notes) "
                "VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7) RETURNING id",
                req.client_id,
                client_row["email"],
                req.invoice_number,
                req.amount_usd,
                due,
                line_items_json,
                req.notes,
            )
        return JSONResponse({"ok": True, "id": str(row["id"])})
    except HTTPException:
        raise
    except Exception as e:
        log.warning("api_create_invoice failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/api/invoices/{invoice_id}/mark-paid")
async def api_mark_invoice_paid(
    invoice_id: str,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE klaravex_invoices "
                "SET status='paid', paid_at=now(), updated_at=now() "
                "WHERE id=$1::uuid AND status != 'paid'",
                invoice_id,
            )
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.warning("api_mark_invoice_paid failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/api/invoices/{invoice_id}/void")
async def api_void_invoice(
    invoice_id: str,
    email: str = Depends(require_admin_session),
) -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE klaravex_invoices "
                "SET status='void', updated_at=now() "
                "WHERE id=$1::uuid AND status NOT IN ('paid', 'void')",
                invoice_id,
            )
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.warning("api_void_invoice failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:200])
