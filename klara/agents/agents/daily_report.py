"""
app/agents/daily_report.py
───────────────────────────
DailyReportAgent — generates the daily operations summary for Klaravex.

Permission level: P2 (read-only DB queries, internal write to reports table).

Input keys (all optional):
  report_date  — ISO date string "YYYY-MM-DD" to report on (default: yesterday)
  triggered_by — who triggered this (default: "celery_beat")

Output keys:
  report_markdown  — full Markdown report string
  stats_json       — dict of raw numbers used to build the report
  report_date      — ISO date string of the period covered
"""
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog

BERLIN = ZoneInfo("Europe/Berlin")
from sqlalchemy import func, select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent, PermissionLevel
from klara.rarv.approval import ApprovalRequest, ApprovalStatus
from klara.rarv.lead import Lead, LeadStatus, LeadSource
from klara.rarv.proposal import Proposal

logger = structlog.get_logger(__name__)

# Score thresholds (must stay in sync with lead_scoring.py)
_HOT_THRESHOLD = 70.0
_WARM_THRESHOLD = 40.0


class DailyReportAgent(BaseAgent):
    name = "daily_report"
    description = (
        "Generates the daily operations report: lead funnel, approvals, "
        "proposals, and outreach summary for Klaravex."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        db = context.db

        # ── Determine report period ───────────────────────────────────────────
        triggered_by = input_data.get("triggered_by", "celery_beat")

        if "report_date" in input_data and input_data["report_date"]:
            try:
                report_date = date.fromisoformat(input_data["report_date"])
            except ValueError:
                return AgentResult(success=False, error=f"Invalid report_date: {input_data['report_date']}")
        else:
            # Default: yesterday in Europe/Berlin (DST-aware via ZoneInfo)
            berlin_now = datetime.now(BERLIN)
            report_date = (berlin_now - timedelta(days=1)).date()

        # Window: [day_start, day_end) — anchored to Berlin midnight, stored as UTC
        day_start = datetime(report_date.year, report_date.month, report_date.day,
                             0, 0, 0, tzinfo=BERLIN).astimezone(timezone.utc)
        day_end = day_start + timedelta(days=1)

        # 7-day window for rolling summary
        week_start = day_start - timedelta(days=6)  # 7 days ending at day_end

        logger.info(
            "daily_report.generating",
            report_date=report_date.isoformat(),
            triggered_by=triggered_by,
        )

        try:
            stats = await self._gather_stats(db, day_start, day_end, week_start)
        except Exception as exc:
            logger.error("daily_report.stats_error", error=str(exc), exc_info=True)
            return AgentResult(success=False, error=f"Stats gathering failed: {exc}")

        markdown = self._format_report(report_date, stats)

        return AgentResult(
            success=True,
            output={
                "report_markdown": markdown,
                "stats_json": stats,
                "report_date": report_date.isoformat(),
            },
        )

    # ── Stats gathering ───────────────────────────────────────────────────────

    async def _gather_stats(self, db, day_start, day_end, week_start) -> dict:
        stats = {}

        # ── Leads: today ──────────────────────────────────────────────────────
        leads_today = await db.execute(
            select(Lead).where(Lead.created_at >= day_start, Lead.created_at < day_end)
        )
        today_leads = leads_today.scalars().all()

        stats["leads_today"] = len(today_leads)
        stats["leads_today_hot"] = sum(
            1 for l in today_leads
            if l.score is not None and l.score >= _HOT_THRESHOLD
        )
        stats["leads_today_warm"] = sum(
            1 for l in today_leads
            if l.score is not None and _WARM_THRESHOLD <= l.score < _HOT_THRESHOLD
        )
        stats["leads_today_cold"] = sum(
            1 for l in today_leads
            if l.score is not None and l.score < _WARM_THRESHOLD
        )
        stats["leads_today_unscored"] = sum(1 for l in today_leads if l.score is None)

        # Source breakdown today
        stats["leads_today_by_source"] = {}
        for src in LeadSource:
            stats["leads_today_by_source"][src.value] = sum(
                1 for l in today_leads if l.source == src.value
            )

        # ── Leads: rolling 7 days ─────────────────────────────────────────────
        leads_week_q = await db.execute(
            select(Lead).where(Lead.created_at >= week_start, Lead.created_at < day_end)
        )
        week_leads = leads_week_q.scalars().all()
        stats["leads_7d"] = len(week_leads)
        stats["leads_7d_hot"] = sum(
            1 for l in week_leads
            if l.score is not None and l.score >= _HOT_THRESHOLD
        )

        # ── Lead funnel: all-time totals ──────────────────────────────────────
        for status in LeadStatus:
            if status == LeadStatus.anonymised:
                continue
            result = await db.execute(
                select(func.count()).where(Lead.status == status.value)
            )
            stats[f"funnel_{status.value}"] = result.scalar() or 0

        # ── Approvals: today ──────────────────────────────────────────────────
        approvals_today_q = await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.created_at >= day_start,
                ApprovalRequest.created_at < day_end,
            )
        )
        approvals_today = approvals_today_q.scalars().all()
        stats["approvals_created_today"] = len(approvals_today)

        # Pending approvals (all-time, not just today)
        pending_q = await db.execute(
            select(func.count()).where(ApprovalRequest.status == ApprovalStatus.pending)
        )
        stats["approvals_pending_total"] = pending_q.scalar() or 0

        # Approved / rejected today
        stats["approvals_approved_today"] = sum(
            1 for a in approvals_today if a.status == ApprovalStatus.approved
        )
        stats["approvals_rejected_today"] = sum(
            1 for a in approvals_today if a.status == ApprovalStatus.rejected
        )

        # Outreach emails approved today
        stats["outreach_approved_today"] = sum(
            1 for a in approvals_today
            if a.action_name == "outreach_email.send"
            and a.status == ApprovalStatus.approved
        )

        # ── Proposals: today ──────────────────────────────────────────────────
        proposals_today_q = await db.execute(
            select(Proposal).where(
                Proposal.created_at >= day_start,
                Proposal.created_at < day_end,
            )
        )
        proposals_today = proposals_today_q.scalars().all()
        stats["proposals_drafted_today"] = len(proposals_today)
        stats["proposals_emailed_today"] = sum(
            1 for p in proposals_today if p.emailed_at is not None
        )

        # Total proposals all-time
        total_proposals_q = await db.execute(select(func.count(Proposal.id)))
        stats["proposals_total"] = total_proposals_q.scalar() or 0

        # ── Tokens used today (proposals) ─────────────────────────────────────
        stats["tokens_used_today"] = sum(
            (p.tokens_used or 0) for p in proposals_today
        )

        # ── phase21-005: autonomy promotions + outreach analytics ─────────────
        # Count of P4 autonomy.promote requests created today (from
        # phase19-010's nightly sweep). These show up to Anthony in the
        # daily report so he reviews them within ~24h.
        stats["autonomy_promotions_today"] = sum(
            1 for a in approvals_today
            if a.action_name == "autonomy.promote"
        )
        # List of agent names for the report body (max 5 to keep report compact).
        promo_agents = []
        for a in approvals_today:
            if a.action_name != "autonomy.promote":
                continue
            try:
                pl = json.loads(a.payload or "{}")
                name = pl.get("agent_name")
                if name and name not in promo_agents:
                    promo_agents.append(name)
            except (json.JSONDecodeError, TypeError):
                pass
        stats["autonomy_promotion_agents"] = promo_agents[:5]

        # Outreach analytics for the trailing 24h window. We call the same
        # logic the dashboard endpoint uses, with days=1. The +/- 1h offset
        # vs the report's Berlin midnight is acceptable for a daily summary
        # (the endpoint's window is "now - 24h", which is what Anthony's
        # already seen scroll past in the dashboard).
        try:
            from app.api.reports_admin import outreach_analytics
            stats["outreach_yesterday"] = await outreach_analytics(days=1, db=db)
        except Exception as exc:
            logger.warning("daily_report.outreach_analytics_failed", error=str(exc))
            stats["outreach_yesterday"] = None

        return stats

    # ── phase21-005: autonomy + outreach analytics sections ──────────────────

    def _render_phase21_sections(self, stats: dict) -> str:
        """
        Two optional sections appended after Outreach E-Mails:
          🎯 Autonomie-Beförderungen — only when > 0 today
          📊 Outreach (24h)         — only when funnel has movement

        When BOTH are empty, returns an empty string (no headers, no
        separator) so the report stays under 60 lines on quiet days.
        """
        promotions = stats.get("autonomy_promotions_today", 0) or 0
        outreach = stats.get("outreach_yesterday") or {}
        funnel = (outreach.get("funnel") if isinstance(outreach, dict) else None) or {}

        any_outreach_movement = any(
            (funnel.get(k) or 0) > 0
            for k in ("sequences_started", "step_2_sent", "step_3_sent",
                      "step_4_sent", "replies", "bookings")
        )

        if promotions == 0 and not any_outreach_movement:
            return ""

        parts: list[str] = []

        if promotions > 0:
            agents = stats.get("autonomy_promotion_agents", []) or []
            agents_line = ", ".join(f"`{a}`" for a in agents) if agents else "—"
            parts.append(
                "## 🎯 Autonomie-Beförderungen — Heute\n\n"
                f"**{promotions}** P3→P2 promotion request(s) created today "
                "(phase19-010 14-day green-streak gate).\n\n"
                f"Agenten: {agents_line}\n\n"
                "> Bitte im Dashboard prüfen und genehmigen/ablehnen.\n"
                "\n---\n"
            )

        if any_outreach_movement:
            rates = outreach.get("rates") or {}
            def _pct(v):
                try: return f"{(float(v or 0) * 100):.2f}%"
                except (TypeError, ValueError): return "—"
            parts.append(
                "## 📊 Outreach (letzte 24h)\n\n"
                "| Metrik | Wert |\n"
                "|--------|-----:|\n"
                f"| Sequenzen gestartet | **{funnel.get('sequences_started', 0)}** |\n"
                f"| Step 2 versandt | {funnel.get('step_2_sent', 0)} |\n"
                f"| Step 3 versandt | {funnel.get('step_3_sent', 0)} |\n"
                f"| Step 4 versandt | {funnel.get('step_4_sent', 0)} |\n"
                f"| Antworten | **{funnel.get('replies', 0)}** |\n"
                f"| Termine gebucht | **{funnel.get('bookings', 0)}** |\n"
                f"| Unterdrückt (Engagement/Reply) | {funnel.get('suppressions', 0)} |\n"
                f"| Reply-Rate | {_pct(rates.get('reply_rate'))} |\n"
                f"| Booking-Rate | {_pct(rates.get('booking_rate'))} |\n"
                "\n---\n"
            )

        # Wrap in leading newline so it slots cleanly after the Outreach-E-Mails section
        return "\n" + "".join(parts)


    # ── Report formatting ─────────────────────────────────────────────────────

    def _format_report(self, report_date: date, stats: dict) -> str:
        dow = report_date.strftime("%A")  # e.g. "Monday"
        date_str = report_date.strftime("%-d. %B %Y")  # e.g. "7. May 2026"

        hot = stats["leads_today_hot"]
        warm = stats["leads_today_warm"]
        cold = stats["leads_today_cold"]
        unscored = stats["leads_today_unscored"]
        total_today = stats["leads_today"]

        # Score bar (simple ASCII)
        def bar(n: int, total: int, width: int = 10) -> str:
            if total == 0:
                return "░" * width
            filled = round(n / total * width)
            return "█" * filled + "░" * (width - filled)

        # Source table
        src_lines = []
        source_labels = {
            "chat": "Chat Widget",
            "contact_form": "Kontaktformular",
            "wp_webhook": "WP Webhook",
            "manual": "Manuell",
        }
        for src_key, src_label in source_labels.items():
            count = stats["leads_today_by_source"].get(src_key, 0)
            if count:
                src_lines.append(f"  - {src_label}: **{count}**")

        sources_block = "\n".join(src_lines) if src_lines else "  _Keine Leads heute_"

        # Pending approvals alert
        pending = stats["approvals_pending_total"]
        pending_alert = (
            f"\n> ⚠️  **{pending} Genehmigung{'en' if pending != 1 else ''} ausstehend** — "
            f"bitte im Dashboard prüfen.\n"
            if pending > 0
            else ""
        )

        # Funnel
        f_new = stats.get("funnel_new", 0)
        f_qual = stats.get("funnel_qualified", 0)
        f_disq = stats.get("funnel_disqualified", 0)
        f_prop = stats.get("funnel_proposal_sent", 0)
        f_won = stats.get("funnel_won", 0)
        f_lost = stats.get("funnel_lost", 0)
        f_total = f_new + f_qual + f_disq + f_prop + f_won + f_lost

        return f"""# 📊 Klaravex Tagesbericht — {dow}, {date_str}

_Automatisch generiert von Klaravex_

---
{pending_alert}
## 🧲 Leads — Heute

| Kategorie | Anzahl | Anteil |
|-----------|-------:|--------|
| 🔥 HOT (Score ≥ 70)  | **{hot}** | {bar(hot, total_today)} |
| 🌤 WARM (40–69)      | **{warm}** | {bar(warm, total_today)} |
| ❄️ KALT (< 40)       | **{cold}** | {bar(cold, total_today)} |
| ○ Nicht bewertet    | {unscored} | {bar(unscored, total_today)} |
| **Gesamt**          | **{total_today}** | |

**Letzte 7 Tage:** {stats['leads_7d']} Leads gesamt, davon {stats['leads_7d_hot']} HOT

**Herkunft heute:**
{sources_block}

---

## 🏭 Lead-Funnel (Gesamtbestand)

```
Neu         {f_new:>5}   →  Qualifiziert  {f_qual:>5}   →  Angebot versandt  {f_prop:>5}
                           Disqualifiziert {f_disq:>5}       Gewonnen          {f_won:>5}
                                                              Verloren          {f_lost:>5}
Gesamt: {f_total}
```

---

## ✅ Genehmigungen — Heute

| Status | Anzahl |
|--------|-------:|
| Erstellt heute | {stats['approvals_created_today']} |
| Genehmigt | **{stats['approvals_approved_today']}** |
| Abgelehnt | {stats['approvals_rejected_today']} |
| **Noch ausstehend (gesamt)** | **{pending}** |

---

## 📄 Proposals — Heute

| Metrik | Wert |
|--------|-----:|
| Entwürfe erstellt | **{stats['proposals_drafted_today']}** |
| Per E-Mail versandt | **{stats['proposals_emailed_today']}** |
| Proposals gesamt (alle Zeit) | {stats['proposals_total']} |
| Claude-Token heute | {stats['tokens_used_today']:,} |

---

## 📧 Outreach-E-Mails

| Metrik | Wert |
|--------|-----:|
| Genehmigt & versandt heute | **{stats['outreach_approved_today']}** |

---
{self._render_phase21_sections(stats)}
## 🩺 System-Status

- API: ✅ Online
- Worker: ✅ Aktiv
- Datenbank: ✅ Verbunden
- Celery Beat: ✅ Läuft

---

_Dieser Bericht wurde um {datetime.now(timezone.utc).strftime('%H:%M UTC')} generiert._
_Bei Fragen: Klaravex Admin Dashboard → /api/v1/approvals/_
"""
