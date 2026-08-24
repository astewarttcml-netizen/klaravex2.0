"""
app/agents/weekly_report.py
────────────────────────────
WeeklyReportAgent — generates a structured weekly business summary covering
new leads, pipeline movement, revenue collected, proposals sent, outstanding
invoices, and top actions for the week.

Permission level: P1 (read-only DB queries; email delivery is best-effort and
logged but does not gate success of the report itself).

Input keys (all optional):
  override_recipient — str: send the report email to this address instead of
                        settings.approval_notify_email

Output keys:
  report_markdown  — full Markdown report string
  emailed          — bool: True if the report was successfully emailed
  week_start       — ISO datetime string for the start of the reporting window
  week_end         — ISO datetime string for the end of the reporting window
  stats            — dict of raw numbers used to build the report
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
from klara.rarv.proposal import Proposal, ProposalStatus
from klara.rarv.runtime.email_sender import send_transactional_email

logger = structlog.get_logger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")

# Pipeline statuses that represent active (in-flight) opportunities
_PIPELINE_STATUSES = {
    LeadStatus.qualified.value,
    LeadStatus.discovery_done.value,
    LeadStatus.proposal_sent.value,
}

# Statuses that represent leads that progressed beyond "new"
# (used to compute conversion rate denominator in weekly context)
_PROGRESSED_STATUSES = {
    LeadStatus.qualified.value,
    LeadStatus.discovery_done.value,
    LeadStatus.proposal_sent.value,
    LeadStatus.won.value,
    LeadStatus.lost.value,
}


class WeeklyReportAgent(BaseAgent):
    """
    Generates a weekly business summary for Klaravex.

    The report window is last Monday 00:00 Europe/Berlin → this Monday 00:00
    Europe/Berlin (i.e. the fully completed calendar week).  The report covers:

      - New leads received during the week
      - Leads that progressed into the pipeline (updated into qualified /
        discovery_done / proposal_sent / won this week)
      - Deals won this week
      - Proposals sent to client this week
      - Revenue collected this week (paid invoices, using updated_at as proxy)
      - Outstanding invoices (unpaid + reminded, all-time)
      - Active pipeline snapshot (count of leads in qualified/discovery/proposal)

    If settings.approval_notify_email is set, the report is emailed as HTML.
    The optional input key ``override_recipient`` directs the email elsewhere.
    """

    name = "weekly_report"
    description = (
        "Generates a weekly business summary covering new leads, pipeline "
        "movement, revenue collected, and top actions for the week."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )
        db = context.db
        settings = context.settings

        # ── Compute week window ───────────────────────────────────────────────
        now_berlin = datetime.now(BERLIN)
        # ISO weekday: Monday = 1 … Sunday = 7
        days_since_monday = now_berlin.isoweekday() - 1
        this_monday = now_berlin.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=days_since_monday)
        last_monday = this_monday - timedelta(weeks=1)

        week_start_utc = last_monday.astimezone(timezone.utc)
        week_end_utc = this_monday.astimezone(timezone.utc)

        log.info(
            "weekly_report.generating",
            week_start=week_start_utc.isoformat(),
            week_end=week_end_utc.isoformat(),
        )

        try:
            stats = await self._gather_stats(db, week_start_utc, week_end_utc)
        except Exception as exc:
            log.error("weekly_report.stats_error", error=str(exc), exc_info=True)
            return AgentResult.fail(error=f"Stats gathering failed: {exc}")

        report_md = self._format_report(last_monday, this_monday, stats)

        # ── Email delivery ────────────────────────────────────────────────────
        recipient = (
            input_data.get("override_recipient")
            or getattr(settings, "approval_notify_email", None)
        )
        emailed = False
        if recipient:
            week_label = last_monday.strftime("%-d. %B") + " – " + (
                this_monday - timedelta(days=1)
            ).strftime("%-d. %B %Y")
            subject = f"Klaravex Weekly Report — {week_label}"
            html_body = _markdown_to_html(report_md)
            emailed = await send_transactional_email(
                settings,
                to_email=recipient,
                to_name="Klaravex",
                subject=subject,
                body_html=html_body,
                body_text=report_md,
            )
            log.info("weekly_report.emailed", recipient=recipient, success=emailed)
        else:
            log.info("weekly_report.no_recipient", reason="approval_notify_email not set")

        return AgentResult.ok(
            output={
                "report_markdown": report_md,
                "emailed": emailed,
                "week_start": week_start_utc.isoformat(),
                "week_end": week_end_utc.isoformat(),
                "stats": stats,
            }
        )

    # ── Stats gathering ───────────────────────────────────────────────────────

    async def _gather_stats(
        self,
        db,
        week_start: datetime,
        week_end: datetime,
    ) -> dict:
        stats: dict = {}

        # New leads this week
        new_leads_q = await db.execute(
            select(Lead).where(
                Lead.created_at >= week_start,
                Lead.created_at < week_end,
            )
        )
        new_leads = new_leads_q.scalars().all()
        stats["new_leads"] = len(new_leads)

        # Leads that moved into a progressed status this week (updated_at proxy)
        progressed_q = await db.execute(
            select(Lead).where(
                Lead.updated_at >= week_start,
                Lead.updated_at < week_end,
                Lead.status.in_(list(_PROGRESSED_STATUSES)),
            )
        )
        progressed = progressed_q.scalars().all()
        stats["leads_progressed"] = len(progressed)

        # Deals won this week
        won_q = await db.execute(
            select(Lead).where(
                Lead.updated_at >= week_start,
                Lead.updated_at < week_end,
                Lead.status == LeadStatus.won.value,
            )
        )
        won_leads = won_q.scalars().all()
        stats["deals_won"] = len(won_leads)
        stats["deals_won_names"] = [
            (l.company or l.name or "Unknown") for l in won_leads
        ]

        # Proposals sent to client this week (Proposal.emailed_at in range)
        proposals_sent_q = await db.execute(
            select(Proposal).where(
                Proposal.status == ProposalStatus.sent_to_client.value,
                Proposal.emailed_at >= week_start,
                Proposal.emailed_at < week_end,
            )
        )
        proposals_sent = proposals_sent_q.scalars().all()
        stats["proposals_sent"] = len(proposals_sent)

        # Revenue collected this week (paid invoices, updated_at as payment proxy)
        paid_invoices_q = await db.execute(
            select(Invoice).where(
                Invoice.status == InvoiceStatus.paid.value,
                Invoice.updated_at >= week_start,
                Invoice.updated_at < week_end,
            )
        )
        paid_invoices = paid_invoices_q.scalars().all()
        stats["revenue_collected_eur"] = float(
            sum(inv.amount_eur for inv in paid_invoices) or Decimal("0.00")
        )
        stats["revenue_invoice_count"] = len(paid_invoices)

        # Outstanding invoices (unpaid + reminded, all-time)
        outstanding_q = await db.execute(
            select(Invoice).where(
                Invoice.status.in_([
                    InvoiceStatus.unpaid.value,
                    InvoiceStatus.reminded.value,
                ])
            )
        )
        outstanding = outstanding_q.scalars().all()
        stats["outstanding_count"] = len(outstanding)
        stats["outstanding_eur"] = float(
            sum(inv.amount_eur for inv in outstanding) or Decimal("0.00")
        )

        # Active pipeline snapshot
        pipeline_q = await db.execute(
            select(Lead).where(Lead.status.in_(list(_PIPELINE_STATUSES)))
        )
        pipeline = pipeline_q.scalars().all()
        stats["pipeline_count"] = len(pipeline)
        stats["pipeline_by_status"] = {
            LeadStatus.qualified.value: sum(
                1 for l in pipeline if l.status == LeadStatus.qualified.value
            ),
            LeadStatus.discovery_done.value: sum(
                1 for l in pipeline if l.status == LeadStatus.discovery_done.value
            ),
            LeadStatus.proposal_sent.value: sum(
                1 for l in pipeline if l.status == LeadStatus.proposal_sent.value
            ),
        }

        # All-time totals for context
        total_won_q = await db.execute(
            select(func.count()).where(Lead.status == LeadStatus.won.value)
        )
        stats["total_won_all_time"] = total_won_q.scalar() or 0

        total_revenue_q = await db.execute(
            select(func.sum(Invoice.amount_eur)).where(
                Invoice.status == InvoiceStatus.paid.value
            )
        )
        stats["total_revenue_all_time_eur"] = float(
            total_revenue_q.scalar() or Decimal("0.00")
        )

        return stats

    # ── Report formatting ─────────────────────────────────────────────────────

    def _format_report(
        self,
        week_start: datetime,
        week_end: datetime,
        stats: dict,
    ) -> str:
        week_label = week_start.strftime("%-d. %B") + " – " + (
            week_end - timedelta(days=1)
        ).strftime("%-d. %B %Y")

        generated_at = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

        # Pipeline breakdown table
        pipeline_rows = "\n".join([
            f"| Qualified          | {stats['pipeline_by_status'].get('qualified', 0):>5} |",
            f"| Discovery Done     | {stats['pipeline_by_status'].get('discovery_done', 0):>5} |",
            f"| Proposal Sent      | {stats['pipeline_by_status'].get('proposal_sent', 0):>5} |",
            f"| **Total Active**   | **{stats['pipeline_count']:>3}** |",
        ])

        # Deals won list
        if stats["deals_won_names"]:
            won_list = "\n".join(f"  - {name}" for name in stats["deals_won_names"])
        else:
            won_list = "  _No deals won this week_"

        # Outstanding alert block
        if stats["outstanding_count"] > 0:
            outstanding_block = (
                f"\n> **ACTION REQUIRED:** {stats['outstanding_count']} outstanding "
                f"invoice{'s' if stats['outstanding_count'] != 1 else ''} totalling "
                f"**€{stats['outstanding_eur']:,.2f}** — review in Klaravex admin.\n"
            )
        else:
            outstanding_block = "\n> All invoices current — no outstanding amounts.\n"

        return f"""# Klaravex Weekly Report — {week_label}

