"""
app/agents/revenue_analytics.py
────────────────────────────────
RevenueAnalyticsAgent (P1)

Read-only agent that aggregates financial KPIs from the database and returns
a structured analytics snapshot.  Designed to be called by:

  • DailyReportAgent   — embeds KPIs in the morning summary
  • Admin dashboard    — on-demand refresh via /api/v1/admin/revenue-analytics
  • LokiOrchestratorAgent — when a revenue query arrives in chat

No side-effects, no approvals required.  P1 = auto-approve.

Output shape (AgentResult.data):
  {
    "generated_at": "<ISO-8601>",
    "period_days": 30,
    "pipeline": {
      "total_leads": int,
      "qualified_leads": int,
      "proposals_sent": int,
      "clients": int,
      "conversion_rate_pct": float,
      "avg_lead_score": float | None,
    },
    "invoices": {
      "sent_total_eur": float,
      "paid_total_eur": float,
      "outstanding_eur": float,
      "overdue_count": int,
      "overdue_total_eur": float,
    },
    "generated_invoices": {
      "draft_count": int,
      "sent_count": int,
      "paid_count": int,
      "sent_total_eur": float,
      "paid_total_eur": float,
    },
    "satisfaction": {
      "avg_nps": float | None,
      "responses": int,
    },
  }
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog
from sqlalchemy import func, select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent, PermissionLevel
from klara.rarv.generated_invoice import GeneratedInvoice, GeneratedInvoiceStatus
from klara.rarv.invoice import Invoice, InvoiceStatus
from klara.rarv.lead import Lead, LeadStatus
from klara.rarv.proposal import Proposal, ProposalStatus

logger = structlog.get_logger(__name__)


class RevenueAnalyticsAgent(BaseAgent):
    name = "revenue_analytics"
    description = (
        "Aggregates financial KPIs from the database: pipeline conversion, "
        "invoice totals, outstanding payments, and client satisfaction.  "
        "Read-only, P1."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        db = context.db
        period_days: int = int(input_data.get("period_days", 30))
        since = datetime.now(timezone.utc) - timedelta(days=period_days)

        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
            period_days=period_days,
        )
        log.info("revenue_analytics.start")

        try:
            # ── Pipeline metrics ──────────────────────────────────────────────
            total_leads_r = await db.execute(select(func.count()).select_from(Lead))
            total_leads: int = total_leads_r.scalar_one()

            qualified_r = await db.execute(
                select(func.count()).select_from(Lead).where(
                    Lead.status.in_([
                        LeadStatus.qualified.value,
                        LeadStatus.discovery_done.value,
                        LeadStatus.proposal_sent.value,
                        LeadStatus.won.value,
                    ])
                )
            )
            qualified_leads: int = qualified_r.scalar_one()

            proposals_sent_r = await db.execute(
                select(func.count()).select_from(Proposal).where(
                    Proposal.status.in_([
                        ProposalStatus.emailed.value,
                        ProposalStatus.sent_to_client.value,
                        ProposalStatus.accepted.value,
                    ])
                )
            )
            proposals_sent: int = proposals_sent_r.scalar_one()

            clients_r = await db.execute(
                select(func.count()).select_from(Lead).where(
                    Lead.status == LeadStatus.won.value
                )
            )
            clients: int = clients_r.scalar_one()

            conversion_rate = (
                round(clients / total_leads * 100, 1) if total_leads else 0.0
            )

            avg_score_r = await db.execute(
                select(func.avg(Lead.score)).where(Lead.score.isnot(None))
            )
            avg_score_raw = avg_score_r.scalar_one()
            avg_lead_score = (
                round(float(avg_score_raw), 1) if avg_score_raw is not None else None
            )

            # ── External invoices (tracked via InvoiceReminderAgent) ──────────
            sent_total_r = await db.execute(
                select(func.sum(Invoice.amount_eur)).where(
                    Invoice.status.in_([
                        InvoiceStatus.sent.value,
                        InvoiceStatus.unpaid.value,
                        InvoiceStatus.reminded.value,
                    ])
                )
            )
            sent_total = float(sent_total_r.scalar_one() or Decimal("0"))

            paid_total_r = await db.execute(
                select(func.sum(Invoice.amount_eur)).where(
                    Invoice.status == InvoiceStatus.paid.value
                )
            )
            paid_total = float(paid_total_r.scalar_one() or Decimal("0"))

            # "Overdue" = past due (unpaid + reminded)
            overdue_r = await db.execute(
                select(
                    func.count(),
                    func.sum(Invoice.amount_eur),
                ).where(
                    Invoice.status.in_([
                        InvoiceStatus.unpaid.value,
                        InvoiceStatus.reminded.value,
                    ])
                )
            )
            overdue_count, overdue_sum = overdue_r.one()
            overdue_total = float(overdue_sum or Decimal("0"))

            outstanding_eur = sent_total

            # ── Generated invoices (PDF system) ──────────────────────────────
            gi_stats: dict[str, int | float] = {}
            for status in (
                GeneratedInvoiceStatus.draft,
                GeneratedInvoiceStatus.sent,
                GeneratedInvoiceStatus.paid,
            ):
                cnt_r = await db.execute(
                    select(func.count()).select_from(GeneratedInvoice).where(
                        GeneratedInvoice.status == status.value
                    )
                )
                gi_stats[f"{status.value}_count"] = cnt_r.scalar_one()

            gi_sent_eur_r = await db.execute(
                select(func.sum(GeneratedInvoice.amount_gross)).where(
                    GeneratedInvoice.status == GeneratedInvoiceStatus.sent.value
                )
            )
            gi_paid_eur_r = await db.execute(
                select(func.sum(GeneratedInvoice.amount_gross)).where(
                    GeneratedInvoice.status == GeneratedInvoiceStatus.paid.value
                )
            )
            gi_sent_eur = float(gi_sent_eur_r.scalar_one() or Decimal("0"))
            gi_paid_eur = float(gi_paid_eur_r.scalar_one() or Decimal("0"))

            # ── Satisfaction (NPS scores on Lead.satisfaction_score) ──────────
            nps_r = await db.execute(
                select(
                    func.avg(Lead.satisfaction_score),
                    func.count(Lead.satisfaction_score),
                ).where(Lead.satisfaction_score.isnot(None))
            )
            avg_nps_raw, nps_responses = nps_r.one()
            avg_nps = (
                round(float(avg_nps_raw), 1) if avg_nps_raw is not None else None
            )

            analytics = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "period_days": period_days,
                "pipeline": {
                    "total_leads": total_leads,
                    "qualified_leads": qualified_leads,
                    "proposals_sent": proposals_sent,
                    "clients": clients,
                    "conversion_rate_pct": conversion_rate,
                    "avg_lead_score": avg_lead_score,
                },
                "invoices": {
                    "sent_total_eur": sent_total,
                    "paid_total_eur": paid_total,
                    "outstanding_eur": outstanding_eur,
                    "overdue_count": int(overdue_count),
                    "overdue_total_eur": overdue_total,
                },
                "generated_invoices": {
                    "draft_count": gi_stats.get("draft_count", 0),
                    "sent_count": gi_stats.get("sent_count", 0),
                    "paid_count": gi_stats.get("paid_count", 0),
                    "sent_total_eur": gi_sent_eur,
                    "paid_total_eur": gi_paid_eur,
                },
                "satisfaction": {
                    "avg_nps": avg_nps,
                    "responses": int(nps_responses),
                },
            }

            log.info(
                "revenue_analytics.done",
                total_leads=total_leads,
                clients=clients,
                conversion_pct=conversion_rate,
                overdue_count=int(overdue_count),
            )
            return AgentResult.ok(analytics)

        except Exception as exc:
            log.error("revenue_analytics.error", error=str(exc), exc_info=True)
            return AgentResult.fail(error=str(exc))
