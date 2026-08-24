"""
app/api/portal/__init__.py
───────────────────────────
Portal API router — aggregates all portal sub-routers.

Mounted at /api/v1/portal in main.py.

Sub-routes:
  /auth        — login, logout, me
  /dashboard   — client summary view
  /projects    — project list and detail
  /files       — file list and secure download
  /files/{id}/feedback — thumbs-up/down client feedback on files (portal-242)
  /invoices    — invoice list, detail, checkout, payment status
  /payments    — recent successful payments listing (portal-223)
  /projects    — per-project message thread, client-facing (portal-231)
"""
from fastapi import APIRouter

from app.api.portal import (
    auth,
    contracts,
    dashboard,
    file_feedback,
    files,
    invoices,
    messages,
    nps_feedback,
    payments,
    payments_history,
    projects,
)

router = APIRouter()

router.include_router(auth.router,      prefix="/auth",      tags=["portal-auth"])
router.include_router(dashboard.router, prefix="/dashboard", tags=["portal-dashboard"])
router.include_router(projects.router,  prefix="/projects",  tags=["portal-projects"])
router.include_router(files.router,     prefix="/files",     tags=["portal-files"])
# Feedback routes: /files/{file_id}/feedback — mounted at /files so URLs
# sit alongside the list/download endpoints (portal-242).
router.include_router(
    file_feedback.router, prefix="/files", tags=["portal-file-feedback"]
)
router.include_router(invoices.router,  prefix="/invoices",  tags=["portal-invoices"])
# Phase 11-002: client-facing contract list + view
router.include_router(contracts.router, prefix="/contracts", tags=["portal-contracts"])
# Phase 14-004: NPS feedback submission
router.include_router(nps_feedback.router, prefix="/feedback", tags=["portal-nps"])
router.include_router(payments.router,  prefix="/invoices",  tags=["portal-payments"])
router.include_router(
    payments_history.router, prefix="/payments", tags=["portal-payments-history"]
)
# Messages: mounted at /projects so routes resolve to
# /api/v1/portal/projects/{project_id}/messages (portal-231)
router.include_router(
    messages.router, prefix="/projects", tags=["portal-messages"]
)
