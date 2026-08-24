"""
app/agents/consent_validation_agent.py
──────────────────────────────────────
Validates dual GDPR consent (consent_de AND consent_en).

Ensures both German and English GDPR consent flags are set on the lead
before proceeding with bilingual outreach. Complies with GDPR/DSGVO.
"""
from __future__ import annotations

import structlog

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.lead import Lead

logger = structlog.get_logger(__name__)


class ConsentValidationAgent(BaseAgent):
    name = "consent_validation_agent"
    description = "Validates dual GDPR consent (consent_de AND consent_en)"
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data keys:
          lead_id (str, required) — lead record to validate
        
        Returns:
          output: {"consent_valid": bool, "consent_de": bool, "consent_en": bool}
        """
        lead_id = input_data.get("lead_id") or context.lead_id
        
        if not lead_id:
            return AgentResult.fail("consent_validation_agent requires lead_id in context or input.")
        
        try:
            from sqlalchemy import select
            
            # Fetch lead record
            stmt = select(Lead).where(Lead.id == lead_id)
            result = await context.db.execute(stmt)
            lead = result.scalars().first()
            
            if not lead:
                return AgentResult.fail(f"Lead {lead_id} not found.")
            
            # Check for dual consent flags
            # Assuming Lead model has gdpr_consent (legacy) and consent_de, consent_en fields
            consent_de = getattr(lead, "consent_de", False)
            consent_en = getattr(lead, "consent_en", False)
            
            # If new fields don't exist, fall back to legacy gdpr_consent
            if not hasattr(lead, "consent_de") or not hasattr(lead, "consent_en"):
                consent_de = consent_en = getattr(lead, "gdpr_consent", False)
            
            consent_valid = consent_de and consent_en
            
            logger.debug(
                "consent_validation.checked",
                lead=lead_id,
                consent_valid=consent_valid,
                consent_de=consent_de,
                consent_en=consent_en,
            )
            
            return AgentResult.ok(output={
                "consent_valid": consent_valid,
                "consent_de": consent_de,
                "consent_en": consent_en,
            })
        
        except Exception as e:
            logger.error("consent_validation.error", error=str(e), lead=lead_id)
            return AgentResult.fail(f"Consent validation failed: {str(e)}")
