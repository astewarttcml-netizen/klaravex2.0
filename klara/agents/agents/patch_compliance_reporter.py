"""
app/agents/patch_compliance_reporter.py
─────────────────────────────────────────
PatchComplianceReporterAgent — P2 service-delivery agent.

Generates a bilingual (EN + DE) BSI/DSGVO-compatible patch compliance report
for a managed endpoint client, saves it to the patch_reports table, and emails
it to the client's primary contact.

Triggers:
  - Celery beat task: Monday 08:00 CET  (see app/tasks/patch_compliance_beat.py)
  - Manual trigger:   POST /api/v1/admin/clients/{client_id}/patch-report

Input data:
  client_id                  (str)
  client_name                (str)
  report_period_start        (str)  — ISO date "YYYY-MM-DD"
  report_period_end          (str)  — ISO date "YYYY-MM-DD"
  total_devices              (int)
  patches_applied            (int)
  patches_failed             (int)
  patches_pending            (int)
  critical_patches_outstanding (list[dict])  — {kb, severity, days_outstanding}
  devices_offline            (list[str])     — hostnames
  primary_contact_email      (str)

Flow:
  1. Validate input.
  2. Generate bilingual Markdown report via Claude.
  3. Save report to patch_reports table (Alembic migration 0040 required — see comment).
  4. Email report to primary_contact_email via SMTP.
  5. Write AuditLog entry.
  6. Return AgentResult.ok() with report summary.

Permission: P2 — automated internal write + direct client email delivery.
No approval gate; report is factual/informational, not advisory.

───────────────────────────────────────────────────────────────────────────────
Alembic migration required — 0040_patch_reports.py
───────────────────────────────────────────────────────────────────────────────

\"\"\"
Migration: 0040_patch_reports

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


def upgrade():
    op.create_table(
        "patch_reports",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("client_id", sa.String(100), nullable=False, index=True),
        sa.Column("client_name", sa.String(255), nullable=False),
        sa.Column("report_period_start", sa.Date, nullable=False),
        sa.Column("report_period_end", sa.Date, nullable=False),
        sa.Column("total_devices", sa.Integer, nullable=False),
        sa.Column("patches_applied", sa.Integer, nullable=False),
        sa.Column("patches_failed", sa.Integer, nullable=False),
        sa.Column("patches_pending", sa.Integer, nullable=False),
        sa.Column("compliance_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("critical_outstanding_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("devices_offline_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("report_markdown_en", sa.Text, nullable=False),
        sa.Column("report_markdown_de", sa.Text, nullable=False),
        sa.Column("emailed_to", sa.String(255), nullable=True),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )


def downgrade():
    op.drop_table("patch_reports")
\"\"\"

───────────────────────────────────────────────────────────────────────────────
SQLAlchemy model (add to app/models/patch_report.py):
───────────────────────────────────────────────────────────────────────────────

\"\"\"
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PatchReport(Base):
    __tablename__ = "patch_reports"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    client_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    report_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    report_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    total_devices: Mapped[int] = mapped_column(Integer, nullable=False)
    patches_applied: Mapped[int] = mapped_column(Integer, nullable=False)
    patches_failed: Mapped[int] = mapped_column(Integer, nullable=False)
    patches_pending: Mapped[int] = mapped_column(Integer, nullable=False)
    compliance_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    critical_outstanding_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    devices_offline_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    report_markdown_en: Mapped[str] = mapped_column(Text, nullable=False)
    report_markdown_de: Mapped[str] = mapped_column(Text, nullable=False)
    emailed_to: Mapped[str | None] = mapped_column(String(255))
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
\"\"\"
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import text

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

_REPORT_PROMPT_EN = """\
You are a managed IT services engineer at Klaravex.
Write a professional English patch compliance report for a client.

Report data:
{data_json}

The report must be in Markdown with ## section headings and include:

## Executive Summary
One paragraph: overall patch rate, compliance percentage, and a brief risk
assessment. Use concrete numbers from the data.

