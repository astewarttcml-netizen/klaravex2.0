"""
app/agents/policy_guard.py
──────────────────────────
Policy enforcement gate.

Checks:
  1. Dual GDPR consent — has the user given consent for BOTH German AND English
     data processing? (Phase 3 requirement: consent_de AND consent_en must both
     be true on the Conversation row, regardless of detected language.)
  2. Blocked content — is the input obviously off-topic or harmful?
  3. Minimum message length.

This agent is called by Klara AI before any pipeline that processes PII.
It is a P1 read-only check — it never modifies data itself.

Two consent modes are supported for backward compatibility:

  * Phase 3 mode (preferred): ``context.conversation`` has ``consent_de`` and
    ``consent_en`` attributes (populated by ``context_manager`` from the
    Conversation row).  Both flags must be true.
  * Legacy mode: ``input_data["gdpr_consent"]`` is a single boolean.  Used by
    the HTTP-layer chat path that calls policy_guard before context_manager
    has resolved a Conversation row.
"""
from __future__ import annotations

import structlog

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)

# Topics explicitly outside scope (rough keyword check — LLM-grade filtering
# can be added later via a moderation call to Anthropic).
#
# Each entry is (substring_pattern, canonical_keyword).  The substring is what
# we look for inside the user's lower-cased message; the canonical keyword is
# what we log on a block.  Using stems lets "How do I hack into …" match the
# canonical "hacking" category without over-fitting on -ing endings.
_BLOCKED_KEYWORDS: list[tuple[str, str]] = [
    ("hack", "hacking"),
    ("crack password", "crack password"),
    ("bypass security", "bypass security"),
    ("illegal", "illegal"),
    ("pornography", "pornography"),
    ("gambling", "gambling"),
    ("drug", "drug"),
]


class PolicyGuardAgent(BaseAgent):
    name = "policy_guard"
    description = (
        "GDPR dual-consent check, content filtering, and minimum-length enforcement. "
        "Blocks processing if either consent flag is missing or content is out-of-scope."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        user_message = input_data.get("message", "")

        # ─────────────────────────────────────────────────────────────────────
        # VALIDATION GATE 1: GDPR consent
        # ─────────────────────────────────────────────────────────────────────
        conversation = getattr(context, "conversation", None)
        has_dual_fields = (
            conversation is not None
            and hasattr(conversation, "consent_de")
            and hasattr(conversation, "consent_en")
        )

        if has_dual_fields:
            consent_de = bool(conversation.consent_de)
            consent_en = bool(conversation.consent_en)

            logger.info(
                "consent_validation_check",
                consent_de=consent_de,
                consent_en=consent_en,
                conversation_id=context.conversation_id,
            )

            # German consent is checked first so a German-speaking visitor sees
            # a German-aware error before any English-only message is surfaced.
            if not consent_de:
                logger.info(
                    "policy_guard.dual_consent_blocked_de",
                    conversation_id=context.conversation_id,
                    reason="Missing German GDPR consent (DSGVO)",
                )
                return AgentResult.fail(
                    "German GDPR consent (DSGVO) is required before we can process "
                    "your message. Bitte akzeptieren Sie die Datenschutzerklärung "
                    "auf dem Kontaktformular."
                )

            if not consent_en:
                logger.info(
                    "policy_guard.dual_consent_blocked_en",
                    conversation_id=context.conversation_id,
                    reason="Missing English GDPR consent",
                )
                return AgentResult.fail(
                    "English GDPR consent is required before we can process your "
                    "message. Please accept the privacy policy on the contact form."
                )
        else:
            # Legacy single-flag path: policy_guard called from chat.py at the
            # HTTP layer before context_manager has resolved a Conversation row.
            gdpr_consent = input_data.get("gdpr_consent", False)

            logger.info(
                "consent_validation_check",
                gdpr_consent=gdpr_consent,
                conversation_id=context.conversation_id,
            )

            if not gdpr_consent:
                logger.info(
                    "policy_guard.consent_blocked",
                    conversation_id=context.conversation_id,
                    reason="GDPR consent not given",
                )
                return AgentResult.fail(
                    "GDPR consent is required before we can process your message. "
                    "Please accept the privacy policy on the contact form."
                )

        # ─────────────────────────────────────────────────────────────────────
        # VALIDATION GATE 2: Blocked content (simple keyword scan)
        # ─────────────────────────────────────────────────────────────────────
        lower_msg = user_message.lower()
        for pattern, canonical in _BLOCKED_KEYWORDS:
            if pattern in lower_msg:
                logger.warning(
                    "policy_guard.content_blocked",
                    keyword=canonical,
                    conversation=context.conversation_id,
                )
                return AgentResult.fail(
                    "This topic is outside the scope of Klaravex's services."
                )

        # ─────────────────────────────────────────────────────────────────────
        # VALIDATION GATE 3: Minimum message length
        # ─────────────────────────────────────────────────────────────────────
        if len(user_message.strip()) < 5:
            return AgentResult.fail("Message too short — please describe your IT need.")

        logger.debug("policy_guard.passed", conversation=context.conversation_id)
        return AgentResult.ok(output={"policy_passed": True})
