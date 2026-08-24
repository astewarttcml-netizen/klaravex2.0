"""
app/agents/kpi_dashboard.py
────────────────────────────
KPIDashboardAgent — returns a point-in-time snapshot of core business KPIs
for Klaravex.

Permission level: P1 (read-only, no side-effects, no email).

All computations are performed in a single async execution pass to keep
latency low.  The agent is designed to back a dashboard endpoint or a Celery
beat task that caches the result for the admin UI.

Input keys (all optional):
  window_days — int (default 30): lookback window for time-bounded metrics
                such as ``leads_last_Nd``.  Other all-time metrics are always
                computed against the full dataset.

Output keys (under ``kpis``):
  total_leads              — count of all leads (excluding anonymised)
  leads_last_Nd            — leads created in the last window_days
  pipeline_count           — leads in qualified / discovery_done / proposal_sent
  pipeline_value_estimate  — pipeline_count × avg paid invoice amount (EUR float)
  conversion_rate_pct      — (won / (won + lost + proposal_sent + discovery_done
                              + qualified)) × 100, rounded to 1 dp
  avg_deal_size_eur        — avg amount_eur from paid invoices (float)
  total_revenue_eur        — sum amount_eur from paid invoices (float)
  outstanding_eur          — sum amount_eur from unpaid + reminded invoices (float)
  outstanding_count        — count of unpaid + reminded invoices
  avg_satisfaction         — mean satisfaction_score (float|None)
  nps_count                — count of leads with satisfaction_score recorded
  window_days              — echoed back from input (default 30)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.invoice import Invoice, InvoiceStatus
from klara.rarv.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")

_PIPELINE_STATUSES = [
    LeadStatus.qualified.value,
    LeadStatus.discovery_done.value,
    LeadStatus.proposal_sent.value,
]

# Statuses considered when computing the conversion rate denominator:
# all leads that reached at least "qualified" (i.e. passed initial screening)
_CONVERSION_DENOMINATOR_STATUSES = [
    LeadStatus.qualified.value,
    LeadStatus.discovery_done.value,
    LeadStatus.proposal_sent.value,
    LeadStatus.won.value,
    LeadStatus.lost.value,
]


class KPIDashboardAgent(BaseAgent):
    """
    Returns a comprehensive, point-in-time KPI snapshot for Klaravex.

    Metrics span both all-time and a configurable rolling window (default: last
    30 days).  Designed for low-latency dashboard calls — all DB work is
    performed with aggregation at the DB layer wherever possible, with Python
    fallback only where SQLAlchemy aggregate functions would be overly complex.

    No emails are sent and no data is mutated.  Safe to call at any frequency.

    Key computed metrics:

      conversion_rate_pct
          Won leads divided by all leads that progressed past "new" into the
          qualified+ funnel.  Excludes disqualified and anonymised from the
          denominator to avoid penalising the rate for leads that were never
          real opportunities.

      pipeline_value_estimate
          Rough EUR value of the in-flight pipeline, computed as
          ``pipeline_count × avg_paid_invoice_amount``.  Returns 0 when no
          paid invoices exist yet (no historical deal size to extrapolate from).

      avg_satisfaction / nps_count
          Derived from ``Lead.satisfaction_score`` which is written by
          ClientSatisfactionAgent after the client clicks an NPS survey link.
    """

    name = "kpi_dashboard"
    description = (
        "Snapshot of current business KPIs: pipeline count/value, conversion "
        "rates, average deal size, satisfaction score, and MRR estimate."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )
        db = context.db

        window_days: int = int(input_data.get("window_days", 30))
        if window_days < 1:
            return AgentResult.fail(error="window_days must be >= 1")

        now_utc = datetime.now(timezone.utc)
        window_start = now_utc - timedelta(days=window_days)
        generated_at = now_utc.isoformat()

        log.info("kpi_dashboard.generating", window_days=window_days)

        try:
            kpis = await self._compute_kpis(db, window_start, window_days)
        except Exception as exc:
            log.error("kpi_dashboard.error", error=str(exc), exc_info=True)
            return AgentResult.fail(error=f"KPI computation failed: {exc}")

        log.info("kpi_dashboard.complete", pipeline=kpis.get("pipeline_count"))

        return AgentResult.ok(
            output={
                "kpis": kpis,
                "generated_at": generated_at,
                "window_days": window_days,
            }
        )

    # ── Core computation ──────────────────────────────────────────────────────

    async def _compute_kpis(
        self,
        db,
        window_start: datetime,
        window_days: int,
    ) -> dict:
        kpis: dict = {}

        # ── Lead counts ───────────────────────────────────────────────────────

        # Total leads (exclude anonymised — PII wiped, not meaningful for KPIs)
        total_leads_q = await db.execute(
            select(func.count()).where(
                Lead.status != LeadStatus.anonymised.value
            )
        )
        kpis["total_leads"] = total_leads_q.scalar() or 0

        # Leads created in the rolling window
        leads_window_q = await db.execute(
            select(func.count()).where(
                Lead.created_at >= window_start,
                Lead.status != LeadStatus.anonymised.value,
            )
        )
        kpis[f"leads_last_{window_days}d"] = leads_window_q.scalar() or 0

        # ── Pipeline ──────────────────────────────────────────────────────────

        pipeline_q = await db.execute(
            select(func.count()).where(Lead.status.in_(_PIPELINE_STATUSES))
        )
        kpis["pipeline_count"] = pipeline_q.scalar() or 0

        # Per-stage breakdown
        for status_val in _PIPELINE_STATUSES:
            stage_q = await db.execute(
                select(func.count()).where(Lead.status == status_val)
            )
            kpis[f"pipeline_{status_val}"] = stage_q.scalar() or 0

        # ── Invoice aggregates ────────────────────────────────────────────────

        # Average paid invoice amount (used for pipeline value estimate)
        avg_paid_q = await db.execute(
            select(func.avg(Invoice.amount_eur)).where(
                Invoice.status == InvoiceStatus.paid.value
            )
        )
        avg_paid_raw = avg_paid_q.scalar()
        avg_deal_size = float(avg_paid_raw) if avg_paid_raw is not None else 0.0
        kpis["avg_deal_size_eur"] = round(avg_deal_size, 2)

        # Total revenue (paid invoices, all time)
        total_rev_q = await db.execute(
            select(func.sum(Invoice.amount_eur)).where(
                Invoice.status == InvoiceStatus.paid.value
            )
        )
        kpis["total_revenue_eur"] = round(
            float(total_rev_q.scalar() or Decimal("0.00")), 2
        )

        # Paid invoice count
        paid_count_q = await db.execute(
            select(func.count()).where(Invoice.status == InvoiceStatus.paid.value)
        )
        kpis["paid_invoice_count"] = paid_count_q.scalar() or 0

        # Outstanding (unpaid + reminded)
        outstanding_q = await db.execute(
            select(func.sum(Invoice.amount_eur), func.count()).where(
                Invoice.status.in_([
                    InvoiceStatus.unpaid.value,
                    InvoiceStatus.reminded.value,
                ])
            )
        )
        outstanding_row = outstanding_q.one()
        kpis["outstanding_eur"] = round(
            float(outstanding_row[0] or Decimal("0.00")), 2
        )
        kpis["outstanding_count"] = outstanding_row[1] or 0

        # ── Pipeline value estimate ───────────────────────────────────────────

        kpis["pipeline_value_estimate"] = round(
            kpis["pipeline_count"] * avg_deal_size, 2
        )

        # ── Conversion rate ───────────────────────────────────────────────────

        # Denominator: all leads that reached qualified or beyond
        denom_q = await db.execute(
            select(func.count()).where(
                Lead.status.in_(_CONVERSION_DENOMINATOR_STATUSES)
            )
        )
        denom = denom_q.scalar() or 0

        won_q = await db.execute(
            select(func.count()).where(Lead.status == LeadStatus.won.value)
        )
        won_count = won_q.scalar() or 0

        if denom > 0:
            kpis["conversion_rate_pct"] = round((won_count / denom) * 100, 1)
        else:
            kpis["conversion_rate_pct"] = 0.0

        kpis["total_won"] = won_count
        kpis["conversion_denominator"] = denom

        # ── Satisfaction / NPS ────────────────────────────────────────────────

        nps_q = await db.execute(
            select(func.avg(Lead.satisfaction_score), func.count()).where(
                Lead.satisfaction_score.is_not(None)
            )
        )
        nps_row = nps_q.one()
        avg_sat = nps_row[0]
        kpis["avg_satisfaction"] = round(float(avg_sat), 2) if avg_sat is not None else None
        kpis["nps_count"] = nps_row[1] or 0

        # ── Funnel breakdown (all statuses, for completeness) ─────────────────

        funnel: dict[str, int] = {}
        for status in LeadStatus:
            if status == LeadStatus.anonymised:
                continue
            count_q = await db.execute(
                select(func.count()).where(Lead.status == status.value)
            )
            funnel[status.value] = count_q.scalar() or 0
        kpis["funnel"] = funnel

        return kpis
