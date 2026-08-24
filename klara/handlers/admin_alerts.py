"""Admin Alerts view — /admin/alerts

Severity-bucketed ticket list sourced from klaravex_tickets.
Auth via session cookie (require_admin_session dependency).
"""

import datetime
import logging
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .lib.admin_auth import require_admin_session
from .lib.db import get_pool

log = logging.getLogger("klaravex.admin_alerts")
router = APIRouter()

_templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)

_STRIPE = {
    "critical": "crit",
    "escalated": "crit",
    "warning": "warn",
    "in_progress": "warn",
    "open": "info",
    "new": "info",
}

_PILL = {
    "critical": "r",
    "escalated": "r",
    "warning": "a",
    "in_progress": "a",
    "open": "b",
    "new": "b",
    "resolved": "g",
    "closed": "n",
}


def _time_ago(dt: datetime.datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    delta = datetime.datetime.now(datetime.timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _user_initials(email: str) -> str:
    name = email.split("@")[0]
    parts = name.replace(".", " ").replace("_", " ").split()
    return "".join(p[0].upper() for p in parts[:2]) or "A"


@router.get("/alerts", response_class=HTMLResponse, include_in_schema=False)
async def admin_alerts(
    email: str = Depends(require_admin_session),
) -> HTMLResponse:
    counts = {"crit": 0, "warn": 0, "open": 0, "total": 0}
    tickets: list[dict] = []

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT id, title, status, client_name, created_at "
                    "FROM klaravex_tickets "
                    "WHERE status NOT IN ('resolved','closed') "
                    "ORDER BY "
                    "  CASE LOWER(status) "
                    "    WHEN 'critical' THEN 1 WHEN 'escalated' THEN 1 "
                    "    WHEN 'warning' THEN 2 WHEN 'in_progress' THEN 2 "
                    "    ELSE 3 END, "
                    "  created_at DESC "
                    "LIMIT 50"
                )
                for r in rows:
                    status = (r["status"] or "open").lower()
                    stripe_key = _STRIPE.get(status, "info")
                    pill_key = _PILL.get(status, "b")
                    tickets.append({
                        "title": r["title"] or "(untitled)",
                        "status": r["status"] or "open",
                        "client_name": r["client_name"] or "",
                        "stripe_class": stripe_key,
                        "pill_class": pill_key,
                        "created_ago": _time_ago(r["created_at"]),
                    })
                    if stripe_key == "crit":
                        counts["crit"] += 1
                    elif stripe_key == "warn":
                        counts["warn"] += 1
                    else:
                        counts["open"] += 1
                counts["total"] = len(tickets)
            except Exception as e:  # noqa: BLE001
                log.warning("alerts query failed: %s", e)
    except Exception as e:  # noqa: BLE001
        log.warning("alerts db error: %s", e)

    tmpl = _templates.env.get_template("admin_alerts.html")
    return HTMLResponse(tmpl.render(
        counts=counts,
        tickets=tickets,
        user_email=email,
        user_initials=_user_initials(email),
    ))
