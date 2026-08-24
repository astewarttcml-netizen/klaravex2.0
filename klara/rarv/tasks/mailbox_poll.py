"""
app/tasks/mailbox_poll.py
──────────────────────────
Klaravex mailbox polling task.

Polls the support@klaravex.com shared mailbox via Microsoft Graph API
every 2 minutes, processes each unread message through the inbound_email
agent, marks it read when done.

Requires env vars (in .env.klaravex):
  SUPPORT_MAILBOX      — e.g. support@klaravex.com
  MS_GRAPH_TENANT_ID
  MS_GRAPH_CLIENT_ID
  MS_GRAPH_CLIENT_SECRET
"""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import structlog
from celery import shared_task

from app.agents.base import AgentContext
from app.agents.registry import registry
from app.config import get_settings
from app.database import db_context
from app.models.inbound_email import InboundEmail

logger = structlog.get_logger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_MSG_FIELDS = "id,from,toRecipients,subject,body,receivedDateTime"
_PAGE_SIZE = 20


@shared_task(
    bind=True,
    name="app.tasks.mailbox_poll.poll_support_mailbox",
    max_retries=2,
    default_retry_delay=60,
)
def poll_support_mailbox(self):
    """Celery entry point — polls the shared mailbox once per call."""
    try:
        result = asyncio.run(_poll())
        logger.info("mailbox_poll.complete", **result)
        return result
    except Exception as exc:
        logger.error("mailbox_poll.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _poll() -> dict:
    settings = get_settings()

    mailbox = settings.support_mailbox
    if not mailbox:
        return {"skipped": True, "reason": "SUPPORT_MAILBOX not configured"}

    if not settings.ms_graph_configured:
        return {"skipped": True, "reason": "MS Graph credentials not configured"}

    token = await _get_token(settings)
    messages = await _fetch_unread(token, mailbox)

    processed = 0
    errors = 0
    for msg in messages:
        try:
            await _handle_message(settings, token, mailbox, msg)
            processed += 1
        except Exception as exc:
            logger.error("mailbox_poll.message_failed", msg_id=msg.get("id"), error=str(exc))
            errors += 1

    return {"processed": processed, "errors": errors, "mailbox": mailbox}


async def _get_token(settings) -> str:
    url = f"https://login.microsoftonline.com/{settings.ms_graph_tenant_id}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, data={
            "grant_type": "client_credentials",
            "client_id": settings.ms_graph_client_id,
            "client_secret": settings.ms_graph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
        })
        r.raise_for_status()
        return r.json()["access_token"]


async def _fetch_unread(token: str, mailbox: str) -> list[dict]:
    url = (
        f"{_GRAPH_BASE}/users/{mailbox}/mailFolders/Inbox/messages"
        f"?$filter=isRead eq false&$select={_MSG_FIELDS}&$top={_PAGE_SIZE}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json().get("value", [])


async def _handle_message(settings, token: str, mailbox: str, msg: dict) -> None:
    msg_id = msg["id"]
    from_email = (msg.get("from") or {}).get("emailAddress", {}).get("address", "").lower()
    to_email = mailbox.lower()
    subject = (msg.get("subject") or "")[:500]

    body_obj = msg.get("body") or {}
    body_text = body_obj.get("content", "")
    if body_obj.get("contentType", "").lower() == "html":
        # Strip HTML tags for plain-text storage
        import re
        body_text = re.sub(r"<[^>]+>", " ", body_text)
        body_text = re.sub(r"\s+", " ", body_text).strip()

    raw_payload = json.dumps(msg, ensure_ascii=False)[:100_000]

    classification: dict | None = None
    async with db_context() as db:
        row = InboundEmail(
            id=str(uuid4()),
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            body=body_text[:50_000],
            raw_payload=raw_payload,
        )
        db.add(row)
        await db.flush()

        try:
            agent = registry.get("inbound_email")
            ctx = AgentContext(db=db, settings=settings)
            result = await agent.run(ctx, {"inbound_email_id": row.id})
            if result.success:
                classification = result.output
            else:
                logger.warning("mailbox_poll.classification_failed", email_id=row.id, error=result.error)
        except Exception as exc:
            logger.error("mailbox_poll.classification_exception", error=str(exc))

        if classification and classification.get("category"):
            try:
                from app.services.inbound_router import route_inbound
                await route_inbound(db, row, classification)
            except Exception as exc:
                logger.error("mailbox_poll.route_exception", error=str(exc))

        await db.commit()

    # Mark as read regardless of classification outcome so we don't reprocess
    await _mark_read(token, mailbox, msg_id)
    logger.info("mailbox_poll.message_processed", msg_id=msg_id, from_email=from_email)


async def _mark_read(token: str, mailbox: str, msg_id: str) -> None:
    url = f"{_GRAPH_BASE}/users/{mailbox}/messages/{msg_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.patch(url, headers=headers, json={"isRead": True})
        if r.status_code not in (200, 204):
            logger.warning("mailbox_poll.mark_read_failed", msg_id=msg_id, status=r.status_code)
