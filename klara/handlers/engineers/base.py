"""Base class for all 4 Klaravex engineer agents.

An engineer's job: take a ticket (or open project) in their specialty, reason
about the next-best concrete deliverable, draft it, and queue it for Anthony's
approval. On approve, the artifact is delivered to the client OR executed.
"""

import json
import logging
import os
import re
import secrets
from typing import Any, Optional

from ..lib.db import get_pool
from .openclaw_client import (
    HttpxOpenClawClient,
    OpenClawClient,
    OpenClawDecodeError,
    OpenClawError,
    OpenClawHTTPError,
    OpenClawTimeoutError,
    OpenClawTransportError,
)

log = logging.getLogger("klaravex.engineers")

OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://localhost:8420")


class EngineerAgent:
    name: str = "engineer_base"
    display_name: str = "Engineer"
    pillar: str = ""
    website_anchor: str = ""
    expertise: str = ""
    system_prompt: str = ""
    specialty_keywords: list[str] = []
    secondary_keywords: list[str] = []
    default_skus: list[str] = []
    first_deliverable_prompt: str = ""
    documentation_targets: list[str] = []
    backup_pillars: list[str] = []

    def __init__(self, *, openclaw_client: Optional[OpenClawClient] = None) -> None:
        self._openclaw_client: OpenClawClient = openclaw_client or HttpxOpenClawClient(OPENCLAW_URL)

    async def reason_about_ticket(self, ticket: dict[str, Any]) -> dict[str, Any]:
        prompt = self._build_ticket_prompt(ticket)
        return await self._call_openclaw(prompt, fallback_title=ticket.get("subject", "Ticket response"))

    async def first_playbook(self) -> dict[str, Any]:
        prompt = self.first_deliverable_prompt or self._default_playbook_prompt()
        return await self._call_openclaw(prompt, fallback_title=f"{self.display_name} Service Playbook")

    async def first_gap_analysis(self, *, website_pillar_copy: str = "") -> dict[str, Any]:
        prompt = self._gap_analysis_prompt(website_pillar_copy)
        return await self._call_openclaw(
            prompt,
            fallback_title=f"{self.display_name} — Pillar Gap Analysis",
        )

    async def produce_documentation(
        self,
        *,
        doc_target: str,
        gap_context: str = "",
    ) -> dict[str, Any]:
        prompt = self._documentation_prompt(doc_target, gap_context)
        return await self._call_openclaw(
            prompt,
            fallback_title=f"{self.display_name} — {doc_target}",
        )

    async def _call_openclaw(self, prompt: str, *, fallback_title: str = "Engineer action") -> dict[str, Any]:
        payload = {
            "engineer": self.name,
            "prompt": prompt,
            "system_prompt": self.system_prompt,
            "fallback_title": fallback_title,
        }
        try:
            data = await self._openclaw_client.reason(payload)
        except OpenClawTimeoutError as exc:
            return self._error_fallback(fallback_title, exc, error_type="timeout")
        except OpenClawHTTPError as exc:
            return self._error_fallback(
                fallback_title, exc, error_type="http_status", error_status=exc.status_code
            )
        except OpenClawDecodeError as exc:
            return self._error_fallback(fallback_title, exc, error_type="decode")
        except OpenClawTransportError as exc:
            return self._error_fallback(fallback_title, exc, error_type="transport")
        except OpenClawError as exc:
            # Future OpenClaw* subclasses fall here rather than the bare Exception catch.
            return self._error_fallback(fallback_title, exc, error_type="unknown")
        except Exception as exc:
            # Truly unexpected failure (client implementation bug). Surface it for retry policy
            # but do not propagate — the engineer reasoning loop must remain non-fatal.
            log.exception("openclaw client raised non-OpenClawError: %s", exc)
            return self._error_fallback(fallback_title, exc, error_type="unknown")

        return {
            "action_type": data.get("action_type", "investigation_plan"),
            "title": data.get("title", fallback_title),
            "body_markdown": data.get("body_markdown", ""),
            "proposed_payload": data.get("proposed_payload", {}),
            "reasoning": data.get("reasoning", ""),
        }

    def _error_fallback(
        self,
        fallback_title: str,
        exc: BaseException,
        *,
        error_type: str,
        error_status: Optional[int] = None,
    ) -> dict[str, Any]:
        """Build the structured fallback dict for an OpenClaw failure.

        error_type is the classification a retry supervisor / dashboard / alert
        pipeline branches on. Lossy collapse into a single 'investigation_plan'
        shape (the pre-iter-3 behaviour) is what review-20260618T175105Z-2
        High [2] flagged; keep error_type distinct per branch.
        """
        log.warning("openclaw %s error: %s", error_type, exc)
        payload: dict[str, Any] = {"error_type": error_type}
        if error_status is not None:
            payload["error_status"] = error_status
        return {
            "action_type": "investigation_plan",
            "title": fallback_title,
            "body_markdown": f"OpenClaw error: {exc}",
            "proposed_payload": payload,
            "reasoning": f"Agent failed: {exc}",
            "error_type": error_type,
        }

    def _build_ticket_prompt(self, ticket: dict[str, Any]) -> str:
        return f"""
{self.system_prompt}

You are reviewing this open ticket as the {self.display_name}:

  Ticket ID:    {ticket.get('id')}
  Severity:     {ticket.get('severity')}
  Source:       {ticket.get('source')}
  SKU:          {ticket.get('sku') or 'unspecified'}
  Subject:      {ticket.get('subject')}
  Summary:      {ticket.get('summary') or '(no summary)'}
  Created:      {ticket.get('created_at')}

Produce a structured next-action proposal. Output ONLY a valid JSON object with this shape:
{{
  "action_type": "one of: investigation_plan | client_reply | playbook | documentation | escalation",
  "title": "short human-readable title (<80 chars)",
  "body_markdown": "the deliverable content in Markdown — the actual reply / plan / doc body",
  "proposed_payload": {{
    "to": "recipient if action_type is client_reply, else omit",
    "subject": "subject line if client_reply, else omit",
    "doc_target": "documentation target if action_type is documentation, else omit",
    "next_steps": ["array of concrete next steps for the operator"]
  }},
  "reasoning": "1-3 sentences on why this action is the next-best move"
}}

Do not include prose before or after the JSON object.
""".strip()

    def _gap_analysis_prompt(self, website_pillar_copy: str = "") -> str:
        if website_pillar_copy:
            return f"""
Analyze gaps between our website claims and our actual capabilities:

Website Claims:
{website_pillar_copy.strip()}

Your {self.display_name} Perspective:
""".strip()
        return f"""
Analyze our current {self.display_name} capabilities and identify the biggest gaps.
""".strip()

    def _documentation_prompt(self, doc_target: str, gap_context: str = "") -> str:
        return f"""
Create documentation for: {doc_target}
{gap_context}
""".strip()

    def _default_playbook_prompt(self) -> str:
        return f"""
Create a standard playbook for {self.display_name} services.
Include:
- Common scenarios
- Step-by-step procedures
- Role-specific best practices
""".strip()

    async def queue_action(
        self,
        *,
        action: dict[str, Any],
        ticket_id: Optional[str] = None,
        project_id: Optional[str] = None,
        client_email: Optional[str] = None,
    ) -> str:
        approval_token = secrets.token_hex(16)
        pool = await get_pool()
        async with pool.acquire() as conn:
            action_id = await conn.fetchval(
                """
                INSERT INTO klaravex_engineer_actions
                  (engineer, pillar, ticket_id, project_id, client_email,
                   action_type, title, body_markdown, proposed_payload,
                   reasoning, approval_token)
                VALUES ($1, $2, $3::uuid, $4::uuid, $5, $6, $7, $8, $9::jsonb, $10, $11)
                RETURNING id::text
                """,
                self.name,
                self.pillar or None,
                ticket_id,
                project_id,
                client_email,
                action.get("action_type") or "investigation_plan",
                action.get("title") or "Untitled",
                action.get("body_markdown") or "",
                json.dumps(action.get("proposed_payload") or {}),
                action.get("reasoning"),
                approval_token,
            )
            return action_id

    def matches_ticket(self, ticket: dict[str, Any]) -> int:
        # Real tickets carry subject + summary + sku (see dispatch_open_tickets
        # SELECT in dispatcher.py); voice routing builds a synthetic ticket
        # from the spoken question's subject field. Reading only `keywords`
        # left every score at 0 and collapsed every dispatch to the
        # strategic_advisory fallback. Concatenate every text field we
        # plausibly know about so a keyword in any of them scores.
        # `keywords` keeps its strict-string contract (non-string raises
        # AttributeError, locked by test_non_string_keywords_raises_attribute_error);
        # subject/summary/sku are tolerant because real DB rows can return None.
        haystack_parts = [ticket.get('keywords', '').lower()]
        for field in ('subject', 'summary', 'sku'):
            value = ticket.get(field)
            if isinstance(value, str):
                haystack_parts.append(value.lower())
        haystack = ' '.join(haystack_parts)
        score = 0
        for kw in self.specialty_keywords:
            if kw.lower() in haystack:
                score += 5
        for kw in self.secondary_keywords:
            if kw.lower() in haystack:
                score += 1
        return score
