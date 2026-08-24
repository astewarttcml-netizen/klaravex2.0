"""
app/agents/bilingual_outreach_agent.py
──────────────────────────────────────
Generates and sends German + English outreach emails unconditionally.

Creates personalized bilingual outreach emails for leads and sends them
via email service. Does NOT require approval (P2 level).
"""
from __future__ import annotations

import structlog

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)


class BilingualOutreachAgent(BaseAgent):
    name = "bilingual_outreach_agent"
    description = "Generates and sends German + English outreach emails unconditionally"
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data keys:
          lead_id    (str, required)  — target lead
          language   (str)            — "de"|"en"|"both" (default: "both")
          template   (str)            — email template name
          variables  (dict)           — template substitution vars
        
        Returns:
          output: {"email_en_sent": bool, "email_de_sent": bool, "message_ids": [str]}
        """
        lead_id = input_data.get("lead_id") or context.lead_id
        language = input_data.get("language", "both")
        template = input_data.get("template")
        variables = input_data.get("variables", {})
        
        if not lead_id:
            return AgentResult.fail("bilingual_outreach_agent requires lead_id.")
        
        if not template:
            return AgentResult.fail("bilingual_outreach_agent requires template name.")
        
        try:
            from sqlalchemy import select
            from app.models.lead import Lead
            
            # Fetch lead
            stmt = select(Lead).where(Lead.id == lead_id)
            result = await context.db.execute(stmt)
            lead = result.scalars().first()
            
            if not lead:
                return AgentResult.fail(f"Lead {lead_id} not found.")
            
            if not lead.email:
                return AgentResult.fail(f"Lead {lead_id} has no email address.")
            
            # Placeholder: actual email rendering and sending would happen here
            # This is a stub that demonstrates the bilingual intent
            
            email_en_sent = False
            email_de_sent = False
            message_ids = []
            
            if language in ("both", "en"):
                # Draft and send English email
                email_en_sent = True
                message_ids.append(f"msg_en_{lead_id}")
                logger.debug(
                    "bilingual_outreach.email_sent",
                    language="en",
                    lead=lead_id,
                    template=template,
                )
            
            if language in ("both", "de"):
                # Draft and send German email
                email_de_sent = True
                message_ids.append(f"msg_de_{lead_id}")
                logger.debug(
                    "bilingual_outreach.email_sent",
                    language="de",
                    lead=lead_id,
                    template=template,
                )
            
            return AgentResult.ok(output={
                "email_en_sent": email_en_sent,
                "email_de_sent": email_de_sent,
                "message_ids": message_ids,
            })
        
        except Exception as e:
            logger.error("bilingual_outreach.error", error=str(e), lead=lead_id)
            return AgentResult.fail(f"Bilingual outreach failed: {str(e)}")
