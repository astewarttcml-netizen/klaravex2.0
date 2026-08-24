"""
app/tasks/execute_approved_action.py
──────────────────────────────────────
Celery task: executes an approved P3/P4/P5 action after human sign-off.

Called by the approval endpoint after a reviewer clicks Approve.
Looks up the approval request, deserialises the payload, and re-runs
the relevant agent with approval_bypass=True.

Supported action namespaces
───────────────────────────
  proposal_drafting.*        → re-runs ProposalDraftingAgent
  seo_content_writer.publish → triggers WebsiteDeployAgent(action="create_post")
  social_media_manager.publish → publishes to all configured social platforms concurrently
  notify_consultant.*        → sends internal WARM-lead alert to consultant
"""
from __future__ import annotations

import asyncio
import json
import uuid

import structlog

from app.tasks.celery_app import celery_app
from app.config import get_settings
from app.database import db_context
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.audit import AuditLog

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Celery entry point
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.execute_approved_action.execute_approved_action",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def execute_approved_action(self, approval_id: str):
    """Execute a previously approved action."""
    # Reset the SQLAlchemy async engine singleton before every asyncio.run() call.
    # asyncio.run() creates a fresh event loop each time; the module-level _engine
    # was bound to the PREVIOUS loop, so any asyncpg connection reuse raises
    # "Future attached to a different loop".  Nulling the globals forces recreation
    # on the current loop.  Old connections time out naturally (pool_size=10, small deploy).
    import app.database as _db_module
    _db_module._engine = None
    _db_module._session_factory = None

    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        asyncio.run(_execute(approval_id))
    except Exception as exc:
        logger.error(
            "execute_approved_action.task_failed",
            approval_id=approval_id,
            error=str(exc),
            exc_info=True,
        )
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Core dispatcher
# ──────────────────────────────────────────────────────────────────────────────

async def _execute(approval_id: str):
    settings = get_settings()
    async with db_context() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
        )
        req = result.scalar_one_or_none()

        if not req:
            logger.error("execute_approved_action.not_found", approval_id=approval_id)
            return

        if req.status != ApprovalStatus.approved:
            logger.warning(
                "execute_approved_action.not_approved",
                approval_id=approval_id,
                status=req.status,
            )
            return

        payload = json.loads(req.payload) if req.payload else {}
        action = req.action_name

        logger.info(
            "execute_approved_action.running",
            approval_id=approval_id,
            action=action,
            lead_id=str(req.lead_id) if req.lead_id else None,
        )

        if action.startswith("proposal_drafting"):
            await _run_proposal(db, settings, payload, req)
        elif action == "seo_content_writer.publish":
            await _run_seo_publish(db, settings, payload, req)
        elif action == "social_media_manager.publish":
            await _run_social_publish(db, settings, payload, req)
        elif action.startswith("notify_consultant"):
            await _notify_consultant(settings, payload, req)
        elif action == "invoice_generator.send_to_client":
            await _run_invoice_send(db, settings, payload, req)
        elif action == "send_client_onboarding_email":
            await _run_client_onboarding_email(db, settings, payload, req)
        elif action == "autonomy.promote":
            await _run_autonomy_promote(db, settings, payload, req)
        else:
            logger.warning("execute_approved_action.unknown_action", action=action)


# ──────────────────────────────────────────────────────────────────────────────
# Action handlers
# ──────────────────────────────────────────────────────────────────────────────

async def _run_proposal(db, settings, payload: dict, req: ApprovalRequest):
    """Re-run ProposalDraftingAgent after P4 approval."""
    from app.agents.base import AgentContext
    from app.agents.registry import registry

    context = AgentContext(
        db=db,
        settings=settings,
        lead_id=req.lead_id,
        conversation_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
    )
    agent = registry.get("proposal_drafting")
    result = await agent(context, payload)
    logger.info(
        "execute_approved_action.proposal_complete",
        lead_id=str(req.lead_id),
        success=result.success,
        error=result.error,
    )


