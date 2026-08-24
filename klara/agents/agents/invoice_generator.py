"""
app/agents/invoice_generator.py
────────────────────────────────
P3 agent — generates a professional PDF invoice and queues it for approval
before sending to the client.

Triggered by:
  POST /api/v1/admin/generated-invoices/generate

Flow:
  1. Allocate next sequential invoice number (INV-YYYY-NNNN) — atomic,
     uses MAX(invoice_number) within the year + 1
  2. Calculate VAT (Kleinunternehmer: 0% by default; §19 UStG note included)
  3. Generate PDF using reportlab → save to /root/loki-agents/invoices/
  4. Persist GeneratedInvoice row (status=draft)
  5. Queue P3 approval with action_name="invoice_generator.send_to_client"
  6. On approval: execute_approved_action emails the PDF as an attachment
     via Resend transactional sender

Input dict keys:
  lead_id            — str UUID (optional)
  client_name        — str (required)
  client_email       — str (required)
  client_address     — str (optional)
  client_company     — str (optional)
  service_description — str (required)
  amount_net         — float or Decimal (required, EUR net)
  vat_rate           — float (optional, default 0.0 — Kleinunternehmer)
  due_days           — int (optional, default 14)
  notes              — str (optional)

German invoice compliance (§14 UStG):
  - Sequential unique invoice number
  - Supplier full name, address, tax ID
  - Client name + address
  - Service description
  - Net amount, VAT rate + amount, gross amount
  - Issue date + payment due date
  - §19 UStG note when vat_rate == 0

Permission: P3 — client-facing financial document, requires Anthony approval.
"""
from __future__ import annotations

import io
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import structlog
from sqlalchemy import func, select, text

from app.agents.base import BaseAgent, AgentContext, AgentResult, PermissionLevel
from app.models.generated_invoice import GeneratedInvoice, GeneratedInvoiceStatus

logger = structlog.get_logger(__name__)

# ── Invoice storage directory ─────────────────────────────────────────────────
INVOICE_DIR = "/root/loki-agents/invoices"

# ── Supplier details (Anthony Stewart / Klaravex) ───────────────────
SUPPLIER_NAME    = "Anthony Stewart"
SUPPLIER_COMPANY = "Klaravex"
SUPPLIER_ADDRESS = "Berlin, Germany"
SUPPLIER_EMAIL   = "hello@klaravex.de"
SUPPLIER_WEB     = "klaravex.de"
# Bank details — shown on invoice for SEPA transfer
BANK_NAME   = "Your Bank"          # Update: op://Claude/Klara AI Social Media/bank_name
IBAN        = "DE00 0000 0000 0000 0000 00"  # Update: op://Claude/Klara AI Social Media/iban
BIC         = "XXXXXXXX"                      # Update: op://Claude/Klara AI Social Media/bic
# Tax registration (Kleinunternehmer — no Umsatzsteuer-ID for §19 UStG)
TAX_NOTE    = "Gemäß §19 UStG wird keine Umsatzsteuer berechnet."
TAX_NOTE_EN = "VAT not charged pursuant to §19 UStG (German Small Business Regulation)."


# ──────────────────────────────────────────────────────────────────────────────
# Sequential invoice number
# ──────────────────────────────────────────────────────────────────────────────

async def _next_invoice_number(db, year: int) -> str:
    """
    Allocate the next sequential invoice number for `year`.

    Format: INV-YYYY-NNNN (4 digits, zero-padded)
    Uses MAX over existing numbers matching the year prefix — safe for
    concurrent writes because the INSERT unique constraint on invoice_number
    will catch any race condition (retry at caller level if needed).
    """
    prefix = f"INV-{year}-"
    result = await db.execute(
        select(func.max(GeneratedInvoice.invoice_number)).where(
            GeneratedInvoice.invoice_number.like(f"{prefix}%")
        )
    )
    current_max: str | None = result.scalar_one_or_none()

    if current_max:
        # Extract numeric suffix and increment
        match = re.search(r"-(\d+)$", current_max)
        next_seq = int(match.group(1)) + 1 if match else 1
    else:
        next_seq = 1

    return f"{prefix}{next_seq:04d}"


