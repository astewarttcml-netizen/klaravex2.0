"""
app/agents/approval_notifier.py
────────────────────────────────
P1 agent — sweeps approval_requests for pending items that have not yet
been emailed to Anthony and sends a grouped digest.

Triggered by: Celery beat every 30 minutes.
Also callable directly via POST /api/v1/agents/run.

Why this agent is necessary:
  ApprovalManagerAgent creates ApprovalRequest rows when P3/P4/P5 actions
  need human review.  Without notification, Anthony must manually open the
  admin dashboard (/admin) to discover outstanding items — in practice that
  means approvals sit unreviewed for hours or indefinitely.

  This agent closes the loop: as soon as a new pending approval appears,
  Anthony receives a consolidated email digest with a direct link to act.

Idempotency:
  approval_requests.notified_at is NULL on creation.
  This agent queries WHERE notified_at IS NULL AND status='pending',
  sends the email, then stamps notified_at = now() on each row.
  Subsequent sweeps see notified_at IS NOT NULL and skip those rows.

  Re-notification is intentionally NOT done.  If Anthony misses the email
  and the request expires, that is visible in the dashboard.  Spammy
  re-alerts would train him to ignore them.

Permission: P1 — read-only DB access + outbound email.  No side-effects
  on leads, proposals, or external services.  Email target is internal
  (Anthony), not a client.  No approval gate needed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select

from app.agents.base import BaseAgent, AgentContext, AgentResult, PermissionLevel
from app.models.approval import ApprovalRequest, ApprovalStatus

logger = structlog.get_logger(__name__)

# Risk-level display config — higher risk → rendered more prominently in email
_RISK_ORDER = ["P5", "P4", "P3"]
_RISK_COLOR = {
    "P5": "#6a1b9a",   # purple — client environment
    "P4": "#c62828",   # red    — legal / billing
    "P3": "#e65100",   # orange — outbound / publishing
}
_RISK_LABEL = {
    "P5": "P5 — Client environment (2-approver)",
    "P4": "P4 — Legal / billing",
    "P3": "P3 — Outbound / publishing",
}


class ApprovalNotifierAgent(BaseAgent):
    name = "approval_notifier"
    permission_level = PermissionLevel.P1
    description = (
        "30-min sweep: finds pending approval requests (P3/P4/P5) that have not "
        "yet been emailed to Anthony. Sends a single grouped digest with a direct "
        "link to the admin dashboard. Stamps notified_at on each row to prevent "
        "duplicate alerts. P1 — internal notification only, no approval needed."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        # ── Fetch unnotified pending approvals ────────────────────────────────
        rows = (await context.db.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalStatus.pending)
            .where(ApprovalRequest.notified_at.is_(None))
            .order_by(ApprovalRequest.created_at.asc())
        )).scalars().all()

        if not rows:
            log.info("approval_notifier.nothing_to_notify")
            return AgentResult.ok({"status": "no_pending_approvals", "notified": 0})

        log.info("approval_notifier.pending_found", count=len(rows))

        # ── Group by risk level ───────────────────────────────────────────────
        groups: dict[str, list[ApprovalRequest]] = {level: [] for level in _RISK_ORDER}
        for row in rows:
            level = row.risk_level.upper()
            if level not in groups:
                level = "P3"   # fallback — shouldn't happen but defensive
            groups[level].append(row)

        # ── Build email ───────────────────────────────────────────────────────
        settings = context.settings
        notify_email = getattr(settings, "approval_notify_email", "hello@klaravex.de")
        dashboard_url = (
            getattr(settings, "api_base_url", "https://api.klaravex.de") + "/admin"
        )

        total = len(rows)
        p5_count = len(groups["P5"])
        p4_count = len(groups["P4"])
        p3_count = len(groups["P3"])

        subject = (
            f"[Klara AI] {total} approval{'s' if total > 1 else ''} awaiting review"
            + (f" — {p5_count} P5" if p5_count else "")
            + (f" — {p4_count} P4" if p4_count else "")
        )

        html_body = _render_digest_email(
            groups=groups,
            dashboard_url=dashboard_url,
            total=total,
        )
        text_body = _render_digest_text(
            groups=groups,
            dashboard_url=dashboard_url,
            total=total,
        )

        try:
            from app.services.email_sender import send_transactional_email
            await send_transactional_email(
                settings,
                to_email=notify_email,
                to_name="Anthony",
                subject=subject,
                body_html=html_body,
                body_text=text_body,
            )
        except Exception as exc:
            log.error("approval_notifier.email_failed", error=str(exc))
            # Do NOT stamp notified_at — let the next sweep retry.
            return AgentResult.fail(f"Email send failed: {exc}")

        # ── Stamp notified_at on all rows ─────────────────────────────────────
        now = datetime.now(timezone.utc)
        for row in rows:
            row.notified_at = now
        await context.db.flush()

        notified_ids = [r.id for r in rows]
        log.info(
            "approval_notifier.digest_sent",
            total=total,
            p5=p5_count,
            p4=p4_count,
            p3=p3_count,
            to=notify_email,
        )

        return AgentResult.ok({
            "status": "notified",
            "notified": total,
            "p5": p5_count,
            "p4": p4_count,
            "p3": p3_count,
            "approval_ids": notified_ids,
        })


# ── Email renderers ───────────────────────────────────────────────────────────

def _age(created_at: datetime) -> str:
    """Human-readable age string relative to now."""
    diff = datetime.now(timezone.utc) - created_at
    mins = int(diff.total_seconds() // 60)
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    return f"{hrs // 24}d ago"


def _render_digest_email(
    groups: dict[str, list[ApprovalRequest]],
    dashboard_url: str,
    total: int,
) -> str:
    sections = ""
    for level in _RISK_ORDER:
        items = groups[level]
        if not items:
            continue
        color = _RISK_COLOR[level]
        label = _RISK_LABEL[level]
        rows_html = ""
        for req in items:
            justification = (req.justification or "").strip()
            if len(justification) > 120:
                justification = justification[:120] + "…"
            rows_html += f"""
            <tr>
              <td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:13px;
                         font-weight:600;color:#222;">{_esc(req.action_name)}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:12px;
                         color:#555;">{_esc(req.requested_by_agent)}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:12px;
                         color:#999;">{_age(req.created_at)}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:12px;
                         color:#555;">{_esc(justification or '—')}</td>
            </tr>"""

        sections += f"""
        <div style="margin-bottom:24px;">
          <div style="background:{color};color:#fff;padding:8px 14px;border-radius:6px 6px 0 0;
                      font-size:13px;font-weight:700;">{label} ({len(items)})</div>
          <table style="width:100%;border-collapse:collapse;background:#fff;
                        border:1px solid #eee;border-top:none;">
            <thead>
              <tr style="background:#f9f9f9;">
                <th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;
                           text-transform:uppercase;letter-spacing:.05em;">Action</th>
                <th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;
                           text-transform:uppercase;letter-spacing:.05em;">Agent</th>
                <th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;
                           text-transform:uppercase;letter-spacing:.05em;">Age</th>
                <th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;
                           text-transform:uppercase;letter-spacing:.05em;">Justification</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:740px;margin:0 auto;
             padding:24px;color:#222;background:#f5f5f5;">

