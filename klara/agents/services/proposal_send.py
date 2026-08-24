"""
app/services/proposal_send.py
──────────────────────────────
phase5-002 — client-facing proposal send pipeline.

The proposal_drafting.draft approval dispatch already persists Proposals
and emails them to admin for review. This service handles the SECOND
approval gate: send-to-client. Triggered by approval action 'proposal.send'.

What it does:
  1. Validates the proposal isn't already sent (idempotent).
  2. Pre-send suppression check using app/services/suppression.is_suppressed.
  3. Renders Markdown → HTML, augments with tracking pixel + click-wrap.
  4. Sends via Resend.
  5. Stamps Proposal.sent_to_client_at + flips status to sent_to_client.

Tracking-token routing: proposals get their own /api/v1/track/proposal/...
endpoints to keep them cleanly separated from prospect tracking.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape as _esc
from typing import Optional
from urllib.parse import quote

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import Settings
from klara.rarv.lead import Lead
from klara.rarv.proposal import Proposal, ProposalStatus
from klara.rarv.runtime.email_sender import send_resend_email
from klara.rarv.runtime.suppression import is_suppressed

logger = structlog.get_logger(__name__)


def proposal_pixel_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/track/proposal/open/{token}"


def proposal_wrap_link(base_url: str, token: str, target_url: str) -> str:
    return (
        f"{base_url.rstrip('/')}/api/v1/track/proposal/click/{token}"
        f"?u={quote(target_url, safe='')}"
    )


_DO_NOT_WRAP = (
    "/api/v1/track/",
    "/unsubscribe",
    "mailto:",
    "tel:",
)


def augment_proposal_for_tracking(body_html: str, base_url: str, token: str) -> str:
    """Inject open pixel + wrap outbound links for a proposal email."""
    if not body_html or not token:
        return body_html or ""

    base = base_url.rstrip("/")

    def _rewrite_href(match: "re.Match[str]") -> str:
        target = match.group(2)
        if any(skip in target for skip in _DO_NOT_WRAP):
            return match.group(0)
        return f"href={match.group(1)}{proposal_wrap_link(base, token, target)}{match.group(1)}"

    out = re.sub(
        r'href=(["\'])(https?://[^"\']+)\1',
        _rewrite_href,
        body_html,
    )
    pixel = (
        f'<img src="{_esc(proposal_pixel_url(base, token))}" '
        f'width="1" height="1" alt="" '
        f'style="display:block;width:1px;height:1px;border:0;" />'
    )
    if "</body>" in out:
        out = out.replace("</body>", pixel + "</body>", 1)
    else:
        out = out + pixel
    return out


def markdown_to_html(markdown: str) -> str:
    """Minimal MD → HTML for proposal emails.

    Heavyweight markdown libraries pull in too many deps for an email
    body. We support: # headings, **bold**, plain paragraphs separated
    by blank lines, and bullet lists. Anything fancier renders as text.
    """
    if not markdown:
        return ""
    lines = markdown.split("\n")
    out: list[str] = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if stripped.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{_esc(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{_esc(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{_esc(stripped[4:])}</h3>")
        elif stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            content = stripped[2:]
            out.append(f"<li>{_inline(content)}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{_inline(stripped)}</p>")
    if in_list:
        out.append("</ul>")
    return "".join(out)


def _inline(text: str) -> str:
    esc = _esc(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)


async def send_proposal_to_client(
    db: AsyncSession,
    settings: Settings,
    proposal_id: str,
) -> dict:
    """
    Send a proposal to the client. Returns a dict suitable for the approval
    dispatch payload (dispatched, sent, suppressed, etc.).

    Idempotent — refuses to resend a proposal already in sent_to_client.
    """
    pr = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    proposal = pr.scalar_one_or_none()
    if proposal is None:
        return {"dispatched": False, "error": "proposal not found"}

    if proposal.status == ProposalStatus.sent_to_client.value:
        logger.info(
            "proposal_send.already_sent",
            proposal_id=proposal_id,
        )
        return {"dispatched": True, "sent": True, "idempotent_skip": True}

    lead_q = await db.execute(select(Lead).where(Lead.id == proposal.lead_id))
    lead = lead_q.scalar_one_or_none()
    if lead is None or not lead.email:
        return {"dispatched": False, "error": "lead missing email"}

    if await is_suppressed(db, lead.email):
        logger.info(
            "proposal_send.blocked_by_suppression",
            proposal_id=proposal_id,
            to=lead.email,
        )
        return {"dispatched": True, "sent": False, "suppressed": True}

    base = getattr(settings, "app_base_url", "https://api.klaravex.de")
    body_html = markdown_to_html(proposal.proposal_markdown)
    body_html = augment_proposal_for_tracking(body_html, base, proposal.tracking_token)

    company = proposal.company or lead.company or "your team"
    subject = f"Proposal: {company} — Klaravex"

    sent = await send_resend_email(
        settings,
        to_email=lead.email,
        to_name=lead.name or "",
        subject=subject,
        body_html=body_html,
        body_text=proposal.proposal_markdown,
    )

    if sent:
        proposal.sent_to_client_at = datetime.now(timezone.utc)
        proposal.status = ProposalStatus.sent_to_client.value
        await db.flush()
        logger.info(
            "proposal_send.sent",
            proposal_id=proposal_id,
            to=lead.email,
        )

    return {
        "dispatched": True,
        "sent": sent,
        "to_email": lead.email,
        "proposal_id": proposal_id,
    }
