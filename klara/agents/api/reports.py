"""
app/api/reports.py
───────────────────
Daily report management endpoints.

GET  /api/v1/reports/          — list generated reports (auth required)
GET  /api/v1/reports/{id}      — get report with full markdown (auth required)
POST /api/v1/reports/trigger   — generate a report now (creates background task)

Typical automated flow:
  Celery Beat fires at 07:00 Europe/Berlin
  → app.tasks.daily_report.generate_daily_report
  → DailyReportAgent gathers stats, formats markdown
  → DailyReport row saved to DB
  → HTML email sent to approval_notify_email

Manual flow (this endpoint):
  POST /api/v1/reports/trigger  {"report_date": "2026-05-07"}
  → enqueues generate_daily_report task
  → returns {"status": "queued", "task_id": "..."}
"""
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, Settings
from app.core.security import verify_api_key
from app.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


class TriggerReportRequest(BaseModel):
    report_date: Optional[str] = None   # ISO "YYYY-MM-DD"; defaults to yesterday
    triggered_by: str = "api.manual"


@router.get("/", dependencies=[Depends(verify_api_key)])
async def list_reports(
    limit: int = 30,
    report_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List generated reports, newest first."""
    from app.models.report import DailyReport

    query = select(DailyReport).order_by(DailyReport.created_at.desc()).limit(limit)
    if report_type:
        query = query.where(DailyReport.report_type == report_type)

    result = await db.execute(query)
    reports = result.scalars().all()

    return [
        {
            "id": r.id,
            "report_date": r.report_date.isoformat(),
            "report_type": r.report_type,
            "triggered_by": r.triggered_by,
            "emailed_to": r.emailed_to,
            "emailed_at": r.emailed_at.isoformat() if r.emailed_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in reports
    ]


@router.get("/{report_id}", dependencies=[Depends(verify_api_key)])
async def get_report(report_id: str, db: AsyncSession = Depends(get_db)):
    """Get a report including full markdown content and raw stats."""
    from app.models.report import DailyReport

    result = await db.execute(
        select(DailyReport).where(DailyReport.id == report_id)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found.")

    return {
        "id": r.id,
        "report_date": r.report_date.isoformat(),
        "report_type": r.report_type,
        "triggered_by": r.triggered_by,
        "report_markdown": r.report_markdown,
        "stats_json": r.stats_json,
        "emailed_to": r.emailed_to,
        "emailed_at": r.emailed_at.isoformat() if r.emailed_at else None,
        "created_at": r.created_at.isoformat(),
    }


@router.post("/trigger", dependencies=[Depends(verify_api_key)])
async def trigger_report(
    req: TriggerReportRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Trigger a report generation immediately.

    Enqueues the Celery task and returns immediately.
    The report will be saved to the DB and emailed when complete.
    """
    from app.tasks.daily_report import generate_daily_report

    task = generate_daily_report.apply_async(
        kwargs={
            "report_date": req.report_date,
            "triggered_by": req.triggered_by,
        },
        queue="default",
    )

    logger.info(
        "reports.trigger",
        task_id=task.id,
        report_date=req.report_date,
        triggered_by=req.triggered_by,
    )

    return {
        "status": "queued",
        "task_id": task.id,
        "report_date": req.report_date or "yesterday",
        "message": (
            "Report generation queued. The report will be saved to the database "
            "and emailed to the admin when complete. "
            f"Check GET /api/v1/reports/ in a few seconds."
        ),
    }