## Patch Compliance Dashboard

| Metric | Value |
|--------|-------|
| Reporting Period | {period_start} – {period_end} |
| Total Managed Devices | {total_devices} |
| Patches Applied | {patches_applied} |
| Patches Failed | {patches_failed} |
| Patches Pending | {patches_pending} |
| **Compliance Rate** | **{compliance_pct:.1f}%** |
| Devices Offline | {offline_count} |

## Critical Outstanding Patches
{critical_table_instruction}

## BSI IT-Grundschutz OPS.1.1.3 Compliance Note
One paragraph referencing BSI IT-Grundschutz OPS.1.1.3 (Patch and Change
Management). State whether the current compliance rate meets the baseline
requirement, and note any critical items that represent material non-compliance.

## Recommended Actions
Numbered list of concrete remediation steps ordered by priority.
If patches_failed > 0: include a step to investigate and remediate each failed patch.
If critical_patches_outstanding is non-empty: escalate oldest items first.
If devices_offline is non-empty: include a device reachability check step.

## DSGVO Article 32 Note
One sentence stating that maintaining current patch status is a component of
the client's technical and organisational measures under DSGVO Article 32.

Tone: professional, factual, direct. No marketing language. No filler.
Output ONLY the Markdown — no preamble, no explanation outside the document.
"""

_REPORT_PROMPT_DE = """\
Sie sind ein Managed-IT-Services-Ingenieur bei Klaravex.
Schreiben Sie einen professionellen deutschen Patch-Compliance-Bericht für einen Kunden.

Berichtsdaten:
{data_json}

Der Bericht muss in Markdown mit ## Abschnittsüberschriften vorliegen und Folgendes enthalten:

## Zusammenfassung
Ein Absatz: Patch-Rate, Compliance-Prozentsatz und eine kurze Risikobewertung.
Konkrete Zahlen aus den Daten verwenden.

## Patch-Compliance-Dashboard

| Kennzahl | Wert |
|----------|------|
| Berichtszeitraum | {period_start} – {period_end} |
| Verwaltete Geräte gesamt | {total_devices} |
| Patches eingespielt | {patches_applied} |
| Patches fehlgeschlagen | {patches_failed} |
| Patches ausstehend | {patches_pending} |
| **Compliance-Rate** | **{compliance_pct:.1f}%** |
| Geräte offline | {offline_count} |

## Kritische ausstehende Patches
{critical_table_instruction}

## BSI IT-Grundschutz OPS.1.1.3 Hinweis
Ein Absatz mit Bezug auf BSI IT-Grundschutz OPS.1.1.3 (Patch- und Änderungsmanagement).
Angabe, ob die aktuelle Compliance-Rate die Grundanforderung erfüllt, und Hinweis auf
kritische Punkte, die eine wesentliche Nichteinhaltung darstellen.

## Empfohlene Maßnahmen
Nummerierte Liste konkreter Behebungsschritte, priorisiert nach Dringlichkeit.

## DSGVO-Artikel-32-Hinweis
Ein Satz: die Aufrechterhaltung des aktuellen Patch-Status ist ein Bestandteil der
technischen und organisatorischen Maßnahmen gemäß DSGVO Artikel 32.

