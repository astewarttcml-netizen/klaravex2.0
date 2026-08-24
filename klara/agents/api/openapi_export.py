"""
app/api/openapi_export.py
──────────────────────────
phase15-004 — admin-gated OpenAPI schema export.

  GET /api/v1/admin/openapi.json   (X-API-Key)

The FastAPI app already serves /docs and /openapi.json publicly in dev
(disabled in production via APP_ENV). This endpoint exposes the schema
to operators with the management API key regardless of APP_ENV — useful
for external tooling (Postman, Insomnia, OpenAPI Generator).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.security import verify_api_key

router = APIRouter()


@router.get("/openapi.json")
async def export_openapi(
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> dict:
    return request.app.openapi()