async def _run_seo_publish(db, settings, payload: dict, req: ApprovalRequest):
    """
    Publish an approved SEO content piece as a WP draft via WebsiteDeployAgent(action="create_post").

    Uses create_post — not execute — because SEO posts are new WP posts, not updates to
    existing pages.  The execute action requires a pre-existing WebsiteDeployJob record with
    a page_id, which SEO content never has.

    Expected payload keys (set by SeoContentWriterAgent when it queues approval):
      keyword      — target keyword (used to derive slug)
      title        — post title
      content_html — rendered HTML body
      meta         — SEO description string (used as WP excerpt)
      post_type    — "post" | "page" (default "post")
      language     — "en" | "de" (logged only)
    """
    from app.agents.base import AgentContext
    from app.agents.registry import registry

    context = AgentContext(
        db=db,
        settings=settings,
        lead_id=req.lead_id,
        conversation_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
    )

    deploy_payload = {
        "action":       "create_post",
        "keyword":      payload.get("keyword", ""),
        "title":        payload.get("title", ""),
        "content_html": payload.get("content_html", ""),
        "meta":         payload.get("meta", ""),
        "post_type":    payload.get("post_type", "post"),
        "language":     payload.get("language", "en"),
    }

    agent = registry.get("website_deploy")
    result = await agent(context, deploy_payload)
    logger.info(
        "execute_approved_action.seo_publish_complete",
        keyword=payload.get("keyword"),
        language=payload.get("language"),
        success=result.success,
        error=result.error,
        output=result.output,
    )


async def _run_social_publish(db, settings, payload: dict, req: ApprovalRequest):
    """
    Publish an approved social media post to all requested platforms concurrently.

    Calls social_publisher.publish_all() which handles LinkedIn Company,
    LinkedIn Personal, Twitter/X (thread), XING, and Facebook.  Platforms
    with missing credentials are skipped with a failed PublishResult — they
    do NOT abort the other platforms.

    After publishing, notifies the consultant with a per-platform summary
    including live post URLs for successful publishes.

    Expected payload keys (set by SocialMediaManagerAgent.run()):
      topic          — post topic (str)
      drafts         — dict mapping platform key → draft text
      platforms      — list of platforms to publish (subset of drafts keys)
      image_prompts  — dict mapping platform key → visual description for a
                        Higgsfield-generated image (2026-07-19; empty string
                        for platforms without one, e.g. reddit)
      scheduled_for  — ISO datetime string or None
      lead_id        — source lead UUID (optional)
    """
    from app.services.social_publisher import publish_all, PublishResult
    from app.services.social_rate_limit import filter_platforms_under_daily_cap

    # platform_topics holds a per-platform topic when each platform has its own.
    # Fallback to the legacy single "topic" field for lead-triggered posts.
    platform_topics: dict = payload.get("platform_topics", {})
    topic: str = payload.get("topic", "")   # legacy / lead-triggered fallback
    drafts: dict = payload.get("drafts", {})
    platforms: list = payload.get("platforms", [])
    image_prompts: dict = payload.get("image_prompts", {})
    scheduled_for = payload.get("scheduled_for", "")

    logger.info(
        "execute_approved_action.social_publish_starting",
        platforms=platforms,
        per_platform_topics=bool(platform_topics),
        topic=topic or "(per-platform)",
        scheduled_for=scheduled_for,
        lead_id=str(req.lead_id) if req.lead_id else None,
    )

    # ── Enforce hard 2-posts-per-platform-per-day cap ──────────────────────────
    allowed_platforms, blocked_platforms = await filter_platforms_under_daily_cap(
        db, platforms
    )
    for p in blocked_platforms:
        logger.warning(
            "social_publish.rate_limited", platform=p, reason="daily_cap_2_reached"
        )

    # ── Generate videos for video-capable platforms (ComfyUI on rig) ─────────
    video_paths: dict[str, str] = {}
    video_capable = {"tiktok", "youtube", "instagram"}
    video_platforms = [p for p in allowed_platforms if p in video_capable]
    if video_platforms:
        # Use the first available image prompt as the video prompt
        video_prompt = ""
        for p in video_platforms:
            video_prompt = image_prompts.get(p, "")
            if video_prompt:
                break
        if not video_prompt:
            video_prompt = topic  # fall back to the post topic

        if video_prompt:
            try:
                import sys
                sys.path.insert(0, "/home/anthony/klaravex/infra/cron")
                from social_video_bridge import generate_videos_for_platforms
                video_map = await generate_videos_for_platforms(video_prompt, video_platforms)
                video_paths = {k: str(v) for k, v in video_map.items() if v is not None}
                logger.info("social_publish.videos_generated",
                            platforms=list(video_paths.keys()),
                            count=len(video_paths))
            except Exception as exc:
                logger.warning("social_publish.video_generation_failed",
                               error=str(exc)[:200])

    # ── Execute all publishes concurrently (allowed platforms only) ───────────
    results = await publish_all(drafts, allowed_platforms, settings,
                                image_prompts=image_prompts, video_paths=video_paths)
    results.extend(
        PublishResult(
            platform=p,
            success=False,
            error="blocked: daily cap of 2/day reached",
        )
        for p in blocked_platforms
    )

    # ── Log per-platform outcomes ─────────────────────────────────────────────
    successes = [r for r in results if r.success]
    failures  = [r for r in results if not r.success]

    # ── Write audit trail — one row per platform result ───────────────────────
    for r in results:
        audit_row = AuditLog(
            event_type="social.published",
            agent_name="social_media_manager",
            action_name=r.platform,
            approval_id=str(req.id),
            lead_id=str(req.lead_id) if req.lead_id else None,
            details=json.dumps({
                # Use the platform-specific topic if available, else fall back
                # to the shared topic string (lead-triggered posts).
                "topic":    platform_topics.get(r.platform) or topic,
                "platform": r.platform,
                "success":  r.success,
                "post_url": r.post_url,
                "post_id":  r.post_id,
                "error":    r.error,
            }),
        )
        db.add(audit_row)
    await db.flush()

    logger.info(
        "execute_approved_action.social_publish_complete",
        topic=topic or "(per-platform)",
        total=len(results),
        succeeded=len(successes),
        failed=len(failures),
        post_urls={r.platform: r.post_url for r in successes},
        errors={r.platform: r.error for r in failures},
        lead_id=str(req.lead_id) if req.lead_id else None,
    )

    # ── Build notification payload ────────────────────────────────────────────
    success_lines = "\n".join(
        f"  ✓ {r.platform}: {r.post_url or r.post_id}" for r in successes
    )
    failure_lines = "\n".join(
        f"  ✗ {r.platform}: {r.error}" for r in failures
    )

    if successes and not failures:
        note = f"All {len(successes)} platform(s) published successfully."
    elif successes and failures:
        note = (
            f"{len(successes)} platform(s) published successfully, "
            f"{len(failures)} failed — see details below."
        )
    else:
        note = f"All {len(failures)} platform(s) failed to publish — see errors below."

    # Append post URLs to drafts dict so _notify_consultant can show them
    notify_payload = {
        "subject": f"[Klaravex] Social publish complete ({len(successes)}/{len(results)} OK): {topic}",
        "lead_name": payload.get("lead_name", ""),
        "note": note,
        "scheduled_for": scheduled_for,
        "platforms": platforms,
        "_publish_success_lines": success_lines,
        "_publish_failure_lines": failure_lines,
        # Preserve drafts for the email body so Anthony can see what was posted
        "linkedin_text": drafts.get("linkedin_company") or drafts.get("linkedin_personal", ""),
        "xing_text": drafts.get("xing", ""),
    }

    await _notify_consultant(settings, notify_payload, req)


