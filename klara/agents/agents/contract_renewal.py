"""
app/agents/contract_renewal.py
────────────────────────────────
ContractRenewalAgent — identifies won clients approaching their contract renewal
window and dispatches personalised renewal outreach emails.

Business model approximation
─────────────────────────────
Klara AI does not maintain an explicit contracts table. Renewal timing is inferred
from the lifecycle of a won lead:

  contract_start ≈ date of first paid invoice (loki_invoices.created_at)
  renewal_due    = contract_start + renewal_months × 30 days

A client is considered "renewal-eligible" when today falls within the window:
  [renewal_due - renewal_lookforward_days, renewal_due + renewal_lookforward_days]

Email language heuristic
─────────────────────────
  - If lead.company ends in ".de" or lead.notes contains "German" / "Deutsch"
    → draft in German
  - Otherwise → German (default for Berlin-based practice)
  The Claude prompt explicitly labels the preferred language.

Permission: P2 — sends email directly to the won client; no P3 approval gate
because renewal outreach is a client-relationship communication, not cold contact.
(If this policy changes, escalate permission_level to P3 and wrap send calls
with an ApprovalRequest instead.)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.invoice import Invoice, InvoiceStatus
from klara.rarv.lead import Lead, LeadStatus
from klara.rarv.runtime.email_sender import send_transactional_email

logger = structlog.get_logger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_RENEWAL_MONTHS = 12
DEFAULT_LOOKFORWARD_DAYS = 30

# ── Prompts ───────────────────────────────────────────────────────────────────
RENEWAL_PROMPT_DE = """\
Du bist ein Senior IT-Berater bei Klaravex. Du wendest dich an einen
bestehenden Kunden, dessen Servicevertrag bald ausläuft, um die Zusammenarbeit
fortzuführen.

Schreibe eine persönliche, professionelle Erneuerungs-E-Mail auf Deutsch.

Regeln:
- Ton: warm, wertschätzend, professionell — kein Verkaufsdruck
- Länge: ~180–220 Wörter im Body
- Beginne mit persönlicher Anrede (Name wenn vorhanden, sonst "Sehr geehrte Damen und Herren,")
- Hebe den Wert der bisherigen Zusammenarbeit hervor
- Erwähne den bevorstehenden Verlängerungszeitpunkt (konkret: {renewal_due})
- Schlage ein kurzes Gespräch vor, um Bedarf und nächste Schritte abzustimmen
- Signatur: "Freundliche Grüße,\nIhr Klaravex Team"
- Erwähne KEINE konkreten Preise

Kundendaten:
{client_context}

Liefere das Ergebnis als valides JSON-Objekt:
{{
  "subject": "<Betreffzeile auf Deutsch>",
  "body_text": "<Plain-Text-Body, Zeilenumbrüche mit \\n>",
  "body_html": "<HTML-Body, einfaches HTML ohne <html>/<head>/<body>-Tags>"
}}
"""

RENEWAL_PROMPT_EN = """\
You are a senior IT consultant at Klaravex reaching out to an existing
client whose service agreement is approaching its renewal date.

Write a personalised, professional renewal email in English.

Rules:
- Tone: warm, appreciative, professional — no sales pressure
- Length: ~180–220 words in the body
- Begin with a personal greeting (use name if available, otherwise "Dear Sir/Madam,")
- Highlight the value delivered during the engagement
- Mention the upcoming renewal date (specifically: {renewal_due})
- Propose a short call to align on needs and next steps
- Signature: "Best regards,\nYour Klaravex Team"
- Do NOT mention specific pricing

Client data:
{client_context}

