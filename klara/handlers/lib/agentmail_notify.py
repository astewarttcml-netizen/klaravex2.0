"""AgentMail internal notification helper — M8.

Sends internal email notifications to the 9 ai.klaravex.com agent inboxes
so Phase 12 B2B squad events land in the right AgentMail box.

Usage::

    from .agentmail_notify import notify_agent_inbox

    # Pre-brief → workflow inbox
    await notify_agent_inbox("workflow", subject, body)

    # biz_engineer advice note → routed engineer's inbox
    await notify_agent_inbox(pillar_to_agentmail_inbox("regulatory_readiness"), subject, body)

The helper is best-effort: failures are logged and swallowed so the
caller's primary flow is never blocked by mailbox delivery.
"""

import logging
import os
from typing import Mapping

from .email import send_email

log = logging.getLogger("klaravex.agentmail_notify")

AGENTMAIL_DOMAIN = os.environ.get("AGENTMAIL_DOMAIN", "ai.klaravex.com")

# ── Engineer pillar → AgentMail local-part mapping ────────────────────────────
# Derived from the 9 known inboxes in agentmail_webhook.py and the 6 engineer
# pillar names in engineers/dispatcher.py.
#
#   regulatory_readiness  → lex   (Compliance Engineer)
#   strategic_advisory    → atlas (Strategy & vCIO)
#   microsoft_365         → echo  (Microsoft 365 & Cloud Engineer)
#   ai_adoption           → iris  (AI Adoption Engineer)
#   managed_security      → cipher(Security Engineer)
#   infrastructure_support→ cipher(closest match: Security/Infra; no dedicated inbox)
#
_PILLAR_TO_INBOX: Mapping[str, str] = {
    "regulatory_readiness":   "lex",
    "strategic_advisory":     "atlas",
    "microsoft_365":          "echo",
    "ai_adoption":            "iris",
    "managed_security":       "cipher",
    "infrastructure_support": "cipher",
}


def pillar_to_agentmail_inbox(pillar: str) -> str:
    """Return the AgentMail local-part for a given engineer pillar.

    Falls back to "workflow" when the pillar is unknown so the message is
    queued for manual review rather than silently dropped.
    """
    return _PILLAR_TO_INBOX.get(pillar, "workflow")


def _inbox_address(local_part: str) -> str:
    return f"{local_part}@{AGENTMAIL_DOMAIN}"


async def notify_agent_inbox(
    inbox: str,
    subject: str,
    body: str,
    *,
    html: str | None = None,
) -> None:
    """Send an internal notification email to an AgentMail inbox.

    ``inbox`` is either a bare local-part (e.g. "workflow") or a full
    address (e.g. "workflow@ai.klaravex.com").  If it already contains
    "@" it is used as-is; otherwise the AGENTMAIL_DOMAIN is appended.

    Never raises — best-effort delivery. The caller must not depend on
    delivery for correctness.
    """
    address = inbox if "@" in inbox else _inbox_address(inbox)
    try:
        await send_email(to=address, subject=subject, body=body, html=html)
        log.info("agentmail_notify: sent to=%s subject=%r", address, subject[:80])
    except Exception as exc:  # noqa: BLE001
        log.warning("agentmail_notify: failed to=%s: %s", address, exc)