# ──────────────────────────────────────────────────────────────────────────────
# PDF generation
# ──────────────────────────────────────────────────────────────────────────────

def _generate_pdf(invoice: GeneratedInvoice) -> bytes:
    """
    Generate a professional A4 PDF invoice using reportlab.

    Returns raw PDF bytes (caller writes to disk).
    Raises ImportError if reportlab is not installed.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()

    # ── Custom styles ─────────────────────────────────────────────────────────
    h1 = ParagraphStyle(
        "InvoiceH1",
        parent=styles["Heading1"],
        fontSize=22,
        textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=4,
    )
    h2 = ParagraphStyle(
        "InvoiceH2",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=2,
        spaceBefore=8,
    )
    normal = ParagraphStyle(
        "InvoiceNormal",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
    )
    small = ParagraphStyle(
        "InvoiceSmall",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#666666"),
        leading=11,
    )
    label = ParagraphStyle(
        "InvoiceLabel",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#888888"),
    )

    # ── Colour palette ────────────────────────────────────────────────────────
    BRAND_BLUE  = colors.HexColor("#1a1a2e")
    BRAND_LIGHT = colors.HexColor("#f0f4ff")
    GREY_LINE   = colors.HexColor("#e0e0e0")

    elements = []

    # ── Header: supplier left, invoice title right ────────────────────────────
    header_data = [
        [
            Paragraph(f"<b>{SUPPLIER_COMPANY}</b>", h1),
            Paragraph(f"<b>INVOICE</b>", h1),
        ],
        [
            Paragraph(
                f"{SUPPLIER_NAME}<br/>{SUPPLIER_ADDRESS}<br/>"
                f"{SUPPLIER_EMAIL}<br/>{SUPPLIER_WEB}",
                normal,
            ),
            Paragraph(
                f"<b>Invoice No:</b> {invoice.invoice_number}<br/>"
                f"<b>Issue Date:</b> {invoice.issued_date.strftime('%d %B %Y')}<br/>"
                f"<b>Due Date:</b>   {invoice.due_date.strftime('%d %B %Y')}",
                normal,
            ),
        ],
    ]
    header_table = Table(header_data, colWidths=["55%", "45%"])
    header_table.setStyle(TableStyle([
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("ALIGN",      (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(header_table)
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND_BLUE, spaceAfter=12))

    # ── Bill To ───────────────────────────────────────────────────────────────
    elements.append(Paragraph("BILL TO", label))
    client_lines = []
    if invoice.client_company:
        client_lines.append(f"<b>{invoice.client_company}</b>")
    client_lines.append(invoice.client_name)
    if invoice.client_address:
        client_lines.append(invoice.client_address.replace("\n", "<br/>"))
    client_lines.append(invoice.client_email)
    elements.append(Paragraph("<br/>".join(client_lines), normal))
    elements.append(Spacer(1, 10 * mm))

    # ── Services table ────────────────────────────────────────────────────────
    elements.append(Paragraph("SERVICES", label))
    elements.append(Spacer(1, 2 * mm))

    currency_sym = "€" if invoice.currency == "EUR" else invoice.currency

    line_data = [
        ["Description", "Amount"],
        [
            Paragraph(invoice.service_description, normal),
            Paragraph(
                f"{currency_sym}{invoice.amount_net:,.2f}",
                ParagraphStyle("Right", parent=normal, alignment=2),
            ),
        ],
    ]
    line_table = Table(line_data, colWidths=["75%", "25%"])
    line_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), BRAND_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, BRAND_LIGHT]),
        ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.5, GREY_LINE),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 6 * mm))

    # ── Totals ────────────────────────────────────────────────────────────────
    vat_label = f"VAT ({float(invoice.vat_rate):.0f}%)" if invoice.vat_rate else "VAT (0% — §19 UStG)"
    totals_data = [
        ["Subtotal (net)",  f"{currency_sym}{invoice.amount_net:,.2f}"],
        [vat_label,         f"{currency_sym}{invoice.vat_amount:,.2f}"],
        ["TOTAL DUE",       f"{currency_sym}{invoice.amount_gross:,.2f}"],
    ]
    totals_table = Table(totals_data, colWidths=["75%", "25%"])
    totals_table.setStyle(TableStyle([
        ("ALIGN",      (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME",   (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 2), (-1, 2), 11),
        ("BACKGROUND", (0, 2), (-1, 2), BRAND_LIGHT),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("LINEABOVE",  (0, 2), (-1, 2), 1, BRAND_BLUE),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 10 * mm))

    # ── Payment details ───────────────────────────────────────────────────────
    elements.append(HRFlowable(width="100%", thickness=0.5, color=GREY_LINE, spaceAfter=6))
    elements.append(Paragraph("PAYMENT DETAILS", label))
    elements.append(Paragraph(
        f"Bank: {BANK_NAME}<br/>IBAN: {IBAN}<br/>BIC: {BIC}<br/>"
        f"Reference: {invoice.invoice_number}",
        normal,
    ))
    elements.append(Spacer(1, 6 * mm))

    # ── VAT note (§19 UStG) ───────────────────────────────────────────────────
    if not invoice.vat_rate or invoice.vat_rate == 0:
        elements.append(Paragraph(f"{TAX_NOTE}<br/>{TAX_NOTE_EN}", small))
        elements.append(Spacer(1, 4 * mm))

    # ── Notes ────────────────────────────────────────────────────────────────
    if invoice.notes:
        elements.append(HRFlowable(width="100%", thickness=0.5, color=GREY_LINE, spaceAfter=4))
        elements.append(Paragraph("NOTES", label))
        elements.append(Paragraph(invoice.notes, small))

    # ── Footer ────────────────────────────────────────────────────────────────
    elements.append(Spacer(1, 8 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=GREY_LINE, spaceAfter=4))
    elements.append(Paragraph(
        f"Thank you for your business. | {SUPPLIER_COMPANY} · {SUPPLIER_WEB}",
        small,
    ))

    doc.build(elements)
    return buffer.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────────────────────────────────────

class InvoiceGeneratorAgent(BaseAgent):
    name = "invoice_generator"
    description = (
        "Generates a professional PDF invoice for a client service engagement. "
        "Allocates a sequential invoice number, builds a German-compliant PDF, "
        "and queues the send action for P3 approval."
    )
    permission_level = PermissionLevel.P3

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        # ── Validate required fields ──────────────────────────────────────────
        required = ("client_name", "client_email", "service_description", "amount_net")
        missing = [f for f in required if not input_data.get(f)]
        if missing:
            return AgentResult.fail(f"Missing required fields: {', '.join(missing)}")

        # ── Parse inputs ──────────────────────────────────────────────────────
        today      = date.today()
        due_days   = int(input_data.get("due_days", 14))
        due_date   = today + timedelta(days=due_days)
        vat_rate   = Decimal(str(input_data.get("vat_rate", "0.00")))
        amount_net = Decimal(str(input_data["amount_net"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        vat_amount = (amount_net * vat_rate / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        amount_gross = amount_net + vat_amount

        # ── Allocate invoice number ───────────────────────────────────────────
        try:
            invoice_number = await _next_invoice_number(context.db, today.year)
        except Exception as exc:
            log.error("invoice_generator.number_alloc_failed", error=str(exc))
            return AgentResult.fail(f"Failed to allocate invoice number: {exc}")

        log.info("invoice_generator.number_allocated", invoice_number=invoice_number)

        # ── Build invoice record (draft) ──────────────────────────────────────
        invoice = GeneratedInvoice(
            lead_id             = input_data.get("lead_id") or context.lead_id,
            invoice_number      = invoice_number,
            client_name         = input_data["client_name"].strip(),
            client_email        = input_data["client_email"].strip().lower(),
            client_address      = input_data.get("client_address"),
            client_company      = input_data.get("client_company"),
            service_description = input_data["service_description"].strip(),
            amount_net          = amount_net,
            vat_rate            = vat_rate,
            vat_amount          = vat_amount,
            amount_gross        = amount_gross,
            currency            = input_data.get("currency", "EUR").upper(),
            issued_date         = today,
            due_date            = due_date,
            status              = GeneratedInvoiceStatus.draft,
            notes               = input_data.get("notes"),
        )
        context.db.add(invoice)
        await context.db.flush()   # get id before PDF generation

        # ── Generate PDF ──────────────────────────────────────────────────────
        try:
            pdf_bytes = _generate_pdf(invoice)
        except ImportError:
            log.error("invoice_generator.reportlab_missing")
            return AgentResult.fail(
                "reportlab is not installed. Run: pip install reportlab"
            )
        except Exception as exc:
            log.error("invoice_generator.pdf_failed", error=str(exc))
            return AgentResult.fail(f"PDF generation failed: {exc}")

        # ── Write PDF to disk ─────────────────────────────────────────────────
        os.makedirs(INVOICE_DIR, exist_ok=True)
        pdf_filename = f"{invoice_number}.pdf"
        pdf_path     = os.path.join(INVOICE_DIR, pdf_filename)
        try:
            with open(pdf_path, "wb") as fh:
                fh.write(pdf_bytes)
        except OSError as exc:
            log.error("invoice_generator.pdf_write_failed", path=pdf_path, error=str(exc))
            return AgentResult.fail(f"Could not write PDF to {pdf_path}: {exc}")

        invoice.pdf_path = pdf_path
        await context.db.flush()
        log.info("invoice_generator.pdf_written", path=pdf_path, size=len(pdf_bytes))

        # ── Queue P3 approval ─────────────────────────────────────────────────
        from app.agents.registry import registry
        approval_manager = registry.get("approval_manager")

        approval_payload = {
            "invoice_id":          invoice.id,
            "invoice_number":      invoice_number,
            "client_name":         invoice.client_name,
            "client_email":        invoice.client_email,
            "client_company":      invoice.client_company or "",
            "service_description": invoice.service_description,
            "amount_net":          float(amount_net),
            "vat_rate":            float(vat_rate),
            "vat_amount":          float(vat_amount),
            "amount_gross":        float(amount_gross),
            "currency":            invoice.currency,
            "issued_date":         str(today),
            "due_date":            str(due_date),
            "pdf_path":            pdf_path,
            "lead_id":             invoice.lead_id or "",
            "notes":               invoice.notes or "",
        }

        approval_result = await approval_manager(
            context,
            {
                "action_name":  "invoice_generator.send_to_client",
                "risk_level":   "P3",
                "payload":      approval_payload,
                "justification": (
                    f"Invoice {invoice_number} for {invoice.client_name} "
                    f"({invoice.client_email}) — "
                    f"€{amount_gross:,.2f} gross, due {due_date}. "
                    f"PDF ready at {pdf_path}."
                ),
                "requested_by": "invoice_generator",
            },
        )

        if not approval_result.success:
            log.error(
                "invoice_generator.approval_queue_failed",
                error=approval_result.error,
                invoice_number=invoice_number,
            )
            return AgentResult.fail(
                f"Invoice generated (ID: {invoice.id}) but approval queueing failed: "
                f"{approval_result.error}"
            )

        approval_id = approval_result.approval_id
        invoice.approval_id = approval_id
        await context.db.flush()

        log.info(
            "invoice_generator.queued_for_approval",
            invoice_number=invoice_number,
            approval_id=approval_id,
            client_email=invoice.client_email,
            amount_gross=float(amount_gross),
        )

        return AgentResult.needs_approval(
            approval_id=approval_id,
            action="invoice_generator.send_to_client",
        )