_Generated automatically by Klaravex_
_Report window: {week_start.strftime('%d.%m.%Y %H:%M')} → {(week_end - timedelta(days=1)).strftime('%d.%m.%Y')} (Europe/Berlin)_

---

## Pipeline Summary

| Stage              | Count |
|--------------------|------:|
{pipeline_rows}

**New leads this week:** {stats['new_leads']}
**Leads that progressed this week:** {stats['leads_progressed']}

---

## Revenue

| Metric                        | Value |
|-------------------------------|------:|
| Collected this week           | **€{stats['revenue_collected_eur']:,.2f}** ({stats['revenue_invoice_count']} invoice{'s' if stats['revenue_invoice_count'] != 1 else ''}) |
| Total revenue (all time)      | €{stats['total_revenue_all_time_eur']:,.2f} |
| Outstanding (unpaid/reminded) | €{stats['outstanding_eur']:,.2f} ({stats['outstanding_count']} invoice{'s' if stats['outstanding_count'] != 1 else ''}) |

{outstanding_block}
---

## Wins

**Deals closed this week:** {stats['deals_won']}

{won_list}

**Cumulative wins (all time):** {stats['total_won_all_time']}

---

## Proposals

**Proposals sent to client this week:** {stats['proposals_sent']}

---

## Outstanding Actions

