"""
app/api/outreach_analytics.py
─────────────────────────────
phase19-008 -- per-sequence open/reply/conversion analytics endpoint.

Closing the gap loki-mode's PRD claimed (the route was missing in prod).
Joins outreach_sequences with the engagement signals already captured on
prospected_leads and returns per-step funnel metrics.

GET /api/v1/admin/outreach-analytics
GET /api/v1/admin/outreach-analytics?since_days=30
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("", dependencies=[Depends(verify_api_key)])
async def outreach_analytics(
    since_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Returns per-step outreach funnel metrics for the trailing N days.

    Shape:
    {
      "window_days": 30,
      "computed_at": "...",
      "per_step": [
        {
          "step_number": 1,
          "total":      <int>,
          "sent":       <int>,
          "opened":     <int>,
          "clicked":    <int>,
          "replied":    <int>,
          "unsubscribed": <int>,
          "converted":  <int>,
          "open_rate":       <0..1>,
          "click_rate":      <0..1>,
          "reply_rate":      <0..1>,
          "conversion_rate": <0..1>
        }
      ],
      "totals": { same fields, summed across steps }
    }
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    # We compute counts off prospected_leads engagement (opened_at, last_clicked_at,
    # replied_at, unsubscribed_at) to avoid duplicating event-state in outreach_sequences.
    rows = (
        await db.execute(
            text(
                """
                SELECT
                  os.step_number,
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE os.status = 'sent')     AS sent,
                  COUNT(*) FILTER (WHERE pl.opened_at IS NOT NULL) AS opened,
                  COUNT(*) FILTER (WHERE pl.last_clicked_at IS NOT NULL) AS clicked,
                  COUNT(*) FILTER (WHERE pl.replied_at IS NOT NULL) AS replied,
                  COUNT(*) FILTER (WHERE pl.unsubscribed_at IS NOT NULL) AS unsubscribed,
                  COUNT(*) FILTER (WHERE pl.converted_lead_id IS NOT NULL) AS converted
                FROM outreach_sequences os
                LEFT JOIN prospected_leads pl ON pl.id = os.prospect_id
                WHERE os.scheduled_at >= :cutoff
                GROUP BY os.step_number
                ORDER BY os.step_number
                """
            ),
            {"cutoff": cutoff},
        )
    ).fetchall()

    def _rate(num: int, den: int) -> float:
        return round(num / den, 4) if den else 0.0

    per_step = []
    grand = {
        "total": 0, "sent": 0, "opened": 0, "clicked": 0, "replied": 0,
        "unsubscribed": 0, "converted": 0,
    }
    for r in rows:
        step, total, sent, opened, clicked, replied, unsubscribed, converted = r
        per_step.append({
            "step_number": step,
            "total": total,
            "sent": sent,
            "opened": opened,
            "clicked": clicked,
            "replied": replied,
            "unsubscribed": unsubscribed,
            "converted": converted,
            "open_rate":       _rate(opened, sent),
            "click_rate":      _rate(clicked, sent),
            "reply_rate":      _rate(replied, sent),
            "conversion_rate": _rate(converted, sent),
        })
        grand["total"]        += total
        grand["sent"]         += sent
        grand["opened"]       += opened
        grand["clicked"]      += clicked
        grand["replied"]      += replied
        grand["unsubscribed"] += unsubscribed
        grand["converted"]    += converted

    totals = {
        **grand,
        "open_rate":       _rate(grand["opened"],     grand["sent"]),
        "click_rate":      _rate(grand["clicked"],    grand["sent"]),
        "reply_rate":      _rate(grand["replied"],    grand["sent"]),
        "conversion_rate": _rate(grand["converted"],  grand["sent"]),
    }

    return {
        "window_days": since_days,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "per_step": per_step,
        "totals": totals,
    }