Deliver the result as a valid JSON object:
{{
  "subject": "<Subject line in English>",
  "body_text": "<Plain-text body, newlines as \\n>",
  "body_html": "<HTML body, simple HTML without <html>/<head>/<body> tags>"
}}
"""


@dataclass
class RenewalCandidate:
    """Holds resolved data for a single renewal candidate."""

    lead_id: str
    name: str | None
    email: str | None
    company: str | None
    renewal_due: datetime
    first_paid_date: datetime
    notes: str | None


class ContractRenewalAgent(BaseAgent):
    """
    Identifies won clients approaching contract renewal and dispatches
    personalised renewal outreach emails.

    Input:
        renewal_months (int)         — assumed contract length, default 12
        renewal_lookforward_days (int) — window ahead to look, default 30
        dry_run (bool)               — if True return candidates without emailing
        notify_consultant (bool)     — send summary to approval_notify_email

    Output:
        candidates      — list of {lead_id, name, renewal_due, emailed, note}
        total_candidates — int
        emails_sent     — int
        dry_run         — bool
    """

    name = "contract_renewal"
    description = (
        "Identifies won clients approaching contract renewal windows and drafts "
        "personalised renewal outreach emails."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        db = context.db
        settings = context.settings

        # ── Input parsing ─────────────────────────────────────────────────────
        renewal_months: int = int(
            input_data.get("renewal_months", DEFAULT_RENEWAL_MONTHS)
        )
        lookforward_days: int = int(
            input_data.get("renewal_lookforward_days", DEFAULT_LOOKFORWARD_DAYS)
        )
        dry_run: bool = bool(input_data.get("dry_run", False))
        notify_consultant: bool = bool(input_data.get("notify_consultant", True))

        now = datetime.now(ZoneInfo("Europe/Berlin"))
        window_end = now + timedelta(days=lookforward_days)

        log.info(
            "contract_renewal.start",
            renewal_months=renewal_months,
            lookforward_days=lookforward_days,
            dry_run=dry_run,
            window_end=window_end.date().isoformat(),
        )

        # ── Step 1: Load all won leads ────────────────────────────────────────
        won_result = await db.execute(
            select(Lead).where(Lead.status == LeadStatus.won.value)
        )
        won_leads: list[Lead] = won_result.scalars().all()

        log.debug("contract_renewal.won_leads", count=len(won_leads))

        # ── Step 2: Identify renewal candidates ───────────────────────────────
        candidates: list[RenewalCandidate] = []

        for lead in won_leads:
            inv_r = await db.execute(
                select(Invoice.created_at)
                .where(
                    Invoice.lead_id == lead.id,
                    Invoice.status == InvoiceStatus.paid.value,
                )
                .order_by(Invoice.created_at.asc())
                .limit(1)
            )
            first_paid: datetime | None = inv_r.scalar_one_or_none()

            if first_paid is None:
                log.debug(
                    "contract_renewal.no_paid_invoice",
                    lead_id=lead.id,
                    name=lead.name,
                )
                continue

            # Normalise to timezone-aware if the DB returns naive datetime
            if first_paid.tzinfo is None:
                first_paid = first_paid.replace(tzinfo=ZoneInfo("Europe/Berlin"))

            renewal_due = first_paid + timedelta(days=renewal_months * 30)

            if now <= renewal_due <= window_end:
                candidates.append(
                    RenewalCandidate(
                        lead_id=lead.id,
                        name=lead.name,
                        email=lead.email,
                        company=lead.company,
                        renewal_due=renewal_due,
                        first_paid_date=first_paid,
                        notes=lead.notes,
                    )
                )
                log.info(
                    "contract_renewal.candidate_found",
                    lead_id=lead.id,
                    name=lead.name,
                    renewal_due=renewal_due.date().isoformat(),
                )

        log.info("contract_renewal.candidates_total", count=len(candidates))

        # ── Step 3: Draft and send renewal emails ─────────────────────────────
        results: list[dict] = []
        emails_sent = 0

        if dry_run:
            for c in candidates:
                results.append(
                    {
                        "lead_id": c.lead_id,
                        "name": c.name or "Unknown",
                        "company": c.company or "",
                        "renewal_due": c.renewal_due.date().isoformat(),
                        "emailed": False,
                        "note": "dry_run — no email sent",
                    }
                )
        else:
            client = AsyncAnthropic(api_key=settings.anthropic_api_key)

            for candidate in candidates:
                record: dict = {
                    "lead_id": candidate.lead_id,
                    "name": candidate.name or "Unknown",
                    "company": candidate.company or "",
                    "renewal_due": candidate.renewal_due.date().isoformat(),
                    "emailed": False,
                    "note": "",
                }

                if not candidate.email:
                    record["note"] = "no email address on lead — skipped"
                    log.warning(
                        "contract_renewal.no_email",
                        lead_id=candidate.lead_id,
                        name=candidate.name,
                    )
                    results.append(record)
                    continue

                # Determine email language
                use_german = _should_use_german(candidate)
                renewal_due_str = candidate.renewal_due.strftime("%d.%m.%Y") if use_german else candidate.renewal_due.strftime("%B %d, %Y")

                client_context = (
                    f"Name: {candidate.name or 'N/A'}\n"
                    f"Company: {candidate.company or 'N/A'}\n"
                    f"Email: {candidate.email}\n"
                    f"First engagement date: {candidate.first_paid_date.strftime('%Y-%m-%d')}\n"
                    f"Notes: {candidate.notes or 'None'}"
                )

                prompt_template = RENEWAL_PROMPT_DE if use_german else RENEWAL_PROMPT_EN
                prompt = prompt_template.format(
                    renewal_due=renewal_due_str,
                    client_context=client_context,
                )

                try:
                    response = await client.messages.create(
                        model=settings.anthropic_model,
                        max_tokens=1500,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    try:
                        from klara.rarv.runtime.llm_cost import track_response
                        await track_response(
                            context.db, agent_name=self.name,
                            model=settings.anthropic_model,
                            response=response, lead_id=getattr(context, 'lead_id', None),
                        )
                    except Exception:
                        pass
                    raw_text = response.content[0].text.strip()
                except Exception as exc:
                    log.error(
                        "contract_renewal.claude_error",
                        lead_id=candidate.lead_id,
                        error=str(exc),
                    )
                    record["note"] = f"Claude error: {exc}"
                    results.append(record)
                    continue

                import json
                import re as _re

                draft = _parse_email_json(raw_text)
                if not draft:
                    log.error(
                        "contract_renewal.parse_error",
                        lead_id=candidate.lead_id,
                        raw=raw_text[:200],
                    )
                    record["note"] = "JSON parse failure on Claude response"
                    results.append(record)
                    continue

                subject = draft.get(
                    "subject",
                    "Ihre IT-Betreuung — Vertragsverlängerung"
                    if use_german
                    else "Your IT Support Contract — Renewal",
                )
                body_text = draft.get("body_text", "")
                body_html = draft.get("body_html", "")

                sent = await send_transactional_email(
                    settings,
                    to_email=candidate.email,
                    to_name=candidate.name or "",
                    subject=subject,
                    body_html=body_html,
                    body_text=body_text,
                )

                if sent:
                    emails_sent += 1
                    record["emailed"] = True
                    record["note"] = f"sent ({'DE' if use_german else 'EN'})"
                    log.info(
                        "contract_renewal.email_sent",
                        lead_id=candidate.lead_id,
                        to=candidate.email,
                        language="de" if use_german else "en",
                    )
                else:
                    record["note"] = "email send failed"
                    log.warning(
                        "contract_renewal.email_failed",
                        lead_id=candidate.lead_id,
                        to=candidate.email,
                    )

                results.append(record)

        # ── Step 4: Notify consultant if requested ────────────────────────────
        notify_email = getattr(settings, "approval_notify_email", None)

        if notify_consultant and notify_email and candidates:
            summary_subject = (
                f"Contract Renewal Report — {len(candidates)} candidate(s) "
                f"due within {lookforward_days} days"
            )
            summary_text, summary_html = _build_summary_email(
                results=results,
                renewal_months=renewal_months,
                lookforward_days=lookforward_days,
                dry_run=dry_run,
                emails_sent=emails_sent,
            )
            notified = await send_transactional_email(
                settings,
                to_email=notify_email,
                to_name="Klaravex",
                subject=summary_subject,
                body_html=summary_html,
                body_text=summary_text,
            )
            log.info(
                "contract_renewal.consultant_notified",
                to=notify_email,
                sent=notified,
                candidates=len(candidates),
            )
        elif notify_consultant and not candidates:
            log.info(
                "contract_renewal.notify_skipped",
                reason="no renewal candidates found",
            )

        log.info(
            "contract_renewal.complete",
            total_candidates=len(candidates),
            emails_sent=emails_sent,
            dry_run=dry_run,
        )

        return AgentResult.ok(
            output={
                "candidates": results,
                "total_candidates": len(candidates),
                "emails_sent": emails_sent,
                "dry_run": dry_run,
                "renewal_months": renewal_months,
                "lookforward_days": lookforward_days,
                "window_end": window_end.date().isoformat(),
            }
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _should_use_german(candidate: RenewalCandidate) -> bool:
    """
    Determine email language for a renewal candidate.

    Heuristic:
      - Default to German (Berlin practice, primarily German market)
      - Switch to English only if there are explicit English signals in the notes
    """
    notes_lower = (candidate.notes or "").lower()
    english_signals = ("english preferred", "en only", "language: en", "english only")
    for signal in english_signals:
        if signal in notes_lower:
            return False
    return True


def _parse_email_json(text: str) -> dict | None:
    """Extract the first JSON object from a Claude response string."""
    import json
    import re

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _build_summary_email(
    results: list[dict],
    renewal_months: int,
    lookforward_days: int,
    dry_run: bool,
    emails_sent: int,
) -> tuple[str, str]:
    """Build plain-text and HTML consultant summary emails."""
    dry_label = " [DRY RUN]" if dry_run else ""

    # Plain text
    lines = [
        f"CONTRACT RENEWAL REPORT{dry_label}",
        "=" * 50,
        f"Renewal window: within {lookforward_days} days",
        f"Assumed contract length: {renewal_months} months",
        f"Total candidates: {len(results)}",
        f"Emails sent: {emails_sent}",
        "",
        "CANDIDATES",
        "-" * 40,
    ]
    for r in results:
        status = "EMAILED" if r.get("emailed") else f"SKIPPED ({r.get('note', '')})"
        lines.append(
            f"  {r.get('name', 'Unknown')} ({r.get('company', 'N/A')}) "
            f"— renewal {r.get('renewal_due', 'N/A')} — {status}"
        )
    lines += ["", "—", "Klaravex"]
    plain = "\n".join(lines)

    # HTML
    rows_html = ""
    for r in results:
        emailed = r.get("emailed", False)
        badge_colour = "#28a745" if emailed else "#dc3545"
        badge_label = "Emailed" if emailed else "Skipped"
        note = r.get("note", "")
        rows_html += (
            f"<tr>"
            f"<td style='padding:8px;border:1px solid #ddd;'>{r.get('name', 'Unknown')}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;'>{r.get('company', '')}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;'>{r.get('renewal_due', '')}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;'>"
            f"<span style='background:{badge_colour};color:#fff;padding:2px 8px;"
            f"border-radius:3px;font-size:12px;'>{badge_label}</span></td>"
            f"<td style='padding:8px;border:1px solid #ddd;font-size:12px;color:#666;'>{note}</td>"
            f"</tr>"
        )

    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:900px;color:#222;'>"
        f"<h2 style='color:#1a73e8;'>Contract Renewal Report{dry_label}</h2>"
        f"<p><strong>Renewal window:</strong> within {lookforward_days} days &nbsp;|&nbsp; "
        f"<strong>Contract length assumed:</strong> {renewal_months} months &nbsp;|&nbsp; "
        f"<strong>Candidates:</strong> {len(results)} &nbsp;|&nbsp; "
        f"<strong>Emails sent:</strong> {emails_sent}</p>"
        f"<table style='border-collapse:collapse;width:100%;'>"
        f"<thead><tr style='background:#1a73e8;color:#fff;'>"
        f"<th style='padding:10px;text-align:left;'>Name</th>"
        f"<th style='padding:10px;text-align:left;'>Company</th>"
        f"<th style='padding:10px;text-align:left;'>Renewal Due</th>"
        f"<th style='padding:10px;text-align:left;'>Status</th>"
        f"<th style='padding:10px;text-align:left;'>Note</th>"
        f"</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        f"</table>"
        f"<p style='margin-top:24px;font-size:12px;color:#999;'>"
        f"Klaravex</p>"
        f"</div>"
    )

    return plain, html