<div style="background:#fff;border-radius:8px;padding:28px;
            box-shadow:0 2px 10px rgba(0,0,0,.07);">

  <h2 style="margin:0 0 6px;color:#1565c0;font-size:20px;">
    ⚡ Klara AI — {total} Approval{'s' if total > 1 else ''} Pending
  </h2>
  <p style="margin:0 0 20px;color:#666;font-size:14px;">
    The following actions are waiting for your review.
  </p>

  {sections}

  <div style="text-align:center;margin-top:20px;">
    <a href="{dashboard_url}"
       style="display:inline-block;background:#1565c0;color:#fff;padding:13px 32px;
              border-radius:6px;text-decoration:none;font-size:15px;font-weight:700;">
      Open Approval Dashboard →
    </a>
  </div>

  <hr style="border:none;border-top:1px solid #eee;margin:24px 0 16px;">
  <p style="font-size:11px;color:#bbb;text-align:center;">
    Klara AI ApprovalNotifierAgent · Klaravex · Sent to {_esc(dashboard_url.split('/admin')[0].replace('https://','').replace('http://',''))}
  </p>
</div>
</body>
</html>"""


def _render_digest_text(
    groups: dict[str, list[ApprovalRequest]],
    dashboard_url: str,
    total: int,
) -> str:
    lines = [
        f"Klara AI — {total} approval{'s' if total > 1 else ''} pending",
        "=" * 50,
        "",
    ]
    for level in _RISK_ORDER:
        items = groups[level]
        if not items:
            continue
        lines.append(f"[{level}] {_RISK_LABEL[level]} — {len(items)} item(s)")
        lines.append("-" * 40)
        for req in items:
            justification = (req.justification or "—").strip()
            if len(justification) > 100:
                justification = justification[:100] + "…"
            lines.append(f"  Action:  {req.action_name}")
            lines.append(f"  Agent:   {req.requested_by_agent}")
            lines.append(f"  Age:     {_age(req.created_at)}")
            lines.append(f"  Why:     {justification}")
            lines.append("")
    lines += [
        "Open dashboard:",
        dashboard_url,
        "",
        "—",
        "Klara AI ApprovalNotifierAgent · Klaravex",
    ]
    return "\n".join(lines)


def _esc(s: Any) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