async def _notify_consultant(settings, payload: dict, req: ApprovalRequest):
    """
    Send an internal alert to the consultant (Anthony) for WARM lead or
    approved action requiring attention.

    Composes a concise HTML + text email via the primary SMTP service.
    Falls back gracefully if SMTP is not configured (logs only).
    """
    from app.services.email_sender import send_email

    to_email = settings.approval_notify_email
    lead_id_str = str(req.lead_id) if req.lead_id else "N/A"

    # Allow callers to override subject/body via payload
    subject = payload.get(
        "subject",
        f"[Klaravex] Action approved and executed — lead {lead_id_str}",
    )
    note = payload.get("note", "An approved action has completed execution.")
    lead_name = payload.get("lead_name", "")
    linkedin_text = payload.get("linkedin_text", "")
    xing_text = payload.get("xing_text", "")
    platforms = payload.get("platforms", [])
    scheduled_for = payload.get("scheduled_for", "")
    success_lines = payload.get("_publish_success_lines", "")
    failure_lines = payload.get("_publish_failure_lines", "")

    # ── Plain text ─────────────────────────────────────────────────────────────
    text_lines = [
        f"Klaravex — Action Notification",
        f"",
        f"Note: {note}",
        f"Lead ID: {lead_id_str}",
    ]
    if lead_name:
        text_lines.append(f"Lead: {lead_name}")
    if success_lines:
        text_lines += ["", "Published successfully:", success_lines]
    if failure_lines:
        text_lines += ["", "Failed:", failure_lines]
    if linkedin_text:
        text_lines += [f"", f"LinkedIn copy:", linkedin_text]
    if xing_text:
        text_lines += [f"", f"XING copy:", xing_text]
    if platforms:
        text_lines.append(f"Platforms: {', '.join(platforms)}")
    if scheduled_for:
        text_lines.append(f"Scheduled for: {scheduled_for}")
    body_text = "\n".join(text_lines)

    # ── HTML ───────────────────────────────────────────────────────────────────
    html_parts = [
        "<h2 style='color:#1a1a2e'>Klaravex — Action Notification</h2>",
        f"<p><strong>Note:</strong> {note}</p>",
        f"<p><strong>Lead ID:</strong> {lead_id_str}</p>",
    ]
    if lead_name:
        html_parts.append(f"<p><strong>Lead:</strong> {lead_name}</p>")
    if success_lines:
        html_parts += [
            "<hr>",
            "<h3>✓ Published</h3>",
            f"<pre style='background:#e8f5e9;padding:12px;border-radius:4px'>{success_lines}</pre>",
        ]
    if failure_lines:
        html_parts += [
            "<h3>✗ Failed</h3>",
            f"<pre style='background:#fff3e0;padding:12px;border-radius:4px'>{failure_lines}</pre>",
        ]
    if linkedin_text:
        html_parts += [
            "<hr>",
            "<h3>LinkedIn Post Copy</h3>",
            f"<pre style='background:#f5f5f5;padding:12px;border-radius:4px'>{linkedin_text}</pre>",
        ]
    if xing_text:
        html_parts += [
            "<h3>XING Post Copy</h3>",
            f"<pre style='background:#f5f5f5;padding:12px;border-radius:4px'>{xing_text}</pre>",
        ]
    if platforms:
        html_parts.append(f"<p><strong>Platforms:</strong> {', '.join(platforms)}</p>")
    if scheduled_for:
        html_parts.append(f"<p><strong>Scheduled for:</strong> {scheduled_for}</p>")

    body_html = "\n".join(html_parts)

    sent = await send_email(
        settings,
        to_email=to_email,
        to_name="Klaravex",
        subject=subject,
        body_html=body_html,
        body_text=body_text,
    )

    logger.info(
        "execute_approved_action.consultant_notified",
        to=to_email,
        lead_id=lead_id_str,
        sent=sent,
    )


