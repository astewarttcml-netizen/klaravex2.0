"""
app/tasks/daily_report.py
──────────────────────────
Celery task: generate and email the daily operations report.

Scheduled via celery beat at 07:00 Europe/Berlin every morning.
Can also be triggered manually via POST /api/v1/reports/trigger.

Flow:
  1. Call DailyReportAgent → markdown + stats
  2. Persist DailyReport row to DB
  3. Convert markdown to HTML
  4. Email to settings.approval_notify_email
  5. Update DailyReport row with emailed_at
"""
import asyncio
import json
import re
import uuid
from datetime import date, datetime, timezone

import structlog

from klara.rarv.runtime import celery_app
from klara.rarv.runtime import get_settings
from klara.rarv.runtime import db_context

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.daily_report.generate_daily_report",
    bind=True,
    max_retries=2,
    default_retry_delay=300,  # 5 min retry delay
)
def generate_daily_report(self, report_date: str | None = None, triggered_by: str = "celery_beat"):
    """
    Celery task entry point (synchronous wrapper around async implementation).

    Args:
        report_date:  ISO date string "YYYY-MM-DD" — defaults to yesterday.
        triggered_by: Who triggered this task (for audit trail).
    """
    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        asyncio.run(_generate(report_date=report_date, triggered_by=triggered_by))
    except Exception as exc:
        logger.error(
            "daily_report.task_failed",
            report_date=report_date,
            triggered_by=triggered_by,
            error=str(exc),
            exc_info=True,
        )
        raise self.retry(exc=exc)


async def _generate(report_date: str | None, triggered_by: str) -> dict:
    """Async implementation — runs inside Celery worker's event loop."""
    from klara.rarv.runtime import AgentContext
    from app.agents.registry import registry
    from klara.rarv.report import DailyReport

    settings = get_settings()

    async with db_context() as db:
        # conversation_id/request_id/lead_id required by AgentContext; report task has no specific lead
        context = AgentContext(
            db=db,
            settings=settings,
            conversation_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            lead_id=None,
        )
        agent = registry.get("daily_report")

        # ── 1. Generate report ────────────────────────────────────────────────
        result = await agent(
            context,
            {
                "report_date": report_date,
                "triggered_by": triggered_by,
            },
        )

        if not result.success:
            logger.error("daily_report.agent_failed", error=result.error)
            raise RuntimeError(f"DailyReportAgent failed: {result.error}")

        output = result.output
        markdown = output["report_markdown"]
        stats = output["stats_json"]
        rdate_str = output["report_date"]  # ISO string — used for display / email / return value
        rdate = date.fromisoformat(rdate_str) if isinstance(rdate_str, str) else rdate_str

        # ── 2. Persist to DB ──────────────────────────────────────────────────
        report = DailyReport(
            report_date=rdate,
            report_type="daily",
            triggered_by=triggered_by,
            report_markdown=markdown,
            stats_json=json.dumps(stats),
        )
        db.add(report)
        await db.flush()  # get the ID before emailing
        report_id = report.id

        logger.info(
            "daily_report.persisted",
            report_id=report_id,
            report_date=rdate,
        )

        # ── 3. Email the report ───────────────────────────────────────────────
        from klara.rarv.runtime.email_sender import send_transactional_email

        admin_email = settings.approval_notify_email
        body_html = _report_to_html(markdown, rdate_str)

        emailed = await send_transactional_email(
            settings,
            to_email=admin_email,
            to_name="Klaravex — Admin",
            subject=f"📊 Klaravex Tagesbericht — {rdate}",
            body_html=body_html,
            body_text=markdown,
        )

        if emailed:
            report.emailed_to = admin_email
            report.emailed_at = datetime.now(timezone.utc)

        logger.info(
            "daily_report.emailed",
            report_id=report_id,
            report_date=rdate,
            to=admin_email,
            sent=emailed,
        )

    return {"report_id": report_id, "report_date": rdate_str, "emailed": emailed}


