"""
app/api/approvals.py
─────────────────────
Human-in-the-loop approval endpoints.

GET  /api/v1/approvals/          — list pending approvals (requires API key)
GET  /api/v1/approvals/{id}      — get approval detail (requires API key)
POST /api/v1/approvals/{id}/approve  — approve an action (requires API key)
POST /api/v1/approvals/{id}/reject   — reject an action (requires API key)

These endpoints are called by the admin (via dashboard or email link)
when a P3/P4/P5 action needs sign-off.

Dispatched actions (executed synchronously inside the request):
  outreach_email.send      — sends the pre-drafted German email via SMTP
  proposal_drafting.draft  — runs ProposalDraftingAgent, saves Proposal to DB,
                             emails markdown to admin/consultant
"""
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from klara.rarv.runtime import AgentContext
from app.agents.registry import registry
from klara.rarv.runtime import get_settings, Settings
from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.approval import ApprovalRequest, ApprovalStatus

logger = structlog.get_logger(__name__)

router = APIRouter()


class ReviewRequest(BaseModel):
    reviewed_by: str
    note: Optional[str] = None


@router.get("/", dependencies=[Depends(verify_api_key)])
async def list_approvals(
    status_filter: str = "pending",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List approval requests. Defaults to showing pending ones."""
    query = (
        select(ApprovalRequest)
        .where(ApprovalRequest.status == status_filter)
        .order_by(ApprovalRequest.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    approvals = result.scalars().all()
    return [
        {
            "id": a.id,
            "action_name": a.action_name,
            "risk_level": a.risk_level,
            "status": a.status,
            "requested_by_agent": a.requested_by_agent,
            "lead_id": a.lead_id,
            "justification": a.justification,
            "created_at": a.created_at.isoformat(),
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        }
        for a in approvals
    ]


@router.get("/{approval_id}", dependencies=[Depends(verify_api_key)])
async def get_approval(approval_id: str, db: AsyncSession = Depends(get_db)):
    """Get full approval detail including payload."""
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Approval not found.")
    return {
        "id": a.id, "action_name": a.action_name, "risk_level": a.risk_level,
        "payload": a.payload, "justification": a.justification,
        "status": a.status, "requested_by_agent": a.requested_by_agent,
        "lead_id": a.lead_id, "conversation_id": a.conversation_id,
        "reviewed_by": a.reviewed_by, "review_note": a.review_note,
        "created_at": a.created_at.isoformat(),
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
    }


@router.post("/{approval_id}/approve", dependencies=[Depends(verify_api_key)])
async def approve_action(
    approval_id: str,
    req: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Approve a pending action and execute it synchronously.

    Supported action_names:
      - outreach_email.send        → sends the pre-drafted German email via SMTP
      - proposal_drafting.draft    → runs ProposalDraftingAgent, saves to DB, emails consultant
      - prospecting_outreach.send  → sends cold outreach email via Resend, marks prospect sent
      - notify_consultant.warm_lead → logged only (no dispatch yet)
    """
    context = AgentContext(db=db, settings=settings)
    approval_mgr = registry.get("approval_manager")

    result = await approval_mgr(
        context,
        {
            "action": "approve",
            "approval_id": approval_id,
            "reviewed_by": req.reviewed_by,
            "note": req.note,
        },
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    # ── Fetch the approved record to dispatch the action ──────────────────────
    ar_result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    approval = ar_result.scalar_one_or_none()

    dispatch: dict = {"dispatched": False, "action": None}

    if approval:
        action_name = approval.action_name
        dispatch["action"] = action_name

        try:
            payload: dict = (
                json.loads(approval.payload)
                if isinstance(approval.payload, str)
                else (approval.payload or {})
            )
        except (json.JSONDecodeError, TypeError):
            payload = {}

        if action_name == "outreach_email.send":
            from klara.rarv.runtime.email_sender import send_transactional_email

            sent = await send_transactional_email(
                settings,
                to_email=payload.get("to_email", ""),
                to_name=payload.get("to_name", ""),
                subject=payload.get("subject", "Ihre Anfrage – Klaravex"),
                body_html=payload.get("body_html", ""),
                body_text=payload.get("body_text", ""),
            )
            dispatch.update({"dispatched": True, "sent": sent})
            logger.info(
                "approvals.outreach_sent",
                approval_id=approval_id,
                to=payload.get("to_email"),
                sent=sent,
            )

        elif action_name == "proposal_drafting.draft":
            from datetime import datetime, timezone

            from klara.rarv.runtime.email_sender import send_transactional_email
            from klara.rarv.proposal import Proposal, ProposalStatus

            lead_id = payload.get("lead_id") or approval.lead_id
            proposal_context = AgentContext(
                db=db,
                settings=settings,
                lead_id=lead_id,
                conversation_id=approval.conversation_id,
            )
            proposal_agent = registry.get("proposal_drafting")
            proposal_result = await proposal_agent(proposal_context, payload)

            if proposal_result.success:
                output = proposal_result.output or {}
                proposal_md = output.get("proposal_markdown", "")
                company = output.get("company", "")

                # ── Persist proposal ──────────────────────────────────────────
                proposal = Proposal(
                    lead_id=lead_id or "",
                    approval_id=approval_id,
                    company=company,
                    proposal_markdown=proposal_md,
                    tokens_used=output.get("tokens_used"),
                    status=ProposalStatus.draft,
                )
                db.add(proposal)
                await db.flush()

                # ── Email proposal to admin/consultant ────────────────────────
                admin_email = settings.approval_notify_email
                body_html = _proposal_to_html(proposal_md, company)
                emailed = await send_transactional_email(
                    settings,
                    to_email=admin_email,
                    to_name="Klaravex — Admin",
                    subject=f"Neuer Proposal-Entwurf: {company or 'Lead ' + (lead_id or '')[:8]}",
                    body_html=body_html,
                    body_text=proposal_md,
                )
                if emailed:
                    proposal.status = ProposalStatus.emailed
                    proposal.emailed_to = admin_email
                    proposal.emailed_at = datetime.now(timezone.utc)

                dispatch.update({
                    "dispatched": True,
                    "proposal_id": proposal.id,
                    "company": company,
                    "tokens_used": output.get("tokens_used"),
                    "emailed": emailed,
                    "emailed_to": admin_email,
                })
                logger.info(
                    "approvals.proposal_drafted",
                    approval_id=approval_id,
                    proposal_id=proposal.id,
                    company=company,
                    emailed=emailed,
                )
            else:
                dispatch.update({
                    "dispatched": False,
                    "error": proposal_result.error,
                })
                logger.error(
                    "approvals.proposal_draft_failed",
                    approval_id=approval_id,
                    error=proposal_result.error,
                )

        elif action_name == "prospecting_outreach.send":
            from klara.rarv.runtime.email_sender import send_resend_email
            from klara.rarv.prospected_lead import ProspectedLead, ProspectedLeadStatus
            from sqlalchemy import select as sa_select

            prospect_id = payload.get("prospect_id")
            to_email    = payload.get("to_email", "")
            to_name     = payload.get("to_name", "")
            subject     = payload.get("subject", "")
            body_html   = payload.get("body_html", "")
            body_text   = payload.get("body_text", "")

            sent = False
            if to_email and subject:
                sent = await send_resend_email(
                    settings,
                    to_email=to_email,
                    to_name=to_name,
                    subject=subject,
                    body_html=body_html,
                    body_text=body_text,
                )

            # Update ProspectedLead status regardless of send outcome so we don't
            # re-queue on the next beat sweep.  A failed send is logged as an error
            # but the record moves out of outreach_queued to prevent infinite retry.
            if prospect_id:
                pl_result = await db.execute(
                    sa_select(ProspectedLead).where(ProspectedLead.id == prospect_id)
                )
                prospect = pl_result.scalar_one_or_none()
                if prospect:
                    prospect.status = (
                        ProspectedLeadStatus.sent if sent
                        else ProspectedLeadStatus.bounced   # send failed → mark bounced for review
                    )
                    await db.flush()

            dispatch.update({
                "dispatched": True,
                "sent": sent,
                "to_email": to_email,
                "company": payload.get("company_name", ""),
                "prospect_id": prospect_id,
            })
            logger.info(
                "approvals.prospecting_outreach_sent",
                approval_id=approval_id,
                to=to_email,
                sent=sent,
                prospect_id=prospect_id,
            )

        else:
            # ── Fallback: dispatch to Celery execute_approved_action task ─────
            # Handles: seo_content_writer.publish, social_media_manager.publish,
            # proposal_drafting.*, notify_consultant.*, and any future P3/P4 actions
            # added to execute_approved_action.py without requiring changes here.
            from app.tasks.execute_approved_action import execute_approved_action as _exec_task
            _exec_task.delay(approval_id)
            dispatch.update({"dispatched": True, "method": "celery", "action": action_name})
            logger.info(
                "approvals.dispatched_to_celery",
                approval_id=approval_id,
                action=action_name,
            )

    audit = registry.get("audit_logger")
    await audit(
        context,
        {
            "event_type": "approval.approved",
            "action_name": approval.action_name if approval else approval_id,
            "details": {
                "reviewed_by": req.reviewed_by,
                "note": req.note,
                "dispatch": dispatch,
            },
        },
    )

    return {
        "status": "approved",
        "approval_id": approval_id,
        "dispatch": dispatch,
    }


def _proposal_to_html(markdown_text: str, company: str) -> str:
    """
    Convert proposal markdown to a readable HTML email body.
    No extra dependencies — uses stdlib re for basic markdown-to-HTML conversion.
    """
    import re

    html = markdown_text

    # Headings
    html = re.sub(r"^#{3}\s+(.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^#{2}\s+(.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^#{1}\s+(.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

    # Bold and italic
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)

    # Bullet lists (lines starting with - or *)
    def _list_block(m):
        items = re.sub(r"^[-*]\s+(.+)$", r"<li>\1</li>", m.group(0), flags=re.MULTILINE)
        return f"<ul>{items}</ul>"

    html = re.sub(
        r"(^[-*]\s+.+$(\n[-*]\s+.+$)*)",
        _list_block,
        html,
        flags=re.MULTILINE,
    )

    # Paragraphs: blank-line-separated blocks that aren't already HTML tags
    blocks = re.split(r"\n{2,}", html)
    result_blocks = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith("<"):
            result_blocks.append(block)
        else:
            result_blocks.append(f"<p>{block}</p>")
    body = "\n".join(result_blocks)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 14px; color: #222; max-width: 700px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 20px; color: #1a1a2e; border-bottom: 2px solid #1a1a2e; padding-bottom: 6px; }}
  h2 {{ font-size: 17px; color: #1a1a2e; margin-top: 24px; }}
  h3 {{ font-size: 15px; color: #333; }}
  p {{ line-height: 1.6; }}
  ul {{ padding-left: 20px; }}
  li {{ line-height: 1.6; margin-bottom: 4px; }}
  .header {{ background: #1a1a2e; color: white; padding: 16px 24px; border-radius: 4px; margin-bottom: 24px; }}
  .footer {{ color: #888; font-size: 12px; margin-top: 32px; border-top: 1px solid #eee; padding-top: 12px; }}
</style>
</head>
<body>
  <div class="header">
    <strong>Klaravex — Proposal Entwurf</strong><br>
    <span style="font-size:13px; opacity:0.8;">Unternehmen: {company or "Unbekannt"}</span>
  </div>
  {body}
  <div class="footer">
    Dieser Entwurf wurde automatisch von Klaravex generiert und wartet auf Ihre Überprüfung.<br>
    Bitte passen Sie ihn vor dem Versand an den Kunden an.
  </div>
</body>
</html>"""


@router.post("/{approval_id}/reject", dependencies=[Depends(verify_api_key)])
async def reject_action(
    approval_id: str,
    req: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Reject a pending action."""
    context = AgentContext(db=db, settings=settings)
    approval_mgr = registry.get("approval_manager")

    result = await approval_mgr(
        context,
        {
            "action": "reject",
            "approval_id": approval_id,
            "reviewed_by": req.reviewed_by,
            "note": req.note,
        },
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    # ── Post-rejection side-effects ───────────────────────────────────────────
    # For prospecting outreach: mark the prospect disqualified so it never
    # re-queues on the next beat sweep.
    ar_result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    approval = ar_result.scalar_one_or_none()

    if approval and approval.action_name == "prospecting_outreach.send":
        try:
            payload: dict = (
                json.loads(approval.payload)
                if isinstance(approval.payload, str)
                else (approval.payload or {})
            )
        except (json.JSONDecodeError, TypeError):
            payload = {}

        prospect_id = payload.get("prospect_id")
        if prospect_id:
            from klara.rarv.prospected_lead import ProspectedLead, ProspectedLeadStatus
            from sqlalchemy import select as sa_select

            pl_result = await db.execute(
                sa_select(ProspectedLead).where(ProspectedLead.id == prospect_id)
            )
            prospect = pl_result.scalar_one_or_none()
            if prospect:
                prospect.status = ProspectedLeadStatus.disqualified
                prospect.rejection_reason = req.note or f"Rejected by {req.reviewed_by}"
                await db.flush()
                logger.info(
                    "approvals.prospect_disqualified",
                    approval_id=approval_id,
                    prospect_id=prospect_id,
                    reviewed_by=req.reviewed_by,
                )

    audit = registry.get("audit_logger")
    await audit(
        context,
        {
            "event_type": "approval.rejected",
            "action_name": approval.action_name if approval else f"approval.{approval_id}",
            "details": {"reviewed_by": req.reviewed_by, "reason": req.note},
        },
    )

    return {"status": "rejected", "approval_id": approval_id}
