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
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.agents.base import AgentContext
from app.agents.registry import registry
from app.config import get_settings, Settings
from app.core.security import verify_api_key
from app.database import get_db
from app.models.approval import ApprovalRequest, ApprovalStatus

logger = structlog.get_logger(__name__)

router = APIRouter()


class ReviewRequest(BaseModel):
    reviewed_by: str
    note: Optional[str] = None


async def _dispatch_via_smartlead(
    *,
    settings,
    prospect,
    subject: str,
    body_html: str,
    body_text: str,
) -> bool:
    """Push a Claude-drafted prospect into Smartlead's master campaign queue.

    Each lead carries its personalized subject + body as custom_fields that
    interpolate into the campaign sequence's `{{subject_line}}` and
    `{{personalized_body}}` template variables. Smartlead's scheduler
    dispatches via the OAuth-connected M365 mailbox; the EMAIL_SENT webhook
    fires when delivery actually happens. Returns True on successful queue.
    """
    from app.services.smartlead_client import get_client, SmartleadError

    if not settings.smartlead_master_campaign_id:
        logger.error(
            "smartlead_dispatch.no_campaign_id",
            prospect_id=getattr(prospect, "id", None),
        )
        return False

    first = (prospect.contact_first_name or "").strip()
    last = (prospect.contact_last_name or "").strip()
    if not first and prospect.contact_name:
        parts = prospect.contact_name.strip().split(maxsplit=1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ""

    lead = {
        "first_name": first,
        "last_name": last,
        "email": (prospect.contact_email or "").strip(),
        "company_name": prospect.company_name or prospect.domain or "",
        "custom_fields": {
            "subject_line": subject,
            "personalized_body": body_html or body_text,
        },
    }

    try:
        client = get_client(settings)
        result = await client.add_leads_to_campaign(
            settings.smartlead_master_campaign_id, [lead]
        )
    except SmartleadError as exc:
        logger.error(
            "smartlead_dispatch.api_error",
            prospect_id=prospect.id,
            email=lead["email"],
            status=exc.status_code,
            error=str(exc)[:200],
        )
        return False
    except Exception as exc:
        logger.error(
            "smartlead_dispatch.unexpected_error",
            prospect_id=prospect.id,
            email=lead["email"],
            error=str(exc)[:200],
        )
        return False

    upload_count = (result or {}).get("upload_count")
    if upload_count == 0 or (result or {}).get("already_added_to_campaign"):
        logger.warning(
            "smartlead_dispatch.lead_not_added",
            prospect_id=prospect.id,
            email=lead["email"],
            result=result,
        )
        return False

    logger.info(
        "smartlead_dispatch.queued",
        prospect_id=prospect.id,
        email=lead["email"],
        campaign_id=settings.smartlead_master_campaign_id,
        upload_count=upload_count,
    )
    return True


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
            from app.services.email_sender import send_email

            sent = await send_email(
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
            # NOTE: do NOT re-import datetime here. A local `from datetime
            # import datetime` makes datetime a function-local symbol for the
            # entire approve_action body, so any earlier elif branch (e.g.
            # the prospecting_outreach.send path) trips UnboundLocalError
            # when it tries to reference datetime before this conditional
            # has run. The module-level import at line 20 is sufficient.
            from app.services.email_sender import send_email
            from app.models.proposal import Proposal, ProposalStatus

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
                emailed = await send_email(
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
            from app.services.email_sender import send_resend_email
            from app.services.engagement_tracker import augment_for_tracking
            from app.models.prospected_lead import ProspectedLead, ProspectedLeadStatus
            from sqlalchemy import select as sa_select

            prospect_id = payload.get("prospect_id")
            # prospecting_outreach drafter writes contact_email/contact_name
            # (see ProspectingOutreachAgent.run), while testimonial_requester
            # and other drafters write to_email/to_name. Accept either —
            # mismatch caused 23 silent no-ops on 2026-05-29 12:41 Berlin.
            to_email    = payload.get("to_email") or payload.get("contact_email") or ""
            to_name     = payload.get("to_name")  or payload.get("contact_name")  or ""
            subject     = payload.get("subject", "")
            body_html   = payload.get("body_html", "")
            body_text   = payload.get("body_text", "")

            # ── phase3-002 wiring: inject pixel + wrap links before send ──
            # We need the prospect's tracking_token to construct the URLs.
            # Lookup happens here (one row) so the augment never silently
            # falls back to an untracked send.
            tracked_html = body_html
            prospect = None
            if prospect_id:
                pl_result = await db.execute(
                    sa_select(ProspectedLead).where(ProspectedLead.id == prospect_id)
                )
                prospect = pl_result.scalar_one_or_none()
                if prospect and getattr(prospect, "tracking_token", None):
                    base = getattr(settings, "app_base_url", "https://api.klaravex.de")
                    tracked_html = augment_for_tracking(body_html, base, prospect.tracking_token)

            sent = False
            # phase4-005: pre-send suppression check.
            from app.services.suppression import is_suppressed
            if await is_suppressed(db, to_email):
                logger.info(
                    "approvals.prospecting_outreach_blocked_by_suppression",
                    approval_id=approval_id,
                    to=to_email,
                )
            elif to_email and subject:
                # Transport selection — Smartlead (campaign queue via M365 OAuth
                # mailbox) or Resend (direct SMTP-style API send). Default is
                # Resend until Smartlead's mailbox finishes its 14-21 day warmup.
                if settings.outreach_transport == "smartlead":
                    sent = await _dispatch_via_smartlead(
                        settings=settings,
                        prospect=prospect,
                        subject=subject,
                        body_html=tracked_html,
                        body_text=body_text,
                    )
                else:
                    sent = await send_resend_email(
                        settings,
                        to_email=to_email,
                        to_name=to_name,
                        subject=subject,
                        body_html=tracked_html,
                        body_text=body_text,
                        reply_to=settings.outreach_reply_to,
                    )

            # Update ProspectedLead status regardless of send outcome so we don't
            # re-queue on the next beat sweep.  A failed send is logged as an error
            # but the record moves out of outreach_queued to prevent infinite retry.
            if prospect_id and prospect is not None:
                prospect.status = (
                    ProspectedLeadStatus.sent if sent
                    else ProspectedLeadStatus.bounced   # send failed → mark bounced for review
                )
                if sent:
                    prospect.outreach_sent_at = datetime.now(timezone.utc)
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

        elif action_name == "proposal.send":
            # phase5-002: client-facing proposal send. Reads the proposal_id
            # from payload, lets the service do suppression + tracking + send.
            from app.services.proposal_send import send_proposal_to_client
            proposal_id = payload.get("proposal_id")
            if not proposal_id:
                dispatch.update({"dispatched": False, "error": "missing proposal_id"})
            else:
                result = await send_proposal_to_client(db, settings, proposal_id)
                dispatch.update(result)
                logger.info(
                    "approvals.proposal_sent",
                    approval_id=approval_id,
                    proposal_id=proposal_id,
                    sent=result.get("sent"),
                    suppressed=result.get("suppressed"),
                )

        elif action_name == "reply_draft.send":
            # phase4-002: send a Claude-drafted response to a cold-outreach reply.
            # Idempotent — refuses to resend a draft already marked sent.
            from app.services.email_sender import send_resend_email
            from app.models.reply_draft import ReplyDraft, ReplyDraftStatus
            from sqlalchemy import select as sa_select

            prospect_id = payload.get("prospect_id")
            to_email    = payload.get("to_email", "")
            to_name     = payload.get("to_name") or ""
            subject     = payload.get("subject", "")
            body_html   = payload.get("body_html", "")
            body_text   = payload.get("body_text") or ""

            draft = None
            if prospect_id:
                draft_q = await db.execute(
                    sa_select(ReplyDraft).where(
                        ReplyDraft.prospected_lead_id == prospect_id
                    )
                )
                draft = draft_q.scalar_one_or_none()

            already_sent = bool(draft and draft.status == ReplyDraftStatus.sent)
            sent = False
            # phase4-005: pre-send suppression check.
            from app.services.suppression import is_suppressed
            if already_sent:
                logger.info(
                    "approvals.reply_draft_already_sent",
                    approval_id=approval_id,
                    prospect_id=prospect_id,
                    draft_id=draft.id,
                )
            elif await is_suppressed(db, to_email):
                logger.info(
                    "approvals.reply_draft_blocked_by_suppression",
                    approval_id=approval_id,
                    to=to_email,
                )
            elif to_email and subject and body_html:
                sent = await send_resend_email(
                    settings,
                    to_email=to_email,
                    to_name=to_name,
                    subject=subject,
                    body_html=body_html,
                    body_text=body_text,
                    reply_to=settings.outreach_reply_to,
                )

            if draft is not None and sent:
                draft.status = ReplyDraftStatus.sent
                draft.sent_at = datetime.now(timezone.utc)
                await db.flush()

            dispatch.update({
                "dispatched": True,
                "sent": sent or already_sent,
                "to_email": to_email,
                "prospect_id": prospect_id,
                "draft_id": draft.id if draft else None,
                "idempotent_skip": already_sent,
            })
            logger.info(
                "approvals.reply_draft_sent",
                approval_id=approval_id,
                to=to_email,
                sent=sent,
                prospect_id=prospect_id,
                already_sent=already_sent,
            )

        else:
            # ── Fallback: dispatch to Celery execute_approved_action task ─────
            # Handles: seo_content_writer.publish, social_media_manager.publish,
            # proposal_drafting.*, notify_consultant.*, and any future P3/P4 actions
            # added to execute_approved_action.py without requiring changes here.
            #
            # A broker outage here must NOT roll back the approval — the row is
            # already marked approved and the audit log captures the decision.
            # We log a warning instead so ops can reconcile (e.g. via a sweep
            # task that re-dispatches approved-but-not-dispatched rows).
            from app.tasks.execute_approved_action import execute_approved_action as _exec_task
            try:
                _exec_task.delay(approval_id)
                dispatch.update({"dispatched": True, "method": "celery", "action": action_name})
                logger.info(
                    "approvals.dispatched_to_celery",
                    approval_id=approval_id,
                    action=action_name,
                )
            except Exception as celery_error:
                dispatch.update({
                    "dispatched": False,
                    "method": "celery",
                    "action": action_name,
                    "error": str(celery_error),
                })
                logger.warning(
                    "approvals.celery_dispatch_failed",
                    approval_id=approval_id,
                    action=action_name,
                    error=str(celery_error),
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
    Dieser Entwurf wurde automatisch von Klara AI generiert und wartet auf Ihre Überprüfung.<br>
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
            from app.models.prospected_lead import ProspectedLead, ProspectedLeadStatus
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

    if approval and approval.action_name == "reply_draft.send":
        # phase4-002: mark the draft rejected; do NOT touch the ProspectedLead
        # status — the prospect already replied; we just don't send our draft.
        from app.models.reply_draft import ReplyDraft, ReplyDraftStatus
        from sqlalchemy import select as sa_select

        rd_result = await db.execute(
            sa_select(ReplyDraft).where(ReplyDraft.approval_id == approval_id)
        )
        draft = rd_result.scalar_one_or_none()
        if draft and draft.status != ReplyDraftStatus.rejected:
            draft.status = ReplyDraftStatus.rejected
            draft.rejected_at = datetime.now(timezone.utc)
            await db.flush()
            logger.info(
                "approvals.reply_draft_rejected",
                approval_id=approval_id,
                draft_id=draft.id,
                reviewed_by=req.reviewed_by,
            )

    # phase21-004: autonomy.promote rejection. Clear the streak's
    # pending_promotion_approval_id (so a future sweep can re-propose) AND
    # reset streak_started_at to now (so the agent needs to re-earn the
    # 14-day green streak from scratch — explicit cooldown). Defensive race
    # guard: only act when the streak's pending_id matches THIS approval_id.
    if approval and approval.action_name == "autonomy.promote":
        try:
            payload: dict = (
                json.loads(approval.payload)
                if isinstance(approval.payload, str)
                else (approval.payload or {})
            )
        except (json.JSONDecodeError, TypeError):
            payload = {}
        agent_name = payload.get("agent_name")
        if agent_name:
            from app.models.autonomy_streak import AutonomyStreak
            from sqlalchemy import select as sa_select
            now = datetime.now(timezone.utc)
            sr = await db.execute(
                sa_select(AutonomyStreak).where(AutonomyStreak.agent_name == agent_name)
            )
            streak = sr.scalar_one_or_none()
            if streak and streak.pending_promotion_approval_id == approval_id:
                streak.pending_promotion_approval_id = None
                streak.streak_started_at = now
                streak.last_checked_at = now
                await db.flush()
                logger.info(
                    "approvals.autonomy_promote_rejected",
                    approval_id=approval_id,
                    agent_name=agent_name,
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