- Review {stats['outstanding_count']} outstanding invoice{'s' if stats['outstanding_count'] != 1 else ''} (€{stats['outstanding_eur']:,.2f})
- Pipeline has {stats['pipeline_count']} active opportunit{'ies' if stats['pipeline_count'] != 1 else 'y'} — ensure follow-up cadence is current
- Check Klaravex admin for any pending approvals

---

_Report generated at {generated_at}_
_Klaravex · api.klaravex.de_
"""


# ── Utility: minimal Markdown → HTML converter ───────────────────────────────

def _markdown_to_html(md: str) -> str:
    """
    Convert a Markdown string to a clean HTML email body.

    Only handles the subset used by this report: headings, bold, italic,
    blockquotes, horizontal rules, tables, and line breaks.  A full Markdown
    parser is intentionally avoided to keep the dependency footprint minimal.
    """
    import re

    lines = md.split("\n")
    html_lines: list[str] = []
    in_table = False
    in_blockquote = False

    def inline(text: str) -> str:
        # Bold
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        # Italic
        text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)
        return text

    for line in lines:
        # Heading 1
        if line.startswith("# "):
            html_lines.append(
                f'<h1 style="color:#1a1a2e;border-bottom:2px solid #e0e0e0;'
                f'padding-bottom:8px">{inline(line[2:])}</h1>'
            )
        # Heading 2
        elif line.startswith("## "):
            html_lines.append(
                f'<h2 style="color:#16213e;margin-top:24px">{inline(line[3:])}</h2>'
            )
        # Heading 3
        elif line.startswith("### "):
            html_lines.append(
                f'<h3 style="color:#0f3460">{inline(line[4:])}</h3>'
            )
        # Horizontal rule
        elif line.strip() == "---":
            html_lines.append('<hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0">')
        # Blockquote
        elif line.startswith("> "):
            html_lines.append(
                f'<blockquote style="border-left:4px solid #e74c3c;margin:12px 0;'
                f'padding:8px 16px;background:#fff5f5;color:#333">'
                f'{inline(line[2:])}</blockquote>'
            )
        # Table separator row — skip
        elif re.match(r"^\|[-| :]+\|$", line.strip()):
            if not in_table:
                html_lines.append(
                    '<table style="border-collapse:collapse;width:100%;'
                    'margin:12px 0;font-size:14px">'
                )
                in_table = True
            continue
        # Table row
        elif line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line[1:-1].split("|")]
            if not in_table:
                html_lines.append(
                    '<table style="border-collapse:collapse;width:100%;'
                    'margin:12px 0;font-size:14px">'
                )
                in_table = True
                tag = "th"
                style = 'style="background:#f5f5f5;font-weight:bold;padding:8px;border:1px solid #ddd;text-align:left"'
            else:
                tag = "td"
                style = 'style="padding:8px;border:1px solid #ddd"'
            row_html = "".join(f"<{tag} {style}>{inline(c)}</{tag}>" for c in cells)
            html_lines.append(f"<tr>{row_html}</tr>")
        # Close table on non-table line
        else:
            if in_table:
                html_lines.append("</table>")
                in_table = False
            # List item
            if line.startswith("  - ") or line.startswith("- "):
                content = line.lstrip(" ").lstrip("- ")
                html_lines.append(f'<li style="margin:4px 0">{inline(content)}</li>')
            # Empty line
            elif line.strip() == "":
                html_lines.append("<br>")
            # Italic / plain paragraph
            else:
                html_lines.append(f'<p style="margin:6px 0">{inline(line)}</p>')

    if in_table:
        html_lines.append("</table>")

    body = "\n".join(html_lines)
    return (
        f'<html><body style="font-family:Arial,Helvetica,sans-serif;'
        f'max-width:700px;margin:auto;color:#333;padding:24px">'
        f"{body}"
        f"</body></html>"
    )
