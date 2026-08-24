"""
app/agents/client_health.py
────────────────────────────
ClientHealthAgent (P2)

Computes a composite health score (0–100) for one or all active clients.
Aggregates signals from:

  • Recency     — days since last conversation / contact
  • Payment     — overdue invoices, payment speed history
  • Delivery    — ratio of stalled vs. active portal projects
  • Satisfaction — NPS score if available

Risk thresholds:
  ≥ 70  →  healthy
  50–69 →  watch
  30–49 →  at-risk
  < 30  →  critical

Input:
  { "lead_id": "<uuid>" }        — single client health check
  {}  or  { "all": true }        — scan all lead.status = "client"

Output (AgentResult.data):
  {
    "clients": [
      {
        "lead_id": str,
        "name": str,
        "email": str,
        "health_score": int (0–100),
        "risk_level": "healthy"|"watch"|"at-risk"|"critical",
        "signals": {
          "recency_score": int,
          "payment_score": int,
          "delivery_score": int,
          "satisfaction_score": int,
          "days_since_contact": int | null,
          "overdue_invoices": int,
          "stalled_projects": int,
          "nps": float | null,
        },
        "recommended_action": str,
      },
      ...
    ],
    "generated_at": str,
    "total_clients": int,
    "at_risk_count": int,
  }
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent, PermissionLevel
from klara.rarv.conversation import Conversation
from klara.rarv.invoice import Invoice, InvoiceStatus
from klara.rarv.lead import Lead, LeadStatus
from klara.rarv.portal import Client, Project, ProjectStatus

logger = structlog.get_logger(__name__)

# ── Scoring weights (must sum to 100) ─────────────────────────────────────────
W_RECENCY      = 30
W_PAYMENT      = 35
W_DELIVERY     = 20
W_SATISFACTION = 15

# ── Thresholds ────────────────────────────────────────────────────────────────
RECENCY_HEALTHY_DAYS   = 14   # ≤14 days → full recency score
RECENCY_WARNING_DAYS   = 30   # ≤30 days → half score
RECENCY_CRITICAL_DAYS  = 60   # >60 days → zero

RISK_CRITICAL = 30
RISK_AT_RISK  = 50
RISK_WATCH    = 70


def _recency_score(days: int | None) -> int:
    """0–100 based on days since last contact."""
    if days is None:
        return 50  # unknown — neutral
    if days <= RECENCY_HEALTHY_DAYS:
        return 100
    if days <= RECENCY_WARNING_DAYS:
        return 70
    if days <= RECENCY_CRITICAL_DAYS:
        return 30
    return 0


def _payment_score(overdue_count: int, overdue_eur: float) -> int:
    """0–100. Overdue invoices drop the score hard."""
    if overdue_count == 0:
        return 100
    if overdue_count == 1 and overdue_eur < 500:
        return 60
    if overdue_count == 1:
        return 40
    if overdue_count == 2:
        return 20
    return 0


def _delivery_score(total: int, stalled: int) -> int:
    """0–100 based on project health."""
    if total == 0:
        return 80  # no projects — neutral-positive
    ratio = stalled / total
    if ratio == 0:
        return 100
    if ratio <= 0.25:
        return 70
    if ratio <= 0.5:
        return 40
    return 10


def _satisfaction_score(nps: float | None) -> int:
    """0–100 mapping NPS (0–10) to score."""
    if nps is None:
        return 60  # no survey — neutral-positive
    return int(min(100, max(0, nps * 10)))


def _risk_level(score: int) -> str:
    if score >= RISK_WATCH:
        return "healthy"
    if score >= RISK_AT_RISK:
        return "watch"
    if score >= RISK_CRITICAL:
        return "at-risk"
    return "critical"


def _recommended_action(risk: str, signals: dict) -> str:
    if risk == "healthy":
        return "No action needed. Continue regular check-ins."
    if risk == "watch":
        if signals["overdue_invoices"]:
            return "Send gentle payment reminder. Schedule a short check-in call."
        if signals["stalled_projects"]:
            return "Review project status with client. Clarify next milestone."
        return "Schedule a proactive check-in within the next two weeks."
    if risk == "at-risk":
        parts = []
        if signals["overdue_invoices"]:
            parts.append(f"escalate {signals['overdue_invoices']} overdue invoice(s)")
        if signals["days_since_contact"] and signals["days_since_contact"] > 30:
            parts.append("re-engage immediately — no contact in 30+ days")
        if signals["stalled_projects"]:
            parts.append("unblock stalled projects")
        return "Priority action: " + "; ".join(parts) if parts else "Book urgent client call."
    # critical
    return (
        "URGENT: Client relationship at high churn risk. "
        "Personal outreach from Anthony required within 48 h."
    )


class ClientHealthAgent(BaseAgent):
    name = "client_health"
    description = (
        "Computes a composite health score (0–100) for one or all active clients "
        "based on recency, payment behaviour, project delivery, and NPS.  "
        "Flags at-risk relationships with recommended actions.  P2."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        db   = context.db
        now  = datetime.now(timezone.utc)

        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )
        log.info("client_health.start", input=input_data)

        try:
            # ── Determine which leads to score ────────────────────────────────
            lead_id: str | None = input_data.get("lead_id")
            if lead_id:
                leads_r = await db.execute(
                    select(Lead).where(
                        Lead.id == lead_id,
                        Lead.status == LeadStatus.won.value,
                    )
                )
                leads = leads_r.scalars().all()
            else:
                leads_r = await db.execute(
                    select(Lead).where(Lead.status == LeadStatus.won.value)
                )
                leads = leads_r.scalars().all()

            if not leads:
                return AgentResult.ok({
                    "clients": [],
                    "generated_at": now.isoformat(),
                    "total_clients": 0,
                    "at_risk_count": 0,
                })

            results = []

            for lead in leads:
                # ── Recency: last conversation updated_at ─────────────────────
                conv_r = await db.execute(
                    select(Conversation.updated_at)
                    .where(Conversation.lead_id == lead.id)
                    .order_by(Conversation.updated_at.desc())
                    .limit(1)
                )
                last_conv = conv_r.scalar_one_or_none()
                days_since: int | None = None
                if last_conv:
                    # Ensure tz-aware comparison
                    lc_aware = last_conv.replace(tzinfo=timezone.utc) if last_conv.tzinfo is None else last_conv
                    days_since = max(0, (now - lc_aware).days)

                r_score = _recency_score(days_since)

                # ── Payment: overdue invoices linked to this lead ─────────────
                inv_r = await db.execute(
                    select(Invoice).where(
                        Invoice.lead_id == lead.id,
                        Invoice.status.in_([
                            InvoiceStatus.unpaid.value,
                            InvoiceStatus.reminded.value,
                        ]),
                    )
                )
                overdue_invs = inv_r.scalars().all()
                overdue_count = len(overdue_invs)
                overdue_eur = float(
                    sum(i.amount_eur for i in overdue_invs) or Decimal("0")
                )
                p_score = _payment_score(overdue_count, overdue_eur)

                # ── Delivery: portal projects via Client.email match ───────────
                # Portal client is matched by email (no FK back to Lead)
                portal_client_r = await db.execute(
                    select(Client).where(Client.email == lead.email).limit(1)
                )
                portal_client = portal_client_r.scalar_one_or_none()

                total_projects = 0
                stalled_projects = 0
                if portal_client:
                    proj_r = await db.execute(
                        select(Project).where(Project.client_id == portal_client.id)
                    )
                    projects = proj_r.scalars().all()
                    total_projects = len(projects)
                    stalled_statuses = {
                        ProjectStatus.waiting_on_client.value,
                        ProjectStatus.awaiting_approval.value,
                    }
                    stalled_projects = sum(
                        1 for p in projects if p.status in stalled_statuses
                    )

                d_score = _delivery_score(total_projects, stalled_projects)

                # ── Satisfaction (NPS) ────────────────────────────────────────
                nps = lead.satisfaction_score  # float | None
                s_score = _satisfaction_score(nps)

                # ── Composite health score ────────────────────────────────────
                health_score = int(
                    (r_score * W_RECENCY
                     + p_score * W_PAYMENT
                     + d_score * W_DELIVERY
                     + s_score * W_SATISFACTION)
                    / 100
                )
                risk = _risk_level(health_score)

                signals = {
                    "recency_score":      r_score,
                    "payment_score":      p_score,
                    "delivery_score":     d_score,
                    "satisfaction_score": s_score,
                    "days_since_contact": days_since,
                    "overdue_invoices":   overdue_count,
                    "overdue_eur":        overdue_eur,
                    "stalled_projects":   stalled_projects,
                    "total_projects":     total_projects,
                    "nps":                nps,
                }

                results.append({
                    "lead_id":             lead.id,
                    "name":                lead.name or "",
                    "email":               lead.email or "",
                    "health_score":        health_score,
                    "risk_level":          risk,
                    "signals":             signals,
                    "recommended_action":  _recommended_action(risk, signals),
                })

            # Sort: worst first
            results.sort(key=lambda x: x["health_score"])

            at_risk_count = sum(
                1 for r in results
                if r["risk_level"] in ("at-risk", "critical")
            )

            log.info(
                "client_health.done",
                total=len(results),
                at_risk=at_risk_count,
            )
            return AgentResult.ok({
                "clients":       results,
                "generated_at":  now.isoformat(),
                "total_clients": len(results),
                "at_risk_count": at_risk_count,
            })

        except Exception as exc:
            log.error("client_health.error", error=str(exc), exc_info=True)
            return AgentResult.fail(error=str(exc))
