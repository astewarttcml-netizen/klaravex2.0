"""
app/services/engagement_tracker.py
───────────────────────────────────
Core logic for cold-outreach engagement tracking (phase3-002).

Three signal sources:
  • open    — tracking pixel hit, via GET /api/v1/track/open/{token}
  • click   — link wrapper hit, via GET /api/v1/track/click/{token}?u={url}
  • reply   — email-provider inbound webhook, via POST /api/v1/webhooks/inbound-reply

The tracker writes timestamps + counters back to ProspectedLead. The
phase3-001 follow-up scheduler reads those fields to suppress further
emails when any signal arrives.

Open dedup: opens within DEDUP_SECONDS of the previous open are dropped
(typical email clients fetch the pixel multiple times within a few
seconds). engagement_count is not incremented on the duplicate hits.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.prospected_lead import ProspectedLead, ProspectedLeadStatus

logger = structlog.get_logger(__name__)

# Dedup window for open events. Email clients (Gmail in particular) routinely
# fetch the pixel several times per render — without this we'd over-count.
DEDUP_SECONDS = 60


def generate_tracking_token() -> str:
    """URL-safe 256-bit random token. ~43 characters."""
    return secrets.token_urlsafe(32)


async def get_prospect_by_token(
    db: AsyncSession, token: str
) -> Optional[ProspectedLead]:
    if not token:
        return None
    result = await db.execute(
        select(ProspectedLead).where(ProspectedLead.tracking_token == token)
    )
    return result.scalar_one_or_none()


async def record_open(
    db: AsyncSession,
    prospect: ProspectedLead,
    now: Optional[datetime] = None,
) -> bool:
    """
    Mark an open. Returns True if recorded, False if deduped within
    DEDUP_SECONDS of the previous open.

    Increments engagement_count only on non-dedup hits.
    """
    now = now or datetime.now(timezone.utc)
    last = prospect.last_opened_at
    if last is not None and (now - last) < timedelta(seconds=DEDUP_SECONDS):
        logger.info(
            "engagement.open_deduped",
            prospect_id=prospect.id,
            elapsed_seconds=(now - last).total_seconds(),
        )
        return False

    if prospect.opened_at is None:
        prospect.opened_at = now
    prospect.last_opened_at = now
    prospect.engagement_count = (prospect.engagement_count or 0) + 1
    await db.flush()
    logger.info("engagement.open_recorded", prospect_id=prospect.id)
    return True


async def record_click(
    db: AsyncSession,
    prospect: ProspectedLead,
    target_url: str,
    now: Optional[datetime] = None,
) -> None:
    """Mark a click. Clicks are not deduped (each is a deliberate action)."""
    now = now or datetime.now(timezone.utc)
    prospect.last_clicked_at = now
    prospect.engagement_count = (prospect.engagement_count or 0) + 1
    # A click is also an implicit open if we never saw an open pixel ping
    # (some clients block external images but allow links).
    if prospect.opened_at is None:
        prospect.opened_at = now
    if prospect.last_opened_at is None:
        prospect.last_opened_at = now
    await db.flush()
    logger.info(
        "engagement.click_recorded",
        prospect_id=prospect.id,
        target_host=target_url.split("/", 3)[2] if "//" in target_url else target_url[:40],
    )


async def record_reply(
    db: AsyncSession,
    prospect: ProspectedLead,
    now: Optional[datetime] = None,
) -> None:
    """Mark a reply received via the email-provider inbound webhook.

    Also advances ProspectedLeadStatus to 'replied' so the lead surfaces in
    the active-conversations view without any extra status transition logic.
    """
    now = now or datetime.now(timezone.utc)
    prospect.replied_at = now
    prospect.status     = ProspectedLeadStatus.replied
    prospect.engagement_count = (prospect.engagement_count or 0) + 1
    await db.flush()
    logger.info("engagement.reply_recorded", prospect_id=prospect.id)


async def record_unsubscribe(
    db: AsyncSession,
    prospect: ProspectedLead,
    now: Optional[datetime] = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    prospect.unsubscribed_at = now
    prospect.engagement_count = (prospect.engagement_count or 0) + 1
    await db.flush()
    logger.info("engagement.unsubscribe_recorded", prospect_id=prospect.id)


# ── Pixel + click wrapper helpers (used by outreach_email.py) ─────────────────

# 1×1 transparent GIF (RFC bytes, ~43 bytes total)
TRANSPARENT_GIF = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00"
    b"\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21"
    b"\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00"
    b"\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44"
    b"\x01\x00\x3b"
)


def pixel_url(base_url: str, token: str) -> str:
    """Construct the open-tracking pixel URL for inclusion in an outbound email."""
    return f"{base_url.rstrip('/')}/api/v1/track/open/{token}"


def wrap_link(base_url: str, token: str, target_url: str) -> str:
    """Wrap a link so clicks hit our redirect endpoint before reaching `target_url`."""
    from urllib.parse import quote
    return (
        f"{base_url.rstrip('/')}/api/v1/track/click/{token}"
        f"?u={quote(target_url, safe='')}"
    )


# Skip rewriting links that point at our own tracking endpoints (already wrapped),
# unsubscribe handlers (must hit the prospect-side path directly), or mailto: links.
_DO_NOT_WRAP = (
    "/api/v1/track/",
    "/api/v1/webhooks/",
    "/unsubscribe",
    "mailto:",
    "tel:",
)


def augment_for_tracking(body_html: str, base_url: str, token: str) -> str:
    """
    Inject the open-tracking pixel and wrap every outbound link in `body_html`
    with the click-tracking redirect.

    Safe to call on any string — if there's no body, no links, or no token, the
    function returns the original input.

    Links matched: every href="http(s)://..." that doesn't already point at our
    tracking endpoints / unsubscribe / mailto / tel.

    Pixel appended: a 1×1 transparent <img> at the very end of the body. If
    body_html doesn't end with </body>, the img is appended raw — most email
    clients tolerate trailing tags. If </body> is present, the img is injected
    just before it (correct nesting).
    """
    if not body_html or not token:
        return body_html or ""

    import re
    from html import escape as _esc

    base = base_url.rstrip("/")

    def _rewrite_href(match: "re.Match[str]") -> str:
        target = match.group(2)
        if any(skip in target for skip in _DO_NOT_WRAP):
            return match.group(0)
        return f'href={match.group(1)}{wrap_link(base, token, target)}{match.group(1)}'

    # Capture quote char so we preserve single vs double quotes
    out = re.sub(
        r'href=(["\'])(https?://[^"\']+)\1',
        _rewrite_href,
        body_html,
    )

    # Pixel — placed before </body> if present, else appended
    pixel = (
        f'<img src="{_esc(pixel_url(base, token))}" '
        f'width="1" height="1" alt="" '
        f'style="display:block;width:1px;height:1px;border:0;" />'
    )
    if "</body>" in out:
        out = out.replace("</body>", pixel + "</body>", 1)
    else:
        out = out + pixel

    return out
