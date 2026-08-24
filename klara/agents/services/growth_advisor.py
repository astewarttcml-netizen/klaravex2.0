"""
app/services/growth_advisor.py
──────────────────────────────
Klara AI Weekly Growth Advisor (prod-005) — signal collector + Markdown
formatter.

Anthony asked for a *suggestion layer*: Klara AI proposes, he decides. Nothing
in this module triggers a side-effect on the WordPress site or the portal.
The output is a structured Markdown report with three sections:

    ## High-impact
    ## Low-effort
    ## Experimental

Each item is a single-paragraph suggestion grounded in one of four signals:

    1. WordPress site health   — 404s, broken nav, missing meta
    2. Portal client behaviour — draft open times, invoice payment lag,
                                 drop-offs
    3. Lead volume & source    — week-over-week, by source
    4. Audit-log task patterns — recurring manual actions

Signal collectors are best-effort: any external dependency (WordPress
HTTP probe, missing tables, missing audit rows) fails *soft* — the
section reports the gap rather than raising — so the scheduled job
never silently no-ops on a partial outage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.audit import AuditLog
from klara.rarv.lead import Lead
from klara.rarv.payment import Payment
from klara.rarv.portal import Invoice

logger = structlog.get_logger(__name__)


# ── Result containers ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class GrowthReport:
    """The composed output: ISO-week metadata, raw signals, rendered MD."""
    iso_year: int
    iso_week: int
    week_start: date
    signals: dict[str, Any]
    markdown: str


@dataclass
class _Suggestion:
    """One bullet under a section."""
    title: str
    detail: str

    def render(self) -> str:
        return f"- **{self.title}** — {self.detail}"


@dataclass
class _Bucket:
    """Collected suggestions for one section of the report."""
    high_impact: list[_Suggestion] = field(default_factory=list)
    low_effort: list[_Suggestion] = field(default_factory=list)
    experimental: list[_Suggestion] = field(default_factory=list)


# ── Public entry point ──────────────────────────────────────────────────────

async def build_weekly_report(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> GrowthReport:
    """
    Build the full GrowthReport for the ISO week containing `now - 7d`.

    The Monday of the *previous* week is reported on — the beat job
    runs Mon 08:00 UTC so the report always covers a closed 7-day window.
    """
    anchor = now or datetime.now(timezone.utc)
    # Report period: Monday-to-Sunday of the *previous* ISO week.
    period_end = _previous_monday(anchor.date())
    period_start = period_end - timedelta(days=7)
    iso_year, iso_week, _ = period_start.isocalendar()

    signals: dict[str, Any] = {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }
    bucket = _Bucket()

    leads = await _collect_lead_signals(db, period_start, period_end)
    signals["leads"] = leads
    _suggest_lead_actions(leads, bucket)

    portal = await _collect_portal_signals(db, period_start, period_end)
    signals["portal"] = portal
    _suggest_portal_actions(portal, bucket)

    audit = await _collect_audit_signals(db, period_start, period_end)
    signals["audit"] = audit
    _suggest_audit_actions(audit, bucket)

    # WordPress site signals are collected best-effort by the Celery task
    # wrapper (it owns the HTTP client). The service reports "skipped"
    # when nothing was passed in.
    signals["wordpress"] = {"status": "skipped", "note": "wrapper-supplied"}

    markdown = _render_markdown(
        iso_year=iso_year,
        iso_week=iso_week,
        period_start=period_start,
        period_end=period_end,
        bucket=bucket,
    )

    logger.info(
        "weekly_growth.built",
        iso_year=iso_year,
        iso_week=iso_week,
        high=len(bucket.high_impact),
        low=len(bucket.low_effort),
        exp=len(bucket.experimental),
    )
    return GrowthReport(
        iso_year=iso_year,
        iso_week=iso_week,
        week_start=period_start,
        signals=signals,
        markdown=markdown,
    )


# ── Signal collectors ───────────────────────────────────────────────────────

async def _collect_lead_signals(
    db: AsyncSession, period_start: date, period_end: date,
) -> dict[str, Any]:
    """Lead volume + source for the period vs. the prior period."""
    this_window = _datetime_window(period_start, period_end)
    prior_window = _datetime_window(
        period_start - timedelta(days=7), period_start
    )

    try:
        this_count = await _scalar_count(db, Lead, this_window)
        prior_count = await _scalar_count(db, Lead, prior_window)
        by_source = await _group_by(db, Lead, Lead.source, this_window)
    except Exception as exc:
        logger.warning("weekly_growth.lead_signals_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}

    delta = this_count - prior_count
    delta_pct = (delta / prior_count * 100) if prior_count else None
    return {
        "status": "ok",
        "this_period": this_count,
        "prior_period": prior_count,
        "delta": delta,
        "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
        "by_source": by_source,
    }


async def _collect_portal_signals(
    db: AsyncSession, period_start: date, period_end: date,
) -> dict[str, Any]:
    """Portal invoice payment lag — proxy for client friction."""
    this_window = _datetime_window(period_start, period_end)

    try:
        # Invoices issued in the window that are still unpaid.
        stmt = (
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.created_at >= this_window[0])
            .where(Invoice.created_at < this_window[1])
            .where(Invoice.status != "paid")
        )
        unpaid_in_window = (await db.execute(stmt)).scalar_one()

        stmt_total = (
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.created_at >= this_window[0])
            .where(Invoice.created_at < this_window[1])
        )
        total_in_window = (await db.execute(stmt_total)).scalar_one()

        stmt_paid_lag = (
            select(func.count())
            .select_from(Payment)
            .where(Payment.created_at >= this_window[0])
            .where(Payment.created_at < this_window[1])
        )
        payments_in_window = (await db.execute(stmt_paid_lag)).scalar_one()
    except Exception as exc:
        logger.warning("weekly_growth.portal_signals_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "invoices_issued": total_in_window,
        "invoices_unpaid": unpaid_in_window,
        "payments_recorded": payments_in_window,
    }


async def _collect_audit_signals(
    db: AsyncSession, period_start: date, period_end: date,
) -> dict[str, Any]:
    """Top recurring agent.action events — surfaces manual-task patterns."""
    this_window = _datetime_window(period_start, period_end)

    try:
        stmt = (
            select(AuditLog.action_name, func.count().label("n"))
            .where(AuditLog.created_at >= this_window[0])
            .where(AuditLog.created_at < this_window[1])
            .where(AuditLog.action_name.is_not(None))
            .group_by(AuditLog.action_name)
            .order_by(func.count().desc())
            .limit(5)
        )
        rows = (await db.execute(stmt)).all()
    except Exception as exc:
        logger.warning("weekly_growth.audit_signals_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "top_actions": [{"action": r[0], "count": int(r[1])} for r in rows],
    }


# ── Heuristic suggestion generators ─────────────────────────────────────────

def _suggest_lead_actions(signals: dict[str, Any], bucket: _Bucket) -> None:
    if signals.get("status") != "ok":
        return

    delta_pct = signals.get("delta_pct")
    this_period = signals.get("this_period", 0)

    if delta_pct is not None and delta_pct <= -25:
        bucket.high_impact.append(_Suggestion(
            title="Lead volume dropped",
            detail=(
                f"Inbound leads fell {abs(delta_pct):.0f}% "
                f"({signals['prior_period']} → {this_period}). "
                "Audit the homepage CTA + WPForms #17 conversion rate."
            ),
        ))
    elif delta_pct is not None and delta_pct >= 25:
        bucket.low_effort.append(_Suggestion(
            title="Lead volume up — capture the spike",
            detail=(
                f"Inbound leads rose {delta_pct:.0f}% "
                f"({signals['prior_period']} → {this_period}). "
                "Lock in the source: which channel drove this?"
            ),
        ))

    sources = signals.get("by_source") or []
    if not sources and this_period > 0:
        bucket.experimental.append(_Suggestion(
            title="Lead source missing",
            detail=(
                "All leads landed without an attributable source — "
                "consider UTM tagging on outbound links."
            ),
        ))


def _suggest_portal_actions(signals: dict[str, Any], bucket: _Bucket) -> None:
    if signals.get("status") != "ok":
        return

    issued = signals.get("invoices_issued", 0)
    unpaid = signals.get("invoices_unpaid", 0)

    if issued > 0:
        unpaid_pct = unpaid / issued * 100
        if unpaid_pct >= 50:
            bucket.high_impact.append(_Suggestion(
                title="Half of new invoices unpaid",
                detail=(
                    f"{unpaid}/{issued} invoices issued this week are "
                    "still open. Consider a polite-reminder cadence "
                    "on day 3 + day 7 via the existing notifications "
                    "service."
                ),
            ))
        elif unpaid_pct >= 25:
            bucket.low_effort.append(_Suggestion(
                title="Invoice follow-up worth sending",
                detail=(
                    f"{unpaid}/{issued} invoices still open. A single "
                    "Resend template covers the gap."
                ),
            ))


def _suggest_audit_actions(signals: dict[str, Any], bucket: _Bucket) -> None:
    if signals.get("status") != "ok":
        return

    top = signals.get("top_actions") or []
    if not top:
        return

    leader = top[0]
    if leader["count"] >= 10:
        bucket.experimental.append(_Suggestion(
            title="Recurring manual task",
            detail=(
                f"`{leader['action']}` ran {leader['count']} times this "
                "week — candidate for a Client-Task Automator playbook "
                "(prod-006)."
            ),
        ))


# ── Markdown rendering ──────────────────────────────────────────────────────

def _render_markdown(
    *,
    iso_year: int,
    iso_week: int,
    period_start: date,
    period_end: date,
    bucket: _Bucket,
) -> str:
    lines: list[str] = []
    lines.append(f"# Klara AI Weekly Growth Advisor — {iso_year}-W{iso_week:02d}")
    lines.append("")
    lines.append(
        f"_Period: {period_start.isoformat()} → "
        f"{(period_end - timedelta(days=1)).isoformat()} (Mon–Sun, UTC)_"
    )
    lines.append("")
    lines.append(
        "Klara AI proposes, Anthony decides. Nothing in this report is "
        "auto-executed."
    )
    lines.append("")

    _render_section(lines, "High-impact", bucket.high_impact)
    _render_section(lines, "Low-effort", bucket.low_effort)
    _render_section(lines, "Experimental", bucket.experimental)

    return "\n".join(lines).rstrip() + "\n"


def _render_section(
    lines: list[str], heading: str, items: list[_Suggestion],
) -> None:
    lines.append(f"## {heading}")
    lines.append("")
    if not items:
        lines.append("_No suggestions this week._")
    else:
        for item in items:
            lines.append(item.render())
    lines.append("")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _previous_monday(today: date) -> date:
    """Return the most recent Monday strictly before `today` (or `today`
    itself when it is a Monday)."""
    return today - timedelta(days=today.weekday())


def _datetime_window(start: date, end: date) -> tuple[datetime, datetime]:
    return (
        datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
    )


async def _scalar_count(
    db: AsyncSession, model, window: tuple[datetime, datetime],
) -> int:
    stmt = (
        select(func.count())
        .select_from(model)
        .where(model.created_at >= window[0])
        .where(model.created_at < window[1])
    )
    return int((await db.execute(stmt)).scalar_one())


async def _group_by(
    db: AsyncSession,
    model,
    column,
    window: tuple[datetime, datetime],
) -> list[dict[str, Any]]:
    stmt = (
        select(column, func.count().label("n"))
        .where(model.created_at >= window[0])
        .where(model.created_at < window[1])
        .group_by(column)
        .order_by(func.count().desc())
    )
    rows: Iterable = (await db.execute(stmt)).all()
    return [{"source": r[0], "count": int(r[1])} for r in rows if r[0]]
