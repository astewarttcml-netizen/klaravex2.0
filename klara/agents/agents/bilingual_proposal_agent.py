"""
app/agents/bilingual_proposal_agent.py
──────────────────────────────────────
Generates bilingual proposals (DE + EN) for qualified leads.

Creates German and English proposal documents from lead and scope data.
Requires P4 manager approval before sending. Integrates with proposal_drafting
pipeline for dual-language delivery.
"""
from __future__ import annotations

import structlog

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)


class BilingualProposalAgent(BaseAgent):
    name = "bilingual_proposal_agent"
    description = "Generates bilingual proposals (DE + EN) for qualified leads"
    permission_level = PermissionLevel.P4

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data keys:
          lead_id    (str, required)  — target lead
          scope      (str)            — service scope / project description
          languages  (list)           — ["de", "en"] or ["de"] or ["en"]
          pricing    (dict)           — pricing tier, total, currency
        
        Returns:
          output: {
            "proposal_id": str,
            "proposal_de": str (markdown),
            "proposal_en": str (markdown),
            "languages_generated": list,
            "approval_required": bool
          }
        """
        lead_id = input_data.get("lead_id") or context.lead_id
        scope = input_data.get("scope")
        languages = input_data.get("languages", ["de", "en"])
        pricing = input_data.get("pricing", {})
        
        if not lead_id:
            return AgentResult.fail("bilingual_proposal_agent requires lead_id.")
        
        if not scope:
            return AgentResult.fail("bilingual_proposal_agent requires scope.")
        
        try:
            from sqlalchemy import select
            from app.models.lead import Lead
            
            # Fetch lead
            stmt = select(Lead).where(Lead.id == lead_id)
            result = await context.db.execute(stmt)
            lead = result.scalars().first()
            
            if not lead:
                return AgentResult.fail(f"Lead {lead_id} not found.")
            
            # Placeholder: actual proposal generation would happen here
            # In real implementation, this would call Claude to generate bilingual proposals
            
            proposal_id = f"prop_{lead_id}"
            proposal_de = f"# Proposal (Deutsch)\n\nScope: {scope}\nLead: {lead.name or 'Unknown'}"
            proposal_en = f"# Proposal (English)\n\nScope: {scope}\nLead: {lead.name or 'Unknown'}"
            
            languages_generated = languages if languages else ["de", "en"]
            
            logger.debug(
                "bilingual_proposal.generated",
                proposal_id=proposal_id,
                lead=lead_id,
                languages=languages_generated,
            )
            
            return AgentResult.ok(output={
                "proposal_id": proposal_id,
                "proposal_de": proposal_de,
                "proposal_en": proposal_en,
                "languages_generated": languages_generated,
                "approval_required": True,
            })
        
        except Exception as e:
            logger.error("bilingual_proposal.error", error=str(e), lead=lead_id)
            return AgentResult.fail(f"Bilingual proposal generation failed: {str(e)}")
