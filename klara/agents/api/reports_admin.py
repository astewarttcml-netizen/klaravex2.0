"""
app/api/reports_admin.py
─────────────────────────
Admin-only reporting endpoints.  All require API-key authentication.

GET /api/v1/admin/access-denials          — last N hours of portal access denials
GET /api/v1/admin/webhook-events          — last N hours of payment events
GET /api/v1/admin/failed-automations      — last N hours of failed agent actions
GET /api/v1/admin/health-check            — quick system health summary
GET /api/v1/admin/autonomy-metrics        — per-agent approval/rollback/error rates (phase3-003)
GET /api/v1/admin/outreach-analytics      — per-window cold-outreach funnel + rates (phase19-008)
GET /api/v1/admin/growth-reports          — list recent weekly growth reports
GET /api/v1/admin/growth-reports/{id}     — retrieve full report (markdown + signals)
POST /api/v1/admin/growth-reports/run     — on-demand trigger for the growth advisor

Query params (windowed endpoints):
  hours : int, default=24, max=168  — look-back window
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, select, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, Settings
from app.core.security import verify_api_key
from app.database import get_db
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.audit import AuditLog
from app.models.lead import Lead
from app.models.outreach_sequence import OutreachSequence, OutreachSequenceStatus
from app.models.payment import PaymentEvent
from app.models.prospected_lead import ProspectedLead
from app.models.weekly_growth_report import WeeklyGrowthReport

logger = structlog.get_logger(__name__)

router = APIRouter()

_MAX_HOURS = 168   # 1 week cap


def _since(hours: int) -> datetime:
    h = min(max(hours, 1), _MAX_HOURS)
    return datetime.now(timezone.utc) - timedelta(hours=h)


# ── 1. Access Denials ─────────────────────────────────────────────────────────

@router.get("/access-denials", dependencies=[Depends(verify_api_key)])
async def access_denials(
    hours: int = Query(default=24, ge=1, le=_MAX_HOURS),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """
    Return portal access denial events from audit_logs.
    Covers event_type in:
      portal.access_denied, portal.cross_client_access_attempt,
      auth.unauthorized, auth.forbidden
    """
    since = _since(hours)
    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.created_at >= since,
            or_(
                AuditLog.event_type == "portal.access_denied",
                AuditLog.event_type == "portal.cross_client_access_attempt",
                AuditLog.event_type == "auth.unauthorized",
                AuditLog.event_type == "auth.forbidden",
                AuditLog.success == False,  # noqa: E712
            ),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

    return {
        "hours": hours,
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "timestamp": r.created_at.isoformat(),
                "event_type": r.event_type,
                "agent_name": r.agent_name,
                "action_name": r.action_name,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "success": r.success,
                "error_message": r.error_message,
                "details": r.details,
                "lead_id": r.lead_id,
            }
            for r in rows
        ],
    }


# ── 2. Webhook Events ─────────────────────────────────────────────────────────

@router.get("/webhook-events", dependencies=[Depends(verify_api_key)])
async def webhook_events(
    hours: int = Query(default=24, ge=1, le=_MAX_HOURS),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """
    Return payment events (Stripe webhooks) from the payment_events table.
    """
    since = _since(hours)
    result = await db.execute(
        select(PaymentEvent)
        .where(PaymentEvent.processed_at >= since)
        .order_by(PaymentEvent.processed_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

    return {
        "hours": hours,
        "count": len(rows),
        "items": [
            {
                "id": str(r.id),
                "stripe_event_id": r.stripe_event_id,
                "stripe_event_id_short": r.stripe_event_id[:12] if r.stripe_event_id else "",
                "event_type": r.event_type,
                "new_status": r.new_status,
                "payment_id": str(r.payment_id) if r.payment_id else None,
                "processed_at": r.processed_at.isoformat(),
            }
            for r in rows
        ],
    }


# ── 3. Failed Automations ─────────────────────────────────────────────────────

@router.get("/failed-automations", dependencies=[Depends(verify_api_key)])
async def failed_automations(
    hours: int = Query(default=24, ge=1, le=_MAX_HOURS),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """
    Return audit_log rows where success=False (failed agent actions).
    """
    since = _since(hours)
    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.created_at >= since,
            AuditLog.success == False,  # noqa: E712
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

    return {
        "hours": hours,
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "timestamp": r.created_at.isoformat(),
                "event_type": r.event_type,
                "agent_name": r.agent_name,
                "action_name": r.action_name,
                "error_message": r.error_message,
                "details": r.details,
                "lead_id": r.lead_id,
                "approval_id": r.approval_id,
            }
            for r in rows
        ],
    }


# ── 4. Health Check ───────────────────────────────────────────────────────────

@router.get("/health-check", dependencies=[Depends(verify_api_key)])
async def health_check(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Quick system health summary for the incident runbook "identify" step.

    Returns:
      db                — "ok" if the database is reachable, "error" otherwise
      celery            — "ok" placeholder (workers are external processes);
                          use `docker ps` to verify loki_celery_worker is running
      stripe_configured — true when STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
                          and STRIPE_PUBLISHABLE_KEY are all set in .env
      last_webhook_event — ISO timestamp of the most recent PaymentEvent row,
                           or null if none exist
      pending_approvals  — count of ApprovalRequest rows with status=pending
    """
    # ── DB reachability ───────────────────────────────────────────────────────
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("health_check.db_error", error=str(exc))
        db_status = "error"

    # ── Last webhook event ────────────────────────────────────────────────────
    last_webhook_event: Optional[str] = None
    try:
        result = await db.execute(
            select(PaymentEvent.processed_at)
            .order_by(PaymentEvent.processed_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            last_webhook_event = row.isoformat()
    except Exception as exc:
        logger.warning("health_check.webhook_query_error", error=str(exc))

    # ── Pending approvals count ───────────────────────────────────────────────
    pending_approvals = 0
    try:
        count_result = await db.execute(
            select(func.count(ApprovalRequest.id)).where(
                ApprovalRequest.status == ApprovalStatus.pending
            )
        )
        pending_approvals = count_result.scalar_one() or 0
    except Exception as exc:
        logger.warning("health_check.approvals_query_error", error=str(exc))

    return {
        "db": db_status,
        "celery": "ok",
        "stripe_configured": settings.stripe_configured,
        "last_webhook_event": last_webhook_event,
        "pending_approvals": pending_approvals,
    }


# ── 5. Autonomy Metrics (phase3-003) ──────────────────────────────────────────
#
# Per-agent rolling-window scorecard used to gate the PRD §17 Phase 3 decision
# to promote an action from P3/P4 (manual approval) to P2 (auto-execute).
#
# For each agent observed in audit_logs or approval_requests within the window
# we compute:
#
#   total_actions       — audit_log rows where agent_name = X
#   success_actions     — audit_log rows where success = TRUE
#   error_actions       — audit_log rows where success = FALSE
#   error_rate          — error_actions / total_actions  (0.0 if no actions)
#   rollback_actions    — audit_log rows where event_type ILIKE '%rollback%' OR '%undo%'
#   rollback_rate       — rollback_actions / total_actions
#   approvals_total     — approval_requests rows where requested_by_agent = X AND status in (approved, rejected, auto_approved)
#   approvals_approved  — approval_requests rows with status in (approved, auto_approved)
#   approvals_rejected  — approval_requests rows with status = rejected
#   approval_rate       — approvals_approved / approvals_total
#   status_color        — 'green' if approval_rate ≥ 0.90 AND error_rate ≤ 0.05
#                          AND rollback_rate ≤ 0.02
#                         'amber' if approval_rate ≥ 0.70
#                         'red'   otherwise
#                         'no_data' if total_actions == 0 AND approvals_total == 0

@router.get("/autonomy-metrics", dependencies=[Depends(verify_api_key)])
async def autonomy_metrics(
    days: int = Query(default=30, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
):
    """
    Return per-agent autonomy metrics over a trailing window.

    Phase 3 gate: action promotion (P3 → P2 auto) requires status_color == 'green'
    over a 30-day window. See PRD §17 — Expanded autonomy.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # ── 1. audit_log aggregation per agent ──
    audit_rows = await db.execute(
        select(
            AuditLog.agent_name,
            func.count().label("total_actions"),
            func.sum(case((AuditLog.success.is_(True), 1), else_=0)).label("success_actions"),
            func.sum(case((AuditLog.success.is_(False), 1), else_=0)).label("error_actions"),
            func.sum(
                case(
                    (
                        or_(
                            AuditLog.event_type.ilike("%rollback%"),
                            AuditLog.event_type.ilike("%undo%"),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("rollback_actions"),
        )
        .where(AuditLog.created_at >= cutoff)
        .where(AuditLog.agent_name.is_not(None))
        .group_by(AuditLog.agent_name)
    )

    audit_by_agent: dict[str, dict] = {}
    for row in audit_rows:
        audit_by_agent[row.agent_name] = {
            "total_actions":    int(row.total_actions or 0),
            "success_actions":  int(row.success_actions or 0),
            "error_actions":    int(row.error_actions or 0),
            "rollback_actions": int(row.rollback_actions or 0),
        }

    # ── 2. approval_request aggregation per agent ──
    APPROVED_VALUES = (ApprovalStatus.approved.value, ApprovalStatus.auto_approved.value)
    REJECTED_VALUES = (ApprovalStatus.rejected.value,)
    TERMINAL_VALUES = APPROVED_VALUES + REJECTED_VALUES

    approval_rows = await db.execute(
        select(
            ApprovalRequest.requested_by_agent,
            func.count().label("approvals_total"),
            func.sum(case((ApprovalRequest.status.in_(APPROVED_VALUES), 1), else_=0)).label("approvals_approved"),
            func.sum(case((ApprovalRequest.status.in_(REJECTED_VALUES), 1), else_=0)).label("approvals_rejected"),
        )
        .where(ApprovalRequest.created_at >= cutoff)
        .where(ApprovalRequest.status.in_(TERMINAL_VALUES))
        .group_by(ApprovalRequest.requested_by_agent)
    )

    approval_by_agent: dict[str, dict] = {}
    for row in approval_rows:
        approval_by_agent[row.requested_by_agent] = {
            "approvals_total":    int(row.approvals_total or 0),
            "approvals_approved": int(row.approvals_approved or 0),
            "approvals_rejected": int(row.approvals_rejected or 0),
        }

    # ── 3. Merge + compute rates + status_color ──
    all_agents = sorted(set(audit_by_agent.keys()) | set(approval_by_agent.keys()))

    agents = []
    for name in all_agents:
        a = audit_by_agent.get(name, {})
        p = approval_by_agent.get(name, {})
        total       = a.get("total_actions",    0)
        success     = a.get("success_actions",  0)
        errors      = a.get("error_actions",    0)
        rollbacks   = a.get("rollback_actions", 0)
        appr_total  = p.get("approvals_total",    0)
        appr_appr   = p.get("approvals_approved", 0)
        appr_rej    = p.get("approvals_rejected", 0)

        error_rate    = (errors    / total)      if total      > 0 else 0.0
        rollback_rate = (rollbacks / total)      if total      > 0 else 0.0
        approval_rate = (appr_appr / appr_total) if appr_total > 0 else 0.0

        # Colour gate — order matters: no_data first, then green / amber / red
        if total == 0 and appr_total == 0:
            color = "no_data"
        elif appr_total == 0:
            # We have actions but no approval traffic — only error/rollback signal.
            # Don't claim green without approval evidence.
            color = "amber" if error_rate <= 0.05 and rollback_rate <= 0.02 else "red"
        elif approval_rate >= 0.90 and error_rate <= 0.05 and rollback_rate <= 0.02:
            color = "green"
        elif approval_rate >= 0.70:
            color = "amber"
        else:
            color = "red"

        agents.append({
            "agent_name":         name,
            "total_actions":      total,
            "success_actions":    success,
            "error_actions":      errors,
            "error_rate":         round(error_rate, 4),
            "rollback_actions":   rollbacks,
            "rollback_rate":      round(rollback_rate, 4),
            "approvals_total":    appr_total,
            "approvals_approved": appr_appr,
            "approvals_rejected": appr_rej,
            "approval_rate":      round(approval_rate, 4),
            "status_color":       color,
        })

    # Sort: green > amber > red > no_data, then by approval_rate desc, then by total_actions desc
    color_order = {"green": 0, "amber": 1, "red": 2, "no_data": 3}
    agents.sort(key=lambda x: (color_order[x["status_color"]], -x["approval_rate"], -x["total_actions"]))

    return {
        "window_days": days,
        "since":       cutoff.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agents":      agents,
        "summary": {
            "total_agents": len(agents),
            "green":   sum(1 for a in agents if a["status_color"] == "green"),
            "amber":   sum(1 for a in agents if a["status_color"] == "amber"),
            "red":     sum(1 for a in agents if a["status_color"] == "red"),
            "no_data": sum(1 for a in agents if a["status_color"] == "no_data"),
        },
    }


# ── 5b. Outreach Analytics (phase19-008) ──────────────────────────────────────
#
# Per-window cold-outreach funnel for the multi-touch cadence (phase3-001 +
# phase19-007). Counts sequences started in the window, sends per step
# (1..MAX_STEP), engagement signals (opens, clicks, replies, unsubscribes),
# suppressions (phase19-006 reply suppression + engagement-arrived
# suppression), and bookings (Calendly meeting_booked_at on a Lead that
# was promoted from a ProspectedLead in the window).
#
# Honest scope notes
# ──────────────────
# • Language split (EN/DE) is NOT included. Outreach is always generated
#   bilingually (phase3-007 BilingualOutreachAgent) — no `sent_language`
#   column on ProspectedLead or OutreachSequence exists yet. When that
#   column lands, add a `by_language` block here. Out of scope for v1.
# • "Opens" count is `prospect.opened_at != NULL within window`. The
#   pixel deduper (phase3-002) ensures one open per unique-recipient-day.

@router.get("/outreach-analytics", dependencies=[Depends(verify_api_key)])
async def outreach_analytics(
    days: int = Query(default=30, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
):
    """
    Cold-outreach funnel + rates over a trailing window.

    The window applies to:
      - ProspectedLead.outreach_sent_at (sequences started, opens, clicks,
        replies, unsubscribes are filtered by the column's own timestamp
        being inside the window).
      - OutreachSequence.sent_at for per-step send counts.
      - Lead.meeting_booked_at for bookings.

    Rates are denominated by sequences_started (sequences that produced an
    initial cold email in the window). Returns 0.0 cleanly when the window
    has zero starts.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # ── 1. Per-prospect engagement aggregates ──
    # Single scan over ProspectedLead with conditional COUNTs — cheaper than
    # five separate queries and reads cleanly from the row.
    p_row = (await db.execute(
        select(
            func.count(ProspectedLead.id).filter(
                ProspectedLead.outreach_sent_at.is_not(None),
                ProspectedLead.outreach_sent_at >= cutoff,
            ).label("sequences_started"),
            func.count(ProspectedLead.id).filter(
                ProspectedLead.opened_at.is_not(None),
                ProspectedLead.opened_at >= cutoff,
            ).label("opens"),
            func.count(ProspectedLead.id).filter(
                ProspectedLead.last_clicked_at.is_not(None),
                ProspectedLead.last_clicked_at >= cutoff,
            ).label("clicks"),
            func.count(ProspectedLead.id).filter(
                ProspectedLead.replied_at.is_not(None),
                ProspectedLead.replied_at >= cutoff,
            ).label("replies"),
            func.count(ProspectedLead.id).filter(
                ProspectedLead.unsubscribed_at.is_not(None),
                ProspectedLead.unsubscribed_at >= cutoff,
            ).label("unsubscribes"),
        )
    )).one()

    # ── 2. Sends per step from OutreachSequence ──
    step_rows = (await db.execute(
        select(
            OutreachSequence.step_number,
            func.count(OutreachSequence.id).label("n"),
        ).where(
            OutreachSequence.status == OutreachSequenceStatus.sent,
            OutreachSequence.sent_at.is_not(None),
            OutreachSequence.sent_at >= cutoff,
        ).group_by(OutreachSequence.step_number)
    )).all()
    sends_by_step = {int(r.step_number): int(r.n or 0) for r in step_rows}
    # step_1_sent is the initial cold email — recorded on ProspectedLead
    # directly, not as an OutreachSequence row.
    step_1_sent = int(p_row.sequences_started or 0)

    # ── 3. Suppressions across all steps ──
    suppressions_q = await db.execute(
        select(func.count(OutreachSequence.id))
        .where(
            OutreachSequence.status == OutreachSequenceStatus.suppressed,
            OutreachSequence.updated_at >= cutoff,
        )
    )
    suppressions = int(suppressions_q.scalar_one() or 0)

    # ── 4. Bookings — Lead.meeting_booked_at where the lead was promoted
    #         from a prospect (ProspectedLead.converted_lead_id IS NOT NULL).
    bookings_q = await db.execute(
        select(func.count(Lead.id))
        .join(ProspectedLead, ProspectedLead.converted_lead_id == Lead.id)
        .where(
            Lead.meeting_booked_at.is_not(None),
            Lead.meeting_booked_at >= cutoff,
        )
    )
    bookings = int(bookings_q.scalar_one() or 0)

    sequences_started = int(p_row.sequences_started or 0)
    opens             = int(p_row.opens or 0)
    clicks            = int(p_row.clicks or 0)
    replies           = int(p_row.replies or 0)
    unsubscribes      = int(p_row.unsubscribes or 0)

    def _rate(numer: int) -> float:
        return round(numer / sequences_started, 4) if sequences_started > 0 else 0.0

    return {
        "window_days":  days,
        "since":        cutoff.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "funnel": {
            "sequences_started": sequences_started,
            "step_1_sent":       step_1_sent,
            "step_2_sent":       sends_by_step.get(2, 0),
            "step_3_sent":       sends_by_step.get(3, 0),
            "step_4_sent":       sends_by_step.get(4, 0),
            "opens":             opens,
            "clicks":            clicks,
            "replies":           replies,
            "unsubscribes":      unsubscribes,
            "suppressions":      suppressions,
            "bookings":          bookings,
        },
        "rates": {
            "open_rate":        _rate(opens),
            "click_rate":       _rate(clicks),
            "reply_rate":       _rate(replies),
            "step_2_send_rate": _rate(sends_by_step.get(2, 0)),
            "step_3_send_rate": _rate(sends_by_step.get(3, 0)),
            "step_4_send_rate": _rate(sends_by_step.get(4, 0)),
            "booking_rate":     _rate(bookings),
            "unsubscribe_rate": _rate(unsubscribes),
        },
    }


# ── 6. Weekly Growth Reports — list ───────────────────────────────────────────

@router.get("/growth-reports", dependencies=[Depends(verify_api_key)])
async def list_growth_reports(
    limit: int = Query(default=12, ge=1, le=52),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a paginated summary of recent weekly growth reports, newest first.

    Each item contains the period metadata and delivery status but omits the
    full Markdown body — use GET /growth-reports/{id} to fetch that.
    """
    result = await db.execute(
        select(WeeklyGrowthReport)
        .order_by(WeeklyGrowthReport.week_start.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()

    count_result = await db.execute(
        select(func.count(WeeklyGrowthReport.id))
    )
    total = count_result.scalar_one() or 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": r.id,
                "iso_year": r.iso_year,
                "iso_week": r.iso_week,
                "week_start": r.week_start.isoformat(),
                "triggered_by": r.triggered_by,
                "emailed_to": r.emailed_to,
                "emailed_at": r.emailed_at.isoformat() if r.emailed_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


# ── 7. Weekly Growth Reports — detail ─────────────────────────────────────────

@router.get("/growth-reports/{report_id}", dependencies=[Depends(verify_api_key)])
async def get_growth_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return the full weekly growth report including the rendered Markdown body
    and the raw signals JSON snapshot used to produce it.
    """
    # Validate UUID format before hitting the DB — PostgreSQL raises DataError
    # on cast failure, which the global handler would surface as a 500.
    try:
        UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Growth report not found")

    result = await db.execute(
        select(WeeklyGrowthReport).where(WeeklyGrowthReport.id == report_id)
    )
    row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Growth report not found")

    return {
        "id": row.id,
        "iso_year": row.iso_year,
        "iso_week": row.iso_week,
        "week_start": row.week_start.isoformat(),
        "triggered_by": row.triggered_by,
        "report_markdown": row.report_markdown,
        "signals": row.signals,
        "emailed_to": row.emailed_to,
        "emailed_at": row.emailed_at.isoformat() if row.emailed_at else None,
        "created_at": row.created_at.isoformat(),
    }


# ── 8. Weekly Growth Reports — on-demand trigger ──────────────────────────────

@router.post("/growth-reports/run", dependencies=[Depends(verify_api_key)])
async def trigger_growth_report():
    """
    Queue an immediate run of the Weekly Growth Advisor.

    The task is dispatched to the Celery default queue and returns the
    Celery task ID for status tracking. The advisor will upsert a row for
    the current ISO week (idempotent — re-running the same week overwrites
    the previous row) and email the report to the configured recipient.

    Returns: {"task_id": "<celery-uuid>", "status": "queued"}
    """
    # Import here to avoid circular-import at module load time; the Celery
    # app is fully initialised by the time any request arrives.
    from app.tasks.weekly_growth_advisor import run_weekly_growth_advisor

    result = run_weekly_growth_advisor.apply_async(
        kwargs={"triggered_by": "admin_api"},
        queue="default",
    )

    logger.info(
        "growth_report.manual_trigger",
        task_id=result.id,
    )

    return {"task_id": result.id, "status": "queued"}
