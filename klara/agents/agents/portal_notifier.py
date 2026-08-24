"""
app/agents/portal_notifier.py
───────────────────────────────
P2 agent — notifies a client by email when a file is uploaded or updated
in their client portal.

Triggered by:
  1. PATCH /api/v1/admin/files/{id}/label  — automatically when a file is
     promoted to "approved" or "delivered" (wired in portal_files_admin.py)
  2. POST /api/v1/agents/run with agent="portal_notifier"  — manual trigger

Payload:
  {
    "lead_id":   "<uuid>",          (pre-sale lead — mutually exclusive with client_id)
    "client_id": "<uuid>",          (portal client — preferred for post-sale use)
    "filename":  "M365_Migration_Plan_v2.pdf",
    "file_url":  "https://portal.klaravex.de/files/...",
    "action":    "uploaded" | "updated" | "shared",
    "notes":     "Phase 2 scope doc attached"   (optional)
  }

Exactly one of lead_id or client_id is required.  client_id is the correct
choice for all portal file events (post-sale clients); lead_id is retained
for backward compatibility with manual / pre-sale use.

Flow:
  1. Load Client (by client_id) OR Lead (by lead_id) — verify email present
  2. Render a short notification email (EN or DE based on email domain /
     client language preference)
  3. Send immediately — P2, informational only, no approval needed
  4. Idempotency: not enforced per-file (multiple files can be shared);
     caller is responsible for deduplication if needed.

Permission: P2 — client-facing but purely informational (no PII beyond
their own name/email, no financial data, no commitments).
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from klara.rarv.runtime import BaseAgent, AgentContext, AgentResult, PermissionLevel
from klara.rarv.lead import Lead

logger = structlog.get_logger(__name__)

_NOTIFY_TEMPLATE_EN = textwrap.dedent("""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;
             padding:20px;color:#222;">
<h2 style="color:#1565c0;">New File Available — {filename}</h2>

<p>Hi {name},</p>

<p>A file has been {action} to your client portal:</p>

<table style="border-collapse:collapse;width:100%;margin:16px 0;">
  <tr style="background:#e3f2fd;">
    <td style="padding:8px 12px;font-weight:bold;">File</td>
    <td style="padding:8px 12px;">{filename}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;font-weight:bold;">Action</td>
    <td style="padding:8px 12px;">{action_label}</td>
  </tr>
  <tr style="background:#f5f5f5;">
    <td style="padding:8px 12px;font-weight:bold;">Date</td>
    <td style="padding:8px 12px;">{date}</td>
  </tr>
  {notes_row}
</table>

<p>
  <a href="{file_url}"
     style="display:inline-block;background:#1565c0;color:#fff;
            padding:10px 20px;border-radius:4px;text-decoration:none;
            font-weight:bold;">
    View File
  </a>
</p>

<p>If you have any questions about this document, please reply to this
email or book a call via my Calendly link.</p>

<p>Best regards,<br>
<strong>Anthony Stewart</strong><br>
Klaravex<br>
<a href="https://klaravex.de">klaravex.de</a>
</p>

<hr style="border:none;border-top:1px solid #eee;margin-top:32px;">
<p style="font-size:11px;color:#999;">
  You are receiving this because you are a client of Klaravex.
  Klaravex · klaravex.de
</p>
</body>
</html>
""")

_NOTIFY_TEMPLATE_DE = textwrap.dedent("""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;
             padding:20px;color:#222;">
<h2 style="color:#1565c0;">Neue Datei verfügbar — {filename}</h2>

<p>Guten Tag {name},</p>

<p>Eine Datei wurde in Ihrem Kundenportal {action_de}:</p>

<table style="border-collapse:collapse;width:100%;margin:16px 0;">
  <tr style="background:#e3f2fd;">
    <td style="padding:8px 12px;font-weight:bold;">Datei</td>
    <td style="padding:8px 12px;">{filename}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;font-weight:bold;">Aktion</td>
    <td style="padding:8px 12px;">{action_label_de}</td>
  </tr>
  <tr style="background:#f5f5f5;">
    <td style="padding:8px 12px;font-weight:bold;">Datum</td>
    <td style="padding:8px 12px;">{date}</td>
  </tr>
  {notes_row}
</table>

<p>
  <a href="{file_url}"
     style="display:inline-block;background:#1565c0;color:#fff;
            padding:10px 20px;border-radius:4px;text-decoration:none;
            font-weight:bold;">
    Datei anzeigen
  </a>
</p>

<p>Bei Fragen zu diesem Dokument antworten Sie bitte auf diese E-Mail oder
buchen Sie einen Termin über meinen Calendly-Link.</p>

<p>Mit freundlichen Grüßen,<br>
<strong>Anthony Stewart</strong><br>
Klaravex<br>
<a href="https://klaravex.de">klaravex.de</a>
</p>

<hr style="border:none;border-top:1px solid #eee;margin-top:32px;">
<p style="font-size:11px;color:#999;">
  Sie erhalten diese Nachricht als Kunde von Klaravex.
  Klaravex · klaravex.de
