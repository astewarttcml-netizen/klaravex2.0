"""
app/agents/context_manager.py
──────────────────────────────
Loads or creates conversation context before any pipeline runs.

Responsibilities:
  - Resolve session_token → Conversation row (or create one)
  - Load recent message history for the LLM context window
  - Attach lead_id to context if already known
"""
from __future__ import annotations

import structlog
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.conversation import Conversation, Message

logger = structlog.get_logger(__name__)


class ContextManagerAgent(BaseAgent):
    name = "context_manager"
    description = (
        "Resolves or creates a Conversation record and loads message history "
        "into the shared context before other agents run."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        session_token = input_data.get("session_token")
        if not session_token:
            return AgentResult.fail("context_manager requires 'session_token' in input.")

        db = context.db

        # Try to load existing conversation
        result = await db.execute(
            select(Conversation).where(Conversation.session_token == session_token)
        )
        convo = result.scalar_one_or_none()

        gdpr_consent = input_data.get("gdpr_consent", False)

        if not convo:
            convo = Conversation(
                session_token=session_token,
                channel=input_data.get("channel", "chat"),
                # Persist consent flags so the Conversation row reflects the
                # consent status given at the HTTP layer.  policy_guard already
                # validated these before context_manager runs.
                consent_de=gdpr_consent,
                consent_en=gdpr_consent,
            )
            db.add(convo)
            await db.flush()
            logger.info("context_manager.created_conversation", convo_id=convo.id)
        else:
            # On subsequent messages, upgrade consent if not already set.
            if gdpr_consent and (not convo.consent_de or not convo.consent_en):
                convo.consent_de = True
                convo.consent_en = True
                await db.flush()
            logger.debug("context_manager.loaded_conversation", convo_id=convo.id)

        # Attach conversation and lead to context
        context.conversation_id = convo.id
        if convo.lead_id:
            context.lead_id = convo.lead_id

        # Load last N messages for LLM context
        history_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == convo.id)
            .order_by(Message.created_at.desc())
            .limit(20)
        )
        messages = list(reversed(history_result.scalars().all()))

        history = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

        return AgentResult.ok(output={"conversation_id": convo.id, "history": history})
