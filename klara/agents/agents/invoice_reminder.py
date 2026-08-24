"""
app/agents/invoice_reminder.py
──────────────────────────────────
P3 agent — sends a polite payment reminder to clients with overdue invoices.

Triggered by: Celery beat daily sweep task.
Also callable directly via POST /api/v1/agents/run with
  agent="invoice_reminder"
  payload: {
    "lead_id": "<uuid>",       (optional — targets single lead)
    "invoice_ref": "INV-2024-042",
    "amount_eur": 3500.00,
    "due_date": "2024-11-15",  (ISO date)
    "days_overdue": 7,
  }

Daily sweep (requires loki_invoices table — migration 0025):
  Finds all invoices with status IN ('sent', 'unpaid') where:
    - due_date < today                  (actually overdue)
    - reminder_sent_at IS NULL          (no reminder queued yet)
                   OR
    - reminder_sent_at <= now - 14d     (last reminder >= 14 days ago, max 3)
    - reminder_count < 3                (cap at 3 reminders per invoice)

Explicit payload mode:
  Always works regardless of invoice DB state. Useful for one-off reminders
  on invoices not yet in the DB (DATEV-issued, manual, etc.).

Flow:
  1. Accept payload (explicit) OR sweep loki_invoices (daily)
  2. Load lead for client name/email/language
  3. Render bilingual HTML email
  4. Queue for P3 approval (financial communication)

Permission: P3 — financial reminder to client, requires Anthony approval.
  Never P2 — even polite financial emails can create disputes.
"""
from __future__ import annotations

import textwrap
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import and_, or_, select

from klara.rarv.runtime import BaseAgent, AgentContext, AgentResult, PermissionLevel
from klara.rarv.lead import Lead
from klara.rarv.invoice import Invoice, InvoiceStatus

logger = structlog.get_logger(__name__)

_REMINDER_TEMPLATE_EN = textwrap.dedent("""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;
             padding:20px;color:#222;">

<p>Dear {name},</p>

<p>I hope the project is going well. I'm writing to follow up on invoice
<strong>{invoice_ref}</strong> for <strong>€{amount:,.2f}</strong>, which was
due on <strong>{due_date}</strong> ({days_overdue} days ago).</p>

<table style="border-collapse:collapse;width:100%;margin:16px 0;
              border:1px solid #e0e0e0;">
  <tr style="background:#fff3e0;">
    <td style="padding:8px 12px;font-weight:bold;width:40%;">Invoice</td>
    <td style="padding:8px 12px;">{invoice_ref}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;font-weight:bold;">Amount</td>
    <td style="padding:8px 12px;font-size:16px;font-weight:bold;">€{amount:,.2f}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:8px 12px;font-weight:bold;">Due Date</td>
    <td style="padding:8px 12px;">{due_date}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;font-weight:bold;">Days Overdue</td>
    <td style="padding:8px 12px;color:#c62828;font-weight:bold;">{days_overdue}</td>
  </tr>
</table>

<p>If payment has already been sent, please disregard this message. If you have
any questions about the invoice or would like to discuss payment timing, please
reply directly to this email.</p>

<p>Payment details are included on the original invoice. Standard transfer to
my German bank account (IBAN / SEPA) is preferred.</p>

<p>Thank you for your prompt attention.</p>

<p>Best regards,<br>
<strong>Anthony Stewart</strong><br>
Klaravex<br>
<a href="https://klaravex.de">klaravex.de</a>
</p>

<hr style="border:none;border-top:1px solid #eee;">
<p style="font-size:11px;color:#999;">
  Invoice reminder · Klaravex
</p>
</body>
</html>
""")

_REMINDER_TEMPLATE_DE = textwrap.dedent("""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;
             padding:20px;color:#222;">

<p>Guten Tag {name},</p>

<p>ich hoffe, das Projekt verläuft gut. Ich möchte Sie höflich an Rechnung
<strong>{invoice_ref}</strong> über <strong>€{amount:,.2f}</strong>
erinnern, die am <strong>{due_date}</strong> fällig war
({days_overdue} Tage überfällig).</p>

<table style="border-collapse:collapse;width:100%;margin:16px 0;
              border:1px solid #e0e0e0;">
  <tr style="background:#fff3e0;">
    <td style="padding:8px 12px;font-weight:bold;width:40%;">Rechnung</td>
    <td style="padding:8px 12px;">{invoice_ref}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;font-weight:bold;">Betrag</td>
    <td style="padding:8px 12px;font-size:16px;font-weight:bold;">€{amount:,.2f}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:8px 12px;font-weight:bold;">Fälligkeitsdatum</td>
    <td style="padding:8px 12px;">{due_date}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;font-weight:bold;">Überfällig seit</td>
    <td style="padding:8px 12px;color:#c62828;font-weight:bold;">{days_overdue} Tagen</td>
  </tr>
</table>

<p>Falls die Zahlung bereits erfolgt ist, betrachten Sie diese Nachricht als
gegenstandslos. Bei Fragen zur Rechnung oder zum Zahlungstermin antworten Sie
bitte direkt auf diese E-Mail.</p>

<p>Die Zahlungsdetails finden Sie auf der ursprünglichen Rechnung. SEPA-Überweisung
auf mein deutsches Konto wird bevorzugt.</p>

<p>Vielen Dank für Ihre zeitnahe Rückmeldung.</p>

<p>Mit freundlichen Grüßen,<br>
<strong>Anthony Stewart</strong><br>
Klaravex<br>
<a href="https://klaravex.de">klaravex.de</a>
</p>

<hr style="border:none;border-top:1px solid #eee;">
<p style="font-size:11px;color:#999;">
  Zahlungserinnerung · Klaravex
</p>
</body>
</html>
""")