</p>
</body>
</html>
""")

_ACTION_LABELS_EN = {
    "uploaded": "uploaded",
    "updated": "updated",
    "shared": "shared with you",
}
_ACTION_LABELS_DE = {
    "uploaded": "hochgeladen",
    "updated": "aktualisiert",
    "shared": "für Sie freigegeben",
}


class PortalNotifierAgent(BaseAgent):
    name = "portal_notifier"
    permission_level = PermissionLevel.P2
    description = (
        "Sends a client notification email when a file is uploaded, updated, or "
        "shared in the client portal. Requires filename, file_url, and action "
        "('uploaded'|'updated'|'shared'). Supply either client_id (preferred for "
        "portal clients) or lead_id (pre-sale / backward compat). Optional 'notes'. "
        "P2 — informational client email, no approval needed."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        client_id = payload.get("client_id")
        lead_id = context.lead_id or payload.get("lead_id")
        filename = payload.get("filename", "")
        file_url = payload.get("file_url", "")
        action = payload.get("action", "uploaded").lower()
        notes = payload.get("notes", "")

        if not client_id and not lead_id:
            return AgentResult.fail(
                "portal_notifier: one of 'client_id' or 'lead_id' is required.",
                agent=self.name,
            )
        if not filename:
            return AgentResult.fail("portal_notifier: 'filename' is required.", agent=self.name)
        if not file_url:
            return AgentResult.fail("portal_notifier: 'file_url' is required.", agent=self.name)
        if action not in _ACTION_LABELS_EN:
            action = "uploaded"

        # ── Resolve recipient — Client path (preferred) ───────────────────────
        if client_id:
            recipient_email, recipient_name, language = await self._resolve_client(
                context, client_id, log
            )
            if recipient_email is None:
                return AgentResult.fail(
                    f"portal_notifier: client {client_id} not found, anonymised, or has no email.",
                    agent=self.name,
                )
        else:
            # ── Resolve recipient — Lead path (backward compat) ───────────────
            recipient_email, recipient_name, language = await self._resolve_lead(
                context, lead_id, log
            )
            if recipient_email is None:
                return AgentResult.fail(
                    f"portal_notifier: lead {lead_id} not found, anonymised, or has no email.",
                    agent=self.name,
                )

        now_str = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
        first_name = recipient_name.split()[0] if recipient_name else (
            "there" if language == "en" else "Sie"
        )

        # ── Build optional notes row ──────────────────────────────────────────
        if notes:
            if language == "de":
                notes_row = (
                    f"<tr><td style='padding:8px 12px;font-weight:bold;'>Hinweis</td>"
                    f"<td style='padding:8px 12px;'>{notes}</td></tr>"
                )
            else:
                notes_row = (
                    f"<tr><td style='padding:8px 12px;font-weight:bold;'>Notes</td>"
                    f"<td style='padding:8px 12px;'>{notes}</td></tr>"
                )
        else:
            notes_row = ""

        if language == "de":
            html = _NOTIFY_TEMPLATE_DE.format(
                name=first_name,
                filename=filename,
                action_de=_ACTION_LABELS_DE.get(action, "hochgeladen"),
                action_label_de=_ACTION_LABELS_DE.get(action, "Hochgeladen").capitalize(),
                file_url=file_url,
                date=now_str,
                notes_row=notes_row,
            )
            subject = f"Neue Datei verfügbar: {filename}"
        else:
            html = _NOTIFY_TEMPLATE_EN.format(
                name=first_name,
                filename=filename,
                action=_ACTION_LABELS_EN.get(action, "uploaded"),
                action_label=_ACTION_LABELS_EN.get(action, "Uploaded").capitalize(),
                file_url=file_url,
                date=now_str,
                notes_row=notes_row,
            )
            subject = f"New file available: {filename}"

        log.info(
            "portal_notifier.sending",
            client_id=client_id,
            lead_id=lead_id,
            filename=filename,
            action=action,
            language=language,
        )

        try:
            from klara.rarv.runtime.email_sender import send_transactional_email
            await send_transactional_email(
                context.settings,
                to_email=recipient_email,
                to_name=recipient_name or recipient_email,
                subject=subject,
                body_html=html,
                body_text=(
                    f"Hi {first_name},\n\n"
                    f"A file has been {action} to your portal: {filename}\n"
                    f"View it here: {file_url}\n\n"
                    f"{('Notes: ' + notes) if notes else ''}\n\n"
                    "Best regards,\nAnthony Stewart\nKlaravex"
                ),
            )
        except Exception as exc:
            log.error("portal_notifier.email_failed", error=str(exc))
            return AgentResult.fail(str(exc), agent=self.name)

        log.info(
            "portal_notifier.sent",
            client_id=client_id,
            lead_id=lead_id,
            filename=filename,
            to_email=recipient_email,
        )

        return AgentResult.ok(
            {
                "status": "sent",
                "client_id": client_id,
                "lead_id": lead_id,
                "filename": filename,
                "action": action,
                "to_email": recipient_email,
                "language": language,
            },
            agent=self.name,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _resolve_client(
        self, context: AgentContext, client_id: str, log
    ) -> tuple[str | None, str | None, str]:
        """Load a portal Client row and return (email, name, language)."""
        try:
            from klara.rarv.portal import Client
            result = await context.db.execute(
                select(Client).where(Client.id == client_id)
            )
            client = result.scalar_one_or_none()
        except Exception as exc:
            log.error("portal_notifier.client_load_error", error=str(exc))
            return None, None, "en"

        if not client or not client.is_active or not client.email:
            return None, None, "en"

        language = client.language_preference or _detect_language_from_email(client.email)
        return client.email, client.name or client.email, language

    async def _resolve_lead(
        self, context: AgentContext, lead_id: str, log
    ) -> tuple[str | None, str | None, str]:
        """Load a Lead row and return (email, name, language)."""
        result = await context.db.execute(
            select(Lead).where(Lead.id == lead_id)
        )
        lead = result.scalar_one_or_none()

        if not lead or lead.status == "anonymised" or not lead.email:
            return None, None, "en"

        language = _detect_language_from_email(lead.email)
        return lead.email, lead.name or lead.email, language


def _detect_language_from_email(email: str) -> str:
    if email.endswith(".de") or email.endswith(".at") or email.endswith(".ch"):
        return "de"
    return "en"
