"""
app/agents/crm_integration.py
─────────────────────────────
CRM Integration Builder (Agent 21 — CRM)

Pushes approved leads and account updates into CRM/task systems.

Permission level: P3 (outbound — posts data to an external CRM endpoint)

Supported modes:
  webhook — POST JSON payload to CRM_WEBHOOK_URL (Zapier, Make, HubSpot,
            Pipedrive, Notion, etc.)
  export  — Write structured JSON to /opt/loki-agents/data/crm_export/
            for manual import or downstream processing

If CRM_WEBHOOK_URL is not set, falls back to export automatically.

Blocked: pushing leads in status new / disqualified / lost / anonymised.
Fallback: if webhook fails, falls back to export and logs the failure.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import structlog
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

_EXPORT_DIR = Path("/opt/loki-agents/data/crm_export")

# Only push leads that have real sales value
# LeadStatus values: new, qualified, disqualified, discovery_done,
# proposal_sent, won, lost, anonymised
_PUSHABLE_STATUSES = {
    LeadStatus.qualified.value,
    LeadStatus.discovery_done.value,
    LeadStatus.proposal_sent.value,
    LeadStatus.won.value,
}


class CrmIntegrationAgent(BaseAgent):
    """
    Pushes approved lead data to an external CRM or exports a structured JSON
    record for manual import.

    Configured via CRM_WEBHOOK_URL env var:
      - Set     → POSTs sanitised lead payload (P3 — outbound)
      - Not set → writes to /data/crm_export/<lead_id>.json

    On webhook failure: falls back to export mode transparently.
    """

    name = "crm_integration"
    description = (
        "Pushes approved leads to an external CRM via webhook or exports a "
        "structured JSON record for manual import."
    )
    permission_level = PermissionLevel.P3

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        lead_id = input_data.get("lead_id") or (
            str(context.lead_id) if context.lead_id else ""
        )
        if not lead_id:
            return AgentResult.fail("crm_integration requires 'lead_id'.")

        note = input_data.get("note", "")
        mode_override = input_data.get("mode")  # "webhook" | "export" | None

        result = await context.db.execute(
            select(Lead).where(Lead.id == lead_id)
        )
        lead: Lead | None = result.scalar_one_or_none()

        if not lead:
            return AgentResult.fail(f"Lead {lead_id} not found.")

        if lead.status not in _PUSHABLE_STATUSES:
            log.warning(
                "crm_integration.blocked_status",
                lead_id=lead_id,
                status=lead.status,
            )
            return AgentResult.fail(
                f"Lead status '{lead.status}' is not eligible for CRM push. "
                "Only HOT/WARM/qualified/discovery_done/proposal_sent/won "
                "leads may be synced."
            )

        payload = self._build_payload(lead, note)
        webhook_url = os.getenv("CRM_WEBHOOK_URL", "").strip()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Determine mode
        if mode_override:
            mode = mode_override
        elif webhook_url:
            mode = "webhook"
        else:
            mode = "export"

        if mode == "webhook" and webhook_url:
            success = await self._post_webhook(webhook_url, payload, log)
            if not success:
                log.warning(
                    "crm_integration.webhook_failed_fallback",
                    lead_id=lead_id,
                )
                mode = "export"

        if mode == "export":
            self._write_export(lead_id, payload)

        log.info(
            "crm_integration.synced",
            lead_id=lead_id,
            mode=mode,
            status=lead.status,
        )

        return AgentResult.ok(
            output={
                "crm_mode": mode,
                "lead_id": lead_id,
                "exported_at": now_iso,
                "status": lead.status,
                "company": lead.company_name,
            }
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_payload(self, lead: Lead, note: str) -> dict:
        """Sanitised, CRM-friendly lead payload."""
        return {
            "source": "loki_crm_integration",
            "lead_id": str(lead.id),
            "name": lead.name,
            "email": lead.email,
            "phone": getattr(lead, "phone", None),
            "company": lead.company_name,
            "status": lead.status,
            "service_interest": lead.service_interest,
            "message": lead.message,
            "score": lead.score,
            "created_at": (
                lead.created_at.isoformat() if lead.created_at else None
            ),
            "updated_at": (
                lead.updated_at.isoformat() if lead.updated_at else None
            ),
            "note": note,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _post_webhook(
        self,
        url: str,
        payload: dict,
        log,
    ) -> bool:
        """POST payload to CRM webhook. Returns True on 2xx."""
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Klara AI-CRM-Integration/1.0",
                    },
                ) as resp:
                    ok = 200 <= resp.status < 300
                    log.info(
                        "crm_integration.webhook_response",
                        status=resp.status,
                        ok=ok,
                    )
                    return ok
        except Exception as exc:
            log.error("crm_integration.webhook_error", error=str(exc))
            return False

    def _write_export(self, lead_id: str, payload: dict) -> None:
        """Write payload to /data/crm_export/<lead_id>.json."""
        _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = _EXPORT_DIR / f"{lead_id}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info("crm_integration.exported", path=str(path))