class InvoiceReminderAgent(BaseAgent):
    name = "invoice_reminder"
    permission_level = PermissionLevel.P2
    description = (
        "Sends a polite payment reminder to a client for an overdue invoice. "
        "Requires explicit payload: lead_id, invoice_ref, amount_eur, due_date, "
        "days_overdue. Renders bilingual HTML email and queues for P3 approval. "
        "P3 — financial communication, always requires Anthony review."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        lead_id = context.lead_id or payload.get("lead_id")
        invoice_ref = payload.get("invoice_ref", "")

        # ── Mode selection ──────────────────────────────────────────────────
        # Explicit payload mode: caller supplies invoice details directly.
        # Daily sweep mode: no explicit invoice_ref → query loki_invoices table.

        if lead_id or invoice_ref:
            # Explicit single-invoice mode (backward compatible)
            return await self._run_explicit(context, payload, log)
        else:
            # Daily sweep mode
            return await self._run_sweep(context, log)

    # ── Explicit mode ───────────────────────────────────────────────────────

    async def _run_explicit(
        self, context: AgentContext, payload: dict, log
    ) -> AgentResult:
        lead_id = context.lead_id or payload.get("lead_id")
        invoice_ref = payload.get("invoice_ref", "")
        amount_eur = payload.get("amount_eur")
        due_date_str = payload.get("due_date", "")
        days_overdue = payload.get("days_overdue", 0)

        if not lead_id:
            return AgentResult.fail("invoice_reminder: 'lead_id' is required.")
        if not invoice_ref:
            return AgentResult.fail("invoice_reminder: 'invoice_ref' is required.")
        if amount_eur is None:
            return AgentResult.fail("invoice_reminder: 'amount_eur' is required.")
        if not due_date_str:
            return AgentResult.fail("invoice_reminder: 'due_date' is required.")

        lead = (await context.db.execute(
            select(Lead).where(Lead.id == lead_id)
        )).scalar_one_or_none()

        if not lead:
            return AgentResult.fail(f"Lead {lead_id} not found.")

        try:
            amount_float = float(amount_eur)
        except (ValueError, TypeError):
            return AgentResult.fail(f"Invalid amount_eur: {amount_eur}")

        return await self._queue_reminder(
            context, log, lead,
            invoice_ref=invoice_ref,
            amount_float=amount_float,
            due_date_str=due_date_str,
            days_overdue=int(days_overdue),
            invoice_obj=None,
        )

    # ── Daily sweep mode ────────────────────────────────────────────────────

    async def _run_sweep(self, context: AgentContext, log) -> AgentResult:
        """
        Find all overdue, un-reminded invoices in loki_invoices and queue
        a P3 reminder for each one.

        Criteria:
          status IN ('sent', 'unpaid')
          due_date < today
          (reminder_sent_at IS NULL OR reminder_sent_at <= now - 14 days)
          reminder_count < 3
        """
        today = date.today()
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)

        overdue_q = (
            select(Invoice)
            .where(
                and_(
                    Invoice.status.in_([InvoiceStatus.sent, InvoiceStatus.unpaid]),
                    Invoice.due_date < today,
                    Invoice.reminder_count < 3,
                    or_(
                        Invoice.reminder_sent_at.is_(None),
                        Invoice.reminder_sent_at <= cutoff,
                    ),
                )
            )
            .order_by(Invoice.due_date.asc())
            .limit(20)   # cap per sweep run
        )
        result = await context.db.execute(overdue_q)
        invoices = result.scalars().all()

        if not invoices:
            log.info("invoice_reminder.sweep.nothing_overdue")
            return AgentResult.ok({"status": "ok", "queued": 0})

        queued = 0
        errors = []

        for inv in invoices:
            lead = (await context.db.execute(
                select(Lead).where(Lead.id == inv.lead_id)
            )).scalar_one_or_none()

            if not lead or lead.status == "anonymised" or not lead.email:
                log.warning("invoice_reminder.sweep.skipped_lead",
                            invoice_id=inv.id,
                            reason="missing/anonymised/no-email")
                continue

            days_overdue = (today - inv.due_date).days
            amount_float = float(inv.amount_eur)
            due_date_str = inv.due_date.isoformat()

            r = await self._queue_reminder(
                context, log, lead,
                invoice_ref=inv.invoice_ref,
                amount_float=amount_float,
                due_date_str=due_date_str,
                days_overdue=days_overdue,
                invoice_obj=inv,
            )
            if r.success:
                queued += 1
                # Stamp reminder tracking on the invoice row
                inv.reminder_sent_at = datetime.now(timezone.utc)
                inv.reminder_count = (inv.reminder_count or 0) + 1
                if inv.status == InvoiceStatus.sent:
                    inv.status = InvoiceStatus.unpaid
            else:
                errors.append(f"{inv.invoice_ref}: {r.error}")

        await context.db.flush()

        log.info("invoice_reminder.sweep.done",
                 queued=queued, errors=len(errors))

        return AgentResult.ok({
            "status": "ok",
            "queued": queued,
            "errors": errors if errors else None,
        })

    # ── Shared queue helper ─────────────────────────────────────────────────

    async def _queue_reminder(
        self,
        context: AgentContext,
        log,
        lead: Lead,
        *,
        invoice_ref: str,
        amount_float: float,
        due_date_str: str,
        days_overdue: int,
        invoice_obj,          # Invoice ORM row or None (explicit mode)
    ) -> AgentResult:
        if lead.status == "anonymised":
            return AgentResult.fail("Cannot send invoice reminder to anonymised lead.")
        if not lead.email:
            return AgentResult.fail(f"Lead {lead.id} has no email address.")

        language = _detect_language(lead)
        first_name = (lead.name or "").split()[0] if lead.name else (
            "there" if language == "en" else "Sie"
        )

        if language == "de":
            html = _REMINDER_TEMPLATE_DE.format(
                name=first_name,
                invoice_ref=invoice_ref,
                amount=amount_float,
                due_date=due_date_str,
                days_overdue=days_overdue,
            )
            subject = f"Zahlungserinnerung: {invoice_ref} — €{amount_float:,.2f}"
        else:
            html = _REMINDER_TEMPLATE_EN.format(
                name=first_name,
                invoice_ref=invoice_ref,
                amount=amount_float,
                due_date=due_date_str,
                days_overdue=days_overdue,
            )
            subject = f"Payment reminder: {invoice_ref} — €{amount_float:,.2f}"

        log.info("invoice_reminder.queueing",
                 lead_id=lead.id,
                 invoice_ref=invoice_ref,
                 amount=amount_float,
                 days_overdue=days_overdue,
                 language=language)

        try:
            from app.agents.registry import registry
            approval_agent = registry.get("approval_manager")
            await approval_agent(context, {
                "action": "create",
                "action_name": "send_invoice_reminder",
                "risk_level": "P3",
                "payload": {
                    "lead_id": lead.id,
                    "to_email": lead.email,
                    "to_name": lead.name or lead.email,
                    "subject": subject,
                    "body_html": html,
                    "body_text": (
                        f"Payment reminder for {invoice_ref}\n"
                        f"Amount: €{amount_float:,.2f}\n"
                        f"Due date: {due_date_str}\n"
                        f"Days overdue: {days_overdue}\n\n"
                        "Please arrange payment or contact us to discuss."
                    ),
                    "invoice_ref": invoice_ref,
                    "amount_eur": amount_float,
                    "invoice_id": invoice_obj.id if invoice_obj else None,
                    "language": language,
                },
                "justification": (
                    f"Invoice {invoice_ref} for {lead.name or lead.email} "
                    f"({lead.company or 'unknown'}). "
                    f"Amount: €{amount_float:,.2f}. "
                    f"{days_overdue} days overdue since {due_date_str}."
                ),
                "requested_by": self.name,
            })
        except Exception as exc:
            log.error("invoice_reminder.queue_error",
                      lead_id=lead.id, error=str(exc))
            return AgentResult.fail(str(exc))

        log.info("invoice_reminder.queued",
                 lead_id=lead.id,
                 invoice_ref=invoice_ref)

        return AgentResult.ok({
            "status": "queued_for_p3_approval",
            "lead_id": lead.id,
            "invoice_ref": invoice_ref,
            "amount_eur": amount_float,
            "to_email": lead.email,
            "language": language,
        })


def _detect_language(lead: Lead) -> str:
    email = lead.email or ""
    if email.endswith(".de") or email.endswith(".at") or email.endswith(".ch"):
        return "de"
    return "en"
