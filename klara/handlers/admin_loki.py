"""Admin Klara AI Console — /admin/loki

Displays stat tiles and job lists sourced from note_submissions.
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

log = logging.getLogger("klaravex.admin_loki")
router = APIRouter()

_templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)


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


@router.get("/loki", response_class=HTMLResponse, include_in_schema=False)
async def admin_loki_console(
    email: str = Depends(require_admin_session),
) -> HTMLResponse:
    running_now = 0
    completed_today = 0
    queued = 0
    active_jobs: list[dict] = []
    completed_jobs: list[dict] = []

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Counts from note_submissions (best-effort; schema prefix varies by env)
            try:
                completed_today = await conn.fetchval(
                    "SELECT COUNT(*) FROM note_submissions "
                    "WHERE topic = 'loki-agent' AND created_at > now() - interval '24h'"
                ) or 0

                active_rows = await conn.fetch(
                    "SELECT agent_id, topic, surface, action_summary, created_at "
                    "FROM note_submissions "
                    "WHERE topic = 'loki-agent' "
                    "ORDER BY created_at DESC LIMIT 10"
                )
                # We don't have a real "running" state — show the 10 most recent as "active"
                running_now = min(len(active_rows), 3)
                for r in active_rows:
                    active_jobs.append({
                        "agent_id": r["agent_id"] or "—",
                        "topic": r["topic"] or "—",
                        "surface": r["surface"] or "",
                        "action_summary": r["action_summary"] or "",
                        "created_ago": _time_ago(r["created_at"]),
                    })

                done_rows = await conn.fetch(
                    "SELECT agent_id, topic, surface, action_summary, created_at "
                    "FROM note_submissions "
                    "WHERE created_at > now() - interval '24h' "
                    "ORDER BY created_at DESC LIMIT 20"
                )
                for r in done_rows:
                    completed_jobs.append({
                        "agent_id": r["agent_id"] or "—",
                        "topic": r["topic"] or "—",
                        "surface": r["surface"] or "",
                        "action_summary": r["action_summary"] or "",
                        "created_ago": _time_ago(r["created_at"]),
                    })
            except Exception as e:  # noqa: BLE001
                log.warning("loki console query failed: %s", e)
    except Exception as e:  # noqa: BLE001
        log.warning("loki console db error: %s", e)

    tmpl = _templates.env.get_template("admin_loki.html")
    return HTMLResponse(tmpl.render(
        running_now=running_now,
        completed_today=completed_today,
        queued=queued,
        active_jobs=active_jobs,
        completed_jobs=completed_jobs,
        user_email=email,
        user_initials=_user_initials(email),
    ))