def _report_to_html(markdown_text: str, report_date: str) -> str:
    """Convert report markdown to a styled HTML email body."""
    html = markdown_text

    # Headings
    html = re.sub(r"^#{3}\s+(.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^#{2}\s+(.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^#{1}\s+(.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

    # Bold and italic
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)

    # Blockquotes
    html = re.sub(
        r"(^>.*$(\n>.*$)*)",
        lambda m: f'<blockquote>{m.group(0).replace("> ", "").replace(">", "")}</blockquote>',
        html,
        flags=re.MULTILINE,
    )

    # Code blocks (```...```)
    html = re.sub(
        r"```[\w]*\n([\s\S]*?)```",
        lambda m: f"<pre><code>{m.group(1)}</code></pre>",
        html,
    )

    # Markdown tables → HTML tables
    def _table_to_html(m) -> str:
        lines = m.group(0).strip().split("\n")
        # First line: header
        headers = [h.strip() for h in lines[0].strip("|").split("|")]
        # Third line onward: data rows (skip the separator line[1])
        rows = []
        for line in lines[2:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows.append(cells)

        head_html = "".join(f"<th>{h}</th>" for h in headers)
        rows_html = ""
        for row in rows:
            cells_html = "".join(f"<td>{c}</td>" for c in row)
            rows_html += f"<tr>{cells_html}</tr>"
        return f"<table><thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table>"

    html = re.sub(
        r"(\|.+\|\n\|[-| :]+\|\n(?:\|.+\|\n?)+)",
        _table_to_html,
        html,
        flags=re.MULTILINE,
    )

    # Bullet lists
    def _list_block(m):
        items = re.sub(r"^[-*]\s+(.+)$", r"<li>\1</li>", m.group(0), flags=re.MULTILINE)
        return f"<ul>{items}</ul>"

    html = re.sub(
        r"(^[-*]\s+.+$(\n[-*]\s+.+$)*)",
        _list_block,
        html,
        flags=re.MULTILINE,
    )

    # Horizontal rules
    html = re.sub(r"^---$", "<hr>", html, flags=re.MULTILINE)

    # Italics for _..._
    html = re.sub(r"_(.+?)_", r"<em>\1</em>", html)

    # Paragraphs
    blocks = re.split(r"\n{2,}", html)
    result_blocks = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if re.match(r"^<(h[1-6]|ul|ol|table|pre|blockquote|hr)", block):
            result_blocks.append(block)
        else:
            result_blocks.append(f"<p>{block}</p>")
    body = "\n".join(result_blocks)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 14px; color: #222; max-width: 720px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 22px; color: #1a1a2e; border-bottom: 2px solid #1a1a2e; padding-bottom: 8px; }}
  h2 {{ font-size: 16px; color: #1a1a2e; margin-top: 28px; }}
  h3 {{ font-size: 14px; color: #333; }}
  p {{ line-height: 1.6; }}
  ul {{ padding-left: 20px; }}
  li {{ line-height: 1.6; margin-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th {{ background: #1a1a2e; color: white; padding: 8px 12px; text-align: left; font-size: 13px; }}
  td {{ padding: 7px 12px; border-bottom: 1px solid #eee; font-size: 13px; }}
  tr:nth-child(even) td {{ background: #f8f8ff; }}
  pre {{ background: #f4f4f4; padding: 14px; border-radius: 4px; font-size: 12px; overflow-x: auto; }}
  code {{ font-family: 'Courier New', monospace; }}
  blockquote {{ background: #fff3cd; border-left: 4px solid #ffc107; margin: 12px 0; padding: 10px 16px; border-radius: 0 4px 4px 0; }}
  hr {{ border: none; border-top: 1px solid #eee; margin: 24px 0; }}
  .header {{ background: #1a1a2e; color: white; padding: 18px 24px; border-radius: 4px; margin-bottom: 24px; }}
  .footer {{ color: #888; font-size: 12px; margin-top: 32px; border-top: 1px solid #eee; padding-top: 12px; }}
</style>
</head>
<body>
  <div class="header">
    <strong>📊 Klaravex Tagesbericht</strong><br>
    <span style="font-size:13px; opacity:0.8;">Klaravex · {report_date}</span>
  </div>
  {body}
  <div class="footer">
    Automatisch generiert von Klaravex · <a href="https://api.klaravex.de/api/v1/reports/" style="color:#888;">Reports öffnen</a>
  </div>
</body>
</html>"""