async def _run_invoice_send(db, settings, payload: dict, req: ApprovalRequest):
    """
    Send an approved PDF invoice to the client via Resend with the PDF attached.

    Expected payload keys (set by InvoiceGeneratorAgent):
      invoice_id          — GeneratedInvoice UUID
      invoice_number      — INV-YYYY-NNNN
      client_name         — recipient name
      client_email        — recipient email
      client_company      — recipient company (optional)
      service_description — service summary
      amount_gross        — total amount due (float, EUR)
      currency            — "EUR"
      issued_date         — ISO date string
      due_date            — ISO date string
      pdf_path            — absolute path to PDF on server
      lead_id             — associated lead UUID (optional)
      notes               — internal notes (not sent to client)
    """
    from app.models.generated_invoice import GeneratedInvoice, GeneratedInvoiceStatus
    from app.services.email_sender import send_transactional_email_with_attachment
    from sqlalchemy import select
    import textwrap

    invoice_id     = payload.get("invoice_id")
    invoice_number = payload.get("invoice_number", "")
    client_name    = payload.get("client_name", "")
    client_email   = payload.get("client_email", "")
    client_company = payload.get("client_company", "")
    amount_gross   = payload.get("amount_gross", 0.0)
    currency       = payload.get("currency", "EUR")
    due_date       = payload.get("due_date", "")
    pdf_path       = payload.get("pdf_path", "")

    currency_sym = "€" if currency == "EUR" else currency
    greeting_name = client_company or client_name

    log = logger.bind(
        action="invoice_generator.send_to_client",
        invoice_number=invoice_number,
        client_email=client_email,
        approval_id=str(req.id),
    )

    # ── Read PDF bytes ────────────────────────────────────────────────────────
    try:
        with open(pdf_path, "rb") as fh:
            pdf_bytes = fh.read()
    except OSError as exc:
        log.error("invoice_send.pdf_read_failed", path=pdf_path, error=str(exc))
        return

    log.info("invoice_send.pdf_loaded", size_bytes=len(pdf_bytes))

    # ── Compose email ─────────────────────────────────────────────────────────
    subject = f"Invoice {invoice_number} — Klaravex"

    body_html = textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;
                     padding:24px;color:#222;">

        <h2 style="color:#1a1a2e;margin-bottom:4px;">Klaravex</h2>
        <p style="color:#888;margin-top:0;">klaravex.com</p>
        <hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">

        <p>Dear {greeting_name},</p>

        <p>Please find attached invoice <strong>{invoice_number}</strong>
        for our recent engagement.</p>

        <table style="border-collapse:collapse;width:100%;margin:16px 0;
                      border:1px solid #e0e0e0;border-radius:4px;">
          <tr style="background:#f0f4ff;">
            <td style="padding:10px 16px;font-weight:bold;width:45%;">Invoice Number</td>
            <td style="padding:10px 16px;">{invoice_number}</td>
          </tr>
          <tr>
            <td style="padding:10px 16px;font-weight:bold;">Amount Due</td>
            <td style="padding:10px 16px;font-size:18px;font-weight:bold;">
              {currency_sym}{amount_gross:,.2f}
            </td>
          </tr>
          <tr style="background:#f0f4ff;">
            <td style="padding:10px 16px;font-weight:bold;">Payment Due</td>
            <td style="padding:10px 16px;">{due_date}</td>
          </tr>
        </table>

        <p>Payment details are on the invoice PDF.</p>

        <p>If you have any questions, please reply to this email.</p>

        <p>Best regards,<br>
        <strong>Anthony Stewart</strong><br>
        Klaravex<br>
        <a href="https://klaravex.com">klaravex.com</a></p>

        <hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">
        <p style="font-size:11px;color:#aaa;">
          Klaravex LLC · Wyoming, United States · hello@klaravex.com
        </p>
        </body>
        </html>
    """)

    body_text = (
        f"Dear {greeting_name},\n\n"
        f"Please find attached invoice {invoice_number} for our recent engagement.\n\n"
        f"Invoice Number: {invoice_number}\n"
        f"Amount Due:     {currency_sym}{amount_gross:,.2f}\n"
        f"Payment Due:    {due_date}\n\n"
        f"Payment details are on the invoice PDF.\n\n"
        f"If you have any questions, please reply to this email.\n\n"
        f"Best regards,\n"
        f"Anthony Stewart\n"
        f"Klaravex\n"
        f"klaravex.com\n"
    )

    # ── Send ──────────────────────────────────────────────────────────────────
    sent = await send_transactional_email_with_attachment(
        settings,
        to_email=client_email,
        to_name=client_name,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
        attachment_bytes=pdf_bytes,
        attachment_filename=f"{invoice_number}.pdf",
        reply_to="hello@klaravex.com",
    )

    # ── Update invoice status ─────────────────────────────────────────────────
    result = await db.execute(
        select(GeneratedInvoice).where(GeneratedInvoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()

    if inv:
        from datetime import datetime, timezone
        if sent:
            inv.status  = GeneratedInvoiceStatus.sent
            inv.sent_at = datetime.now(tz=timezone.utc)
        # Even on send failure, mark as approved so it can be retried manually
        elif inv.status == GeneratedInvoiceStatus.draft:
            inv.status = GeneratedInvoiceStatus.approved
        await db.flush()

    log.info(
        "invoice_send.complete",
        sent=sent,
        invoice_number=invoice_number,
        client_email=client_email,
    )

    # ── Write audit log ───────────────────────────────────────────────────────
    audit_row = AuditLog(
        event_type="invoice.sent" if sent else "invoice.send_failed",
        agent_name="invoice_generator",
        action_name="invoice_generator.send_to_client",
        approval_id=str(req.id),
        lead_id=payload.get("lead_id") or (str(req.lead_id) if req.lead_id else None),
        details=json.dumps({
            "invoice_number": invoice_number,
            "client_email":   client_email,
            "amount_gross":   amount_gross,
            "currency":       currency,
            "due_date":       due_date,
            "sent":           sent,
            "pdf_path":       pdf_path,
        }),
    )
    db.add(audit_row)
    await db.flush()


async def _run_client_onboarding_email(db, settings, payload: dict, req: ApprovalRequest):
    """
    Execute an approved client onboarding action.

    Steps:
      1. Send the onboarding welcome email via Resend.
      2. Auto-provision a portal_clients row (idempotent — skip if email exists).
      3. Send the client a magic login link email so they can access the portal.
      4. Write audit log.

    Expected payload keys (set by ClientOnboardingAgent):
      lead_id      — lead UUID
      to_email     — client email
      to_name      — client display name
      subject      — welcome email subject
      body_html    — welcome email HTML body
      body_text    — welcome email plain text body
      language     — "en" | "de"
    """
    from sqlalchemy import select
    from app.models.portal import Client
    from app.services.email_sender import send_transactional_email
    from app.services.magic_link_service import request_link
    import uuid as _uuid

    lead_id    = payload.get("lead_id") or (str(req.lead_id) if req.lead_id else None)
    to_email   = payload.get("to_email", "")
    to_name    = payload.get("to_name", "")
    subject    = payload.get("subject", "Welcome to Klaravex")
    body_html  = payload.get("body_html", "")
    body_text  = payload.get("body_text", "")
    language   = payload.get("language", "en")

    log = logger.bind(
        action="send_client_onboarding_email",
        lead_id=lead_id,
        to_email=to_email,
        approval_id=str(req.id),
    )

    # ── 1. Send welcome email ─────────────────────────────────────────────────
    if to_email:
        sent = await send_transactional_email(
            settings,
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
        )
        log.info("client_onboarding_email.sent", sent=sent)
    else:
        sent = False
        log.warning("client_onboarding_email.no_email_address")

    # ── 2. Provision portal Client row (idempotent) ───────────────────────────
    client = None
    if to_email:
        # Check if a portal client already exists for this email
        existing = await db.execute(
            select(Client).where(Client.email == to_email.lower())
        )
        client = existing.scalar_one_or_none()

        if client is None:
            # Load lead for name/company data
            from app.models.lead import Lead
            lead_result = await db.execute(
                select(Lead).where(Lead.id == lead_id)
            ) if lead_id else None
            lead = lead_result.scalar_one_or_none() if lead_result else None

            client = Client(
                id=str(_uuid.uuid4()),
                name=to_name or (lead.name if lead else to_email),
                email=to_email.lower(),
                company=lead.company if lead else None,
                hashed_password=None,   # passwordless — magic link only
                is_active=True,
                language_preference=language,
                internal_notes=(
                    f"Auto-provisioned from lead {lead_id} "
                    f"on onboarding approval {str(req.id)}"
                ),
            )
            db.add(client)
            await db.flush()
            log.info("client_onboarding_email.portal_client_created", client_id=client.id)
        else:
            log.info("client_onboarding_email.portal_client_already_exists", client_id=client.id)

    # ── 3. Send portal magic link ─────────────────────────────────────────────
    if client and to_email:
        try:
            await request_link(email=to_email, db=db, settings=settings)
            log.info("client_onboarding_email.magic_link_sent", client_id=client.id)
        except Exception as exc:
            # Non-fatal — welcome email already sent; link can be re-requested
            log.warning("client_onboarding_email.magic_link_failed", error=str(exc))

    # ── 4. Audit log ──────────────────────────────────────────────────────────
    audit_row = AuditLog(
        event_type="client.onboarding_email_sent" if sent else "client.onboarding_email_failed",
        agent_name="client_onboarding",
        action_name="send_client_onboarding_email",
        approval_id=str(req.id),
        lead_id=lead_id,
        details=json.dumps({
            "to_email":  to_email,
            "to_name":   to_name,
            "subject":   subject,
            "language":  language,
            "sent":      sent,
            "client_id": client.id if client else None,
        }),
    )
    db.add(audit_row)
    await db.flush()

    log.info(
        "client_onboarding_email.complete",
        sent=sent,
        portal_client_id=client.id if client else None,
    )

    # ── 5. phase6-001 — auto-queue contract_generator P4 approval ─────────────
    # Onboarding email landed → next step is the SoW/contract. The trigger
    # service writes a P4 ApprovalRequest and stamps lead.contract_sent_at
    # for idempotency. Failures here MUST NOT roll back the onboarding work.
    if sent and lead_id:
        try:
            from app.services.contract_trigger import queue_contract_draft
            from app.models.lead import Lead
            lead_row = (await db.execute(
                select(Lead).where(Lead.id == lead_id)
            )).scalar_one_or_none()
            if lead_row is not None:
                contract_approval = await queue_contract_draft(db, lead_row)
                if contract_approval:
                    log.info(
                        "client_onboarding_email.contract_queued",
                        contract_approval_id=contract_approval,
                    )
        except Exception as exc:
            log.error(
                "client_onboarding_email.contract_trigger_failed",
                error=str(exc),
            )


# ──────────────────────────────────────────────────────────────────────────────
# phase21-001 — autonomy.promote handler
# ──────────────────────────────────────────────────────────────────────────────

async def _run_autonomy_promote(db, settings, payload: dict, req: ApprovalRequest):
    """
    Handle an approved autonomy.promote P4 request (phase19-010 emitted it,
    Anthony approved it).

    Side effects:
      1. Write an AutonomyPromotion ledger row capturing the metric snapshot
         at approval time (sourced from autonomy_metrics for the same window
         the streak runner uses).
      2. Clear AutonomyStreak.pending_promotion_approval_id so the streak row
         is no longer "promotion in flight". The streak start time is kept
         (the green run continues — only the pending flag clears).

    What this does NOT do:
      - Flip the agent's permission_level constant. Deploy gate is
        intentional: changing permission levels is a code-level edit that
        gets reviewed in a PR and shipped via the normal Docker rebuild.
        The ledger row is the audit-of-record that Anthony approved the
        promotion; the actual constant change is a follow-up by hand.

    Idempotency:
      A duplicate Celery dispatch for the same approval_id will hit the
      UNIQUE partial index on autonomy_promotions.approval_id and be
      detected; we short-circuit BEFORE the insert by checking for an
      existing row.
    """
    from sqlalchemy import select
    from app.api.reports_admin import autonomy_metrics
    from app.models.autonomy_promotion import AutonomyPromotion
    from app.models.autonomy_streak import AutonomyStreak

    agent_name = payload.get("agent_name")
    from_level = payload.get("from_level", "P3")
    to_level   = payload.get("to_level",   "P2")
    if not agent_name:
        logger.error("autonomy_promote.missing_agent_name", approval_id=req.id)
        return

    log = logger.bind(agent_name=agent_name, approval_id=req.id)

    # ── Idempotency: was this approval already handled? ──
    existing_q = await db.execute(
        select(AutonomyPromotion).where(AutonomyPromotion.approval_id == req.id)
    )
    if existing_q.scalar_one_or_none() is not None:
        log.info("autonomy_promote.idempotent_hit")
        return

    # ── Metric snapshot at approval time ──
    # Source: same autonomy_metrics endpoint the streak runner uses, same
    # 30-day window. The snapshot may differ from the snapshot at proposal
    # time (phase19-010 doesn't store it in the payload); we capture
    # whichever Anthony saw most recently when he approved.
    snap = {"approval_rate": None, "error_rate": None, "rollback_rate": None, "window_days": 30}
    try:
        metrics = await autonomy_metrics(days=30, db=db)
        for a in metrics.get("agents", []):
            if a.get("agent_name") == agent_name:
                snap["approval_rate"] = a.get("approval_rate")
                snap["error_rate"]    = a.get("error_rate")
                snap["rollback_rate"] = a.get("rollback_rate")
                break
    except Exception as exc:
        log.warning("autonomy_promote.metric_snapshot_failed", error=str(exc))

    # ── Ledger row ──
    ledger = AutonomyPromotion(
        agent_name=agent_name,
        from_level=from_level,
        to_level=to_level,
        reason=payload.get("reason") or "approved_via_autonomy.promote",
        justification=req.justification or "(no justification recorded)",
        approval_rate=snap["approval_rate"],
        error_rate=snap["error_rate"],
        rollback_rate=snap["rollback_rate"],
        window_days=snap["window_days"],
        promoted_by=req.reviewed_by or "system:execute_approved_action",
        approval_id=req.id,
    )
    db.add(ledger)

    # ── Clear streak.pending_promotion_approval_id ──
    streak_q = await db.execute(
        select(AutonomyStreak).where(AutonomyStreak.agent_name == agent_name)
    )
    streak = streak_q.scalar_one_or_none()
    if streak is not None and streak.pending_promotion_approval_id == req.id:
        streak.pending_promotion_approval_id = None

    log.info(
        "autonomy_promote.recorded",
        from_level=from_level,
        to_level=to_level,
        approval_rate=snap["approval_rate"],
    )