Ton: professionell, sachlich, direkt. Keine Marketingsprache.
Ausgabe NUR das Markdown-Dokument — keine Präambel, keine Erklärung außerhalb des Dokuments.
"""


def _build_critical_table(critical_patches: list[dict], lang: str) -> str:
    if not critical_patches:
        if lang == "de":
            return "_Keine kritischen ausstehenden Patches._"
        return "_No critical patches outstanding._"

    if lang == "de":
        header = "| KB-Artikel | Schweregrad | Tage ausstehend |\n|------------|-------------|-----------------|"
    else:
        header = "| KB Article | Severity | Days Outstanding |\n|------------|----------|-----------------|"

    rows = "\n".join(
        f"| {p.get('kb', 'N/A')} | {p.get('severity', 'Unknown')} | {p.get('days_outstanding', '?')} |"
        for p in critical_patches
    )
    return f"{header}\n{rows}"


class PatchComplianceReporterAgent(BaseAgent):
    name = "patch_compliance_reporter"
    description = (
        "Generates a bilingual (EN + DE) BSI/DSGVO-compatible patch compliance "
        "report. Saves to patch_reports table and emails to the client contact. "
        "Trigger: Celery beat Monday 08:00 CET or "
        "POST /api/v1/admin/clients/{client_id}/patch-report."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        db = context.db
        log = logger.bind(
            agent=self.name,
            conversation_id=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        # ── Validate input ────────────────────────────────────────────────────
        client_id: str = (input_data.get("client_id") or "").strip()
        client_name: str = (input_data.get("client_name") or "").strip()
        period_start_str: str = (input_data.get("report_period_start") or "").strip()
        period_end_str: str = (input_data.get("report_period_end") or "").strip()
        primary_contact_email: str = (input_data.get("primary_contact_email") or "").strip()

        missing = [
            f for f, v in [
                ("client_id", client_id),
                ("client_name", client_name),
                ("report_period_start", period_start_str),
                ("report_period_end", period_end_str),
                ("primary_contact_email", primary_contact_email),
            ]
            if not v
        ]
        if missing:
            return AgentResult.fail(
                f"patch_compliance_reporter: missing required fields: {', '.join(missing)}",
                agent=self.name,
            )

        try:
            period_start = date.fromisoformat(period_start_str)
            period_end = date.fromisoformat(period_end_str)
        except ValueError as exc:
            return AgentResult.fail(
                f"patch_compliance_reporter: invalid date format — {exc}",
                agent=self.name,
            )

        try:
            total_devices: int = int(input_data.get("total_devices") or 0)
            patches_applied: int = int(input_data.get("patches_applied") or 0)
            patches_failed: int = int(input_data.get("patches_failed") or 0)
            patches_pending: int = int(input_data.get("patches_pending") or 0)
        except (TypeError, ValueError) as exc:
            return AgentResult.fail(
                f"patch_compliance_reporter: device/patch counts must be integers — {exc}",
                agent=self.name,
            )

        critical_patches: list[dict] = input_data.get("critical_patches_outstanding") or []
        devices_offline: list[str] = input_data.get("devices_offline") or []

        # Compliance % = applied / (applied + failed + pending) * 100
        total_actionable = patches_applied + patches_failed + patches_pending
        compliance_pct: float = (
            (patches_applied / total_actionable * 100) if total_actionable > 0 else 100.0
        )

        data_payload = {
            "client_id": client_id,
            "client_name": client_name,
            "report_period_start": period_start_str,
            "report_period_end": period_end_str,
            "total_devices": total_devices,
            "patches_applied": patches_applied,
            "patches_failed": patches_failed,
            "patches_pending": patches_pending,
            "compliance_pct": round(compliance_pct, 2),
            "critical_patches_outstanding": critical_patches,
            "devices_offline": devices_offline,
        }

        log.info(
            "patch_compliance_reporter.generating",
            client_id=client_id,
            client_name=client_name,
            compliance_pct=round(compliance_pct, 2),
        )

        # ── Generate bilingual report via Claude ──────────────────────────────
        anthropic_client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        prompt_kwargs = dict(
            data_json=json.dumps(data_payload, indent=2),
            period_start=period_start_str,
            period_end=period_end_str,
            total_devices=total_devices,
            patches_applied=patches_applied,
            patches_failed=patches_failed,
            patches_pending=patches_pending,
            compliance_pct=compliance_pct,
            offline_count=len(devices_offline),
        )

        try:
            en_response = await anthropic_client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=context.settings.anthropic_max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": _REPORT_PROMPT_EN.format(
                            **prompt_kwargs,
                            critical_table_instruction=_build_critical_table(
                                critical_patches, "en"
                            ),
                        ),
                    }
                ],
            )
            try:
                from app.services.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=context.settings.anthropic_model,
                    response=en_response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            report_en: str = en_response.content[0].text.strip()

            de_response = await anthropic_client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=context.settings.anthropic_max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": _REPORT_PROMPT_DE.format(
                            **prompt_kwargs,
                            critical_table_instruction=_build_critical_table(
                                critical_patches, "de"
                            ),
                        ),
                    }
                ],
            )
            try:
                from app.services.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=context.settings.anthropic_model,
                    response=de_response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            report_de: str = de_response.content[0].text.strip()

            tokens_used: int = (
                en_response.usage.output_tokens + de_response.usage.output_tokens
            )
        except Exception as exc:
            log.error(
                "patch_compliance_reporter.claude_error",
                error=str(exc),
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            return AgentResult.fail(
                f"patch_compliance_reporter: LLM error — {exc}",
                agent=self.name,
            )

        log.info(
            "patch_compliance_reporter.reports_generated",
            client_id=client_id,
            tokens_used=tokens_used,
        )

        # ── Persist to patch_reports table ────────────────────────────────────
        # patch_reports table is created by migration 0040_patch_reports.
        # Using raw SQL insert to avoid requiring the model import at this layer;
        # the ORM model lives in app/models/patch_report.py (see module docstring).
        report_id = str(uuid4())
        now_utc = datetime.now(timezone.utc)

        try:
            await db.execute(
                text(
                    """
                    INSERT INTO patch_reports (
                        id, client_id, client_name,
                        report_period_start, report_period_end,
                        total_devices, patches_applied, patches_failed, patches_pending,
                        compliance_pct,
                        critical_outstanding_json, devices_offline_json,
                        report_markdown_en, report_markdown_de,
                        created_at
                    ) VALUES (
                        :id, :client_id, :client_name,
                        :period_start, :period_end,
                        :total_devices, :patches_applied, :patches_failed, :patches_pending,
                        :compliance_pct,
                        :critical_json, :offline_json,
                        :report_en, :report_de,
                        :created_at
                    )
                    """
                ),
                {
                    "id": report_id,
                    "client_id": client_id,
                    "client_name": client_name,
                    "period_start": period_start,
                    "period_end": period_end,
                    "total_devices": total_devices,
                    "patches_applied": patches_applied,
                    "patches_failed": patches_failed,
                    "patches_pending": patches_pending,
                    "compliance_pct": round(compliance_pct, 2),
                    "critical_json": json.dumps(critical_patches),
                    "offline_json": json.dumps(devices_offline),
                    "report_en": report_en,
                    "report_de": report_de,
                    "created_at": now_utc,
                },
            )
            await db.commit()
            log.info(
                "patch_compliance_reporter.saved",
                report_id=report_id,
                client_id=client_id,
            )
        except Exception as exc:
            log.error(
                "patch_compliance_reporter.db_error",
                error=str(exc),
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            return AgentResult.fail(
                f"patch_compliance_reporter: database write failed — {exc}",
                agent=self.name,
            )

        # ── Email report to client ────────────────────────────────────────────
        email_sent = False
        try:
            from app.services.email_sender import send_transactional_email

            subject = (
                f"Klaravex — Patch Compliance Report "
                f"{period_start_str} to {period_end_str} | "
                f"{client_name}"
            )
            body_text = (
                f"Dear {client_name},\n\n"
                f"Please find below your patch compliance report for the period "
                f"{period_start_str} to {period_end_str}.\n\n"
                f"Compliance Rate: {compliance_pct:.1f}%\n\n"
                f"--- ENGLISH REPORT ---\n\n{report_en}\n\n"
                f"--- DEUTSCHER BERICHT ---\n\n{report_de}\n\n"
                f"Klaravex"
            )
            body_html = _render_email_html(
                client_name=client_name,
                period_start=period_start_str,
                period_end=period_end_str,
                compliance_pct=compliance_pct,
                report_en=report_en,
                report_de=report_de,
            )

            email_sent = await send_transactional_email(
                context.settings,
                to_email=primary_contact_email,
                to_name=client_name,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
            )

            if email_sent:
                # Update emailed_at timestamp
                await db.execute(
                    text(
                        "UPDATE patch_reports SET emailed_to=:to, emailed_at=:at "
                        "WHERE id=:id"
                    ),
                    {"to": primary_contact_email, "at": datetime.now(timezone.utc), "id": report_id},
                )
                await db.commit()
                log.info(
                    "patch_compliance_reporter.emailed",
                    report_id=report_id,
                    to=primary_contact_email,
                )
            else:
                log.warning(
                    "patch_compliance_reporter.email_not_sent",
                    report_id=report_id,
                    to=primary_contact_email,
                )
        except Exception as exc:
            # Email failure must not invalidate the report that was already saved.
            log.error(
                "patch_compliance_reporter.email_error",
                error=str(exc),
                exc_info=True,
            )

        # ── Write AuditLog entry ──────────────────────────────────────────────
        try:
            from app.agents.registry import registry
            audit_agent = registry.get("audit_logger")
            await audit_agent(
                context,
                {
                    "event_type": "agent.action",
                    "agent_name": self.name,
                    "action_name": "patch_compliance_reporter.generate",
                    "details": {
                        "report_id": report_id,
                        "client_id": client_id,
                        "client_name": client_name,
                        "compliance_pct": round(compliance_pct, 2),
                        "tokens_used": tokens_used,
                        "email_sent": email_sent,
                    },
                    "success": True,
                },
            )
        except Exception as exc:
            log.warning("patch_compliance_reporter.audit_warning", error=str(exc))

        return AgentResult.ok(
            output={
                "report_id": report_id,
                "client_id": client_id,
                "client_name": client_name,
                "period_start": period_start_str,
                "period_end": period_end_str,
                "compliance_pct": round(compliance_pct, 2),
                "patches_applied": patches_applied,
                "patches_failed": patches_failed,
                "patches_pending": patches_pending,
                "critical_outstanding_count": len(critical_patches),
                "devices_offline_count": len(devices_offline),
                "tokens_used": tokens_used,
                "email_sent": email_sent,
            },
            agent=self.name,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _render_email_html(
    *,
    client_name: str,
    period_start: str,
    period_end: str,
    compliance_pct: float,
    report_en: str,
    report_de: str,
) -> str:
    """Wrap the two Markdown reports in a minimal HTML email shell."""
    compliance_color = "#2e7d32" if compliance_pct >= 90 else "#e65100" if compliance_pct < 70 else "#f9a825"

    # Convert newlines to <br> for the pre blocks
    def _pre(text: str) -> str:
        return f"<pre style='white-space:pre-wrap;font-family:monospace;font-size:13px;" \
               f"background:#f5f5f5;padding:16px;border-radius:4px;'>{text}</pre>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px;color:#222;">
  <div style="border-left:4px solid {compliance_color};background:#fafafa;
              padding:12px 16px;border-radius:4px;margin-bottom:24px;">
    <strong>Patch Compliance Report — {client_name}</strong><br>
    <span style="font-size:13px;">Period: {period_start} to {period_end}</span><br>
    <span style="font-size:18px;font-weight:bold;color:{compliance_color};">
      Compliance: {compliance_pct:.1f}%
    </span>
  </div>
  <h2 style="color:#1a1a2e;">English Report</h2>
  {_pre(report_en)}
  <h2 style="color:#1a1a2e;margin-top:32px;">Deutscher Bericht</h2>
  {_pre(report_de)}
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
  <p style="font-size:12px;color:#999;">
    Generated by Klaravex · Klara AI PatchComplianceReporterAgent ·
    klaravex.de
  </p>
</body>
</html>"""
