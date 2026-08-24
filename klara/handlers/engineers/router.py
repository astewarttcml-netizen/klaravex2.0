"""HTTP surface for the 5 pillar engineer agents.

All write endpoints are LOKI_INTERNAL_SECRET-gated. Routes:

  GET  /engineers/roster                       public: pillar map for the website
  POST /engineers/dispatch                     run dispatcher across open tickets
  POST /engineers/seed-gap-analyses            foundational gap analysis per pillar
  POST /engineers/seed-playbooks               (legacy) service playbooks per pillar
  POST /engineers/produce-docs                 walk each pillar's backlog, produce docs
  POST /engineers/{name}/process/{ticket_id}   force one engineer to process one ticket
  GET  /engineers/actions                      list pending engineer actions
  POST /engineers/actions/{id}/approve         approve a pending action
  POST /engineers/actions/{id}/reject          reject a pending action
"""

import logging
import os
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..lib.db import get_pool
from .dispatcher import (
    ENGINEERS,
    PILLAR_WEBSITE_COPY,
    dispatch_open_tickets,
    get_engineer,
    produce_pending_docs,
    seed_gap_analyses,
    seed_playbooks,
)

log = logging.getLogger("klaravex.engineers.router")
router = APIRouter()

INTERNAL_SECRET = os.environ.get("LOKI_INTERNAL_SECRET", "")


def _check_internal(request: Request) -> None:
    if not INTERNAL_SECRET:
        return
    presented = request.headers.get("x-loki-internal-secret", "")
    if not secrets.compare_digest(INTERNAL_SECRET, presented):
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/roster", include_in_schema=False)
async def engineer_roster() -> dict[str, Any]:
    """Public: returns the 5 pillar engineers — used by klaravex.com to render
    'Meet the team' from a single source of truth."""
    return {
        "engineers": [
            {
                "name": e.name,
                "display_name": e.display_name,
                "pillar": e.pillar,
                "website_anchor": e.website_anchor,
                "expertise": e.expertise,
                "default_skus": e.default_skus,
                "specialty_keywords": e.specialty_keywords[:8],
                "backup_pillars": e.backup_pillars,
                "documentation_targets_count": len(e.documentation_targets),
            }
            for e in ENGINEERS
        ],
        "pillar_website_copy": PILLAR_WEBSITE_COPY,
    }


@router.post("/dispatch", include_in_schema=False)
async def dispatch(request: Request, limit: int = 20) -> JSONResponse:
    _check_internal(request)
    result = await dispatch_open_tickets(limit=limit)
    return JSONResponse(result)


@router.post("/seed-gap-analyses", include_in_schema=False)
async def seed_gaps(request: Request) -> JSONResponse:
    _check_internal(request)
    result = await seed_gap_analyses()
    return JSONResponse(result)


@router.post("/seed-playbooks", include_in_schema=False)
async def seed(request: Request) -> JSONResponse:
    _check_internal(request)
    result = await seed_playbooks()
    return JSONResponse(result)


@router.post("/produce-docs", include_in_schema=False)
async def produce_docs(request: Request, limit_per_engineer: int = 2) -> JSONResponse:
    _check_internal(request)
    result = await produce_pending_docs(limit_per_engineer=limit_per_engineer)
    return JSONResponse(result)


@router.post("/{name}/process/{ticket_id}", include_in_schema=False)
async def process_one(request: Request, name: str, ticket_id: str) -> JSONResponse:
    _check_internal(request)
    engineer = get_engineer(name)
    if not engineer:
        raise HTTPException(status_code=404, detail=f"unknown engineer: {name}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id::text, severity, status, source, archetype, sku,
                   subject, summary, client_email, created_at
              FROM klaravex_tickets WHERE id = $1
            """,
            ticket_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="ticket not found")
    ticket = dict(row)
    action = await engineer.reason_about_ticket(ticket)
    action_id = await engineer.queue_action(
        action=action,
        ticket_id=ticket_id,
        client_email=ticket.get("client_email"),
    )
    return JSONResponse({
        "ok": True,
        "engineer": engineer.name,
        "pillar": engineer.pillar,
        "ticket_id": ticket_id,
        "action_id": action_id,
        "action_type": action.get("action_type"),
        "title": action.get("title"),
    })


@router.get("/actions", include_in_schema=False)
async def list_actions(request: Request, status: str = "pending", limit: int = 50) -> JSONResponse:
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text, engineer, ticket_id::text, action_type, title,
                   status, created_at, reasoning
              FROM klaravex_engineer_actions
             WHERE status = $1
             ORDER BY created_at DESC LIMIT $2
            """,
            status, limit,
        )
    return JSONResponse({"actions": [dict(r) for r in rows]})


@router.post("/actions/{action_id}/approve", include_in_schema=False)
async def approve_action(request: Request, action_id: str) -> JSONResponse:
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE klaravex_engineer_actions
               SET status='approved', approved_at=now(), updated_at=now()
             WHERE id=$1 AND status='pending'
            """,
            action_id,
        )
    return JSONResponse({"ok": True, "action_id": action_id, "status": "approved"})


@router.post("/actions/{action_id}/reject", include_in_schema=False)
async def reject_action(request: Request, action_id: str) -> JSONResponse:
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE klaravex_engineer_actions
               SET status='rejected', updated_at=now()
             WHERE id=$1 AND status='pending'
            """,
            action_id,
        )
    return JSONResponse({"ok": True, "action_id": action_id, "status": "rejected"})
