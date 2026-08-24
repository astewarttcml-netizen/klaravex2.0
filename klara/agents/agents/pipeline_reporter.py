"""
app/agents/pipeline_reporter.py
─────────────────────────────────
P1 agent — weekly Monday pipeline summary email to Anthony.

Different from daily_report (ops metrics) — pipeline_reporter is a sales
pipeline digest: lead counts by stage, open proposals, won this week,
conversion rate, pipeline value estimate.

Triggered by: Celery beat task every Monday 08:30 Europe/Berlin.
Also callable directly via POST /api/v1/agents/run with agent="pipeline_reporter".

Email includes:
  - Stage breakdown (new, qualified, proposal_sent, discovery_done, won, lost)
  - Proposals open > 7 days without response
  - Deals won/lost this week
  - Cold leads eligible for nurture
  - Pipeline value estimate (based on budget_range midpoints)

Permission: P1 — read-only analytics, internal email to Anthony only.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select

from app.agents.base import BaseAgent, AgentContext, AgentResult, PermissionLevel
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

# Rough midpoints for pipeline value estimation
_BUDGET_MIDPOINTS: dict[str, float] = {
    "< €1,000": 750,
    "€1,000–€3,000": 2000,
    "€3,000–€5,000": 4000,
    "€5,000–€10,000": 7500,
    "€10,000–€25,000": 17500,
    "> €25,000": 30000,
}


class PipelineReporterAgent(BaseAgent):
    name = "pipeline_reporter"
    permission_level = PermissionLevel.P1
    description = (
        "Weekly Monday 08:30 CET pipeline digest email to Anthony. "
        "Shows lead stage breakdown, open proposals, won/lost this week, "
        "cold lead pool size, and estimated pipeline value. "
        "P1 — read-only, internal only."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        # Stage counts
        stage_rows = (await context.db.execute(
            select(Lead.status, func.count(Lead.id))
            .where(Lead.status != LeadStatus.anonymised)
            .group_by(Lead.status)
        )).fetchall()
        stage_counts = {row[0]: row[1] for row in stage_rows}

        # Won this week
        won_week = (await context.db.execute(
            select(func.count(Lead.id))
            .where(Lead.status == LeadStatus.won)
            .where(Lead.updated_at >= week_ago)
        )).scalar() or 0

        # Lost this week
        lost_week = (await context.db.execute(
            select(func.count(Lead.id))
            .where(Lead.status == LeadStatus.lost)
            .where(Lead.updated_at >= week_ago)
        )).scalar() or 0

        # Open proposals > 7 days
        from app.models.proposal import Proposal
        try:
            stale_proposals = (await context.db.execute(
                select(func.count(Proposal.id))
                .where(Proposal.status == "sent")
                .where(Proposal.created_at <= week_ago)
            )).scalar() or 0
        except Exception:
            stale_proposals = 0

        # Fetch qualified + proposal_sent leads for pipeline value estimate
        active_leads = (await context.db.execute(
            select(Lead.budget_range, Lead.status)
            .where(Lead.status.in_([
                LeadStatus.qualified,
                LeadStatus.proposal_sent,
                LeadStatus.discovery_done,
            ]))
        )).fetchall()

        # Estimate pipeline value
        pipeline_value = 0.0
        for row in active_leads:
            budget_str = row[0] or ""
            for key, midpoint in _BUDGET_MIDPOINTS.items():
                if key.lower() in budget_str.lower():
                    pipeline_value += midpoint
                    break

        # Cold leads eligible for nurture (COLD/lost/disqualified with no cold_nurture activity)
        cold_count = (
            stage_counts.get(LeadStatus.disqualified, 0)
            + stage_counts.get(LeadStatus.lost, 0)
        )

        total_active = sum(
            stage_counts.get(s, 0)
            for s in [LeadStatus.new, LeadStatus.qualified,
                      LeadStatus.proposal_sent, LeadStatus.discovery_done]
        )

        report = {
            "week_ending": now.strftime("%Y-%m-%d"),
            "stage_counts": stage_counts,
            "total_active": total_active,
            "won_this_week": won_week,
            "lost_this_week": lost_week,
            "stale_proposals_7d": stale_proposals,
            "estimated_pipeline_eur": round(pipeline_value, 0),
            "cold_nurture_pool": cold_count,
        }

        html = _render_pipeline_email(report, now)

        # Send directly — P1, no approval needed
        try:
            from app.services.email_sender import send_transactional_email
            await send_transactional_email(
                context.settings,
                to_email=context.settings.approval_notify_email,
                to_name="Anthony Stewart",
                subject=f"Weekly Pipeline — {now.strftime('%d %b %Y')}",
                body_html=html,
                body_text=json.dumps(report, indent=2, default=str),
            )
        except Exception as exc:
            log.warning("pipeline_reporter.email_failed", error=str(exc))
            # Don't fail the agent — report data is still returned

        log.info("pipeline_reporter.sent",
                 total_active=total_active,
                 pipeline_value=pipeline_value,
                 won_week=won_week)

        return AgentResult.ok(report)


def _render_pipeline_email(report: dict, now: datetime) -> str:
    stages = report["stage_counts"]
    rows_html = ""
    stage_order = [
        LeadStatus.new, LeadStatus.qualified, LeadStatus.proposal_sent,
        LeadStatus.discovery_done, LeadStatus.won, LeadStatus.lost,
        LeadStatus.disqualified,
    ]
    for s in stage_order:
        count = stages.get(s, 0)
        if count > 0:
            rows_html += (
                f"<tr><td style='padding:4px 8px;'>{s}</td>"
                f"<td style='padding:4px 8px;text-align:right;font-weight:bold;'>{count}</td></tr>"
            )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:20px;color:#222;">
<h2 style="color:#1565c0;border-bottom:2px solid #1565c0;padding-bottom:8px;">
  📊 Weekly Pipeline Report — {now.strftime('%d %b %Y')}
</h2>

<h3 style="color:#333;">Pipeline Stages</h3>
<table style="border-collapse:collapse;width:100%;margin-bottom:20px;">
  <tr style="background:#e3f2fd;">
    <th style="padding:6px 8px;text-align:left;">Stage</th>
    <th style="padding:6px 8px;text-align:right;">Count</th>
  </tr>
  {rows_html}
  <tr style="background:#f5f5f5;font-weight:bold;">
    <td style="padding:6px 8px;">TOTAL ACTIVE</td>
    <td style="padding:6px 8px;text-align:right;">{report['total_active']}</td>
  </tr>
</table>

<table style="border-collapse:collapse;width:100%;margin-bottom:20px;">
  <tr><td style="padding:4px 0;"><strong>Won this week:</strong></td>
      <td style="color:#2e7d32;font-weight:bold;">{report['won_this_week']}</td></tr>
  <tr><td style="padding:4px 0;"><strong>Lost this week:</strong></td>
      <td style="color:#c62828;">{report['lost_this_week']}</td></tr>
  <tr><td style="padding:4px 0;"><strong>Proposals stale &gt;7 days:</strong></td>
      <td style="color:#e65100;">{report['stale_proposals_7d']}</td></tr>
  <tr><td style="padding:4px 0;"><strong>Est. pipeline value:</strong></td>
      <td style="font-weight:bold;">€{report['estimated_pipeline_eur']:,.0f}</td></tr>
  <tr><td style="padding:4px 0;"><strong>Cold nurture pool:</strong></td>
      <td>{report['cold_nurture_pool']}</td></tr>
</table>

<hr style="border:none;border-top:1px solid #eee;">
<p style="font-size:12px;color:#999;">Klaravex · klaravex.de</p>
</body>
</html>"""
