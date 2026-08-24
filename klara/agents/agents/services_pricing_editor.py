"""
app/agents/services_pricing_editor.py
──────────────────────────────────────
Services / Pricing Editor (Agent 28 — SERV)

Drafts revised copy and redlines for service pages and pricing sections.
P4 permission: all output is queued as ApprovalRequest — pricing changes
are legal/billing territory and must be reviewed before publishing.

Actions:
  draft    — Generate revised copy for a named section (EN or DE)
  critique — Return specific critique of current copy without rewriting
  redline  — Produce a tracked-change diff suggestion for existing copy

Sections: services_overview, service_azure, service_m365, service_network,
          service_security, service_support, pricing_overview,
          pricing_cards, pricing_faq

Blocked: changing live price values without approval; publishing directly.
Fallback: save output as P4 ApprovalRequest only.
"""
from __future__ import annotations

import json

import structlog
from anthropic import AsyncAnthropic

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)

_VALID_SECTIONS = {
    "services_overview",
    "service_azure",
    "service_m365",
    "service_network",
    "service_security",
    "service_support",
    "pricing_overview",
    "pricing_cards",
    "pricing_faq",
}

_SECTION_CONTEXT = {
    "services_overview": "Services landing page — intro paragraph + service card grid",
    "service_azure": "Azure & Microsoft 365 service detail page — scope, deliverables, ideal client",
    "service_m365": "Microsoft 365 migration and management service detail",
    "service_network": "Network security and Meraki/SDN service detail",
    "service_security": "Cybersecurity assessment and hardening service detail",
    "service_support": "Ongoing IT support retainer / managed service offering",
    "pricing_overview": "Pricing philosophy paragraph — value-based, transparent, no surprise fees",
    "pricing_cards": "3–4 pricing tier cards (tier name + description + price placeholder + features)",
    "pricing_faq": "4–6 pricing FAQ items addressing common objections",
}

_BRAND_BRIEF = """
Business: Klaravex — freelance IT consulting for expats and international businesses.
Owner: Anthony Stewart (British, based in Berlin).
Audience: English-speaking expats + international companies needing enterprise-grade IT in Berlin.
Tone: Authoritative, direct, reassuring. NOT startup-casual or over-enthusiastic.
Differentiators: Enterprise pedigree (Merrill Lynch, World Bank, FDH Aero), Berlin-based, bilingual EN/DE.
Key services: Azure/Microsoft 365, Entra ID, Intune, network security, IT support contracts.
Pricing principle: Never fabricate specific prices. Use placeholders like [PRICE] or "from €X/month".
"""

_PRICING_GUARD = (
    "IMPORTANT: Do NOT invent specific prices. "
    "Use placeholders like [RATE], [PRICE], 'from €X/month', or 'contact for pricing'. "
    "Actual rates will be filled in by Anthony before publishing."
)


class ServicesPricingEditorAgent(BaseAgent):
    name = "services_pricing_editor"
    description = (
        "Drafts and redlines service page and pricing copy for klaravex.de. "
        "All output is queued as a P4 ApprovalRequest — never publishes directly."
    )
    permission_level = PermissionLevel.P4

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        action = input_data.get("action", "draft")
        section = input_data.get("section", "").strip().lower()
        target_lang = input_data.get("target_lang", "en").lower()
        instruction = input_data.get("instruction", "").strip()

        if section not in _VALID_SECTIONS:
            return AgentResult.fail(
                f"Unknown section '{section}'. Valid: {sorted(_VALID_SECTIONS)}"
            )
        if target_lang not in ("en", "de"):
            return AgentResult.fail("target_lang must be 'en' or 'de'")

        log.info("services_pricing_editor.start", action=action, section=section, lang=target_lang)

        if action == "draft":
            return await self._draft(context, section, target_lang, instruction, log)
        elif action == "critique":
            return await self._critique(context, section, target_lang, instruction, log)
        elif action == "redline":
            return await self._redline(context, section, target_lang, instruction, log)
        else:
            return AgentResult.fail(
                f"Unknown action '{action}'. Valid: draft, critique, redline"
            )

    # ── Draft ─────────────────────────────────────────────────────────────────

    async def _draft(
        self, context: AgentContext, section: str, lang: str, instruction: str, log
    ) -> AgentResult:
        section_ctx = _SECTION_CONTEXT.get(section, "")
        is_pricing = section.startswith("pricing")
        lang_note = (
            "Write in formal English for international B2B audiences."
            if lang == "en"
            else "Write in formal German (Sie-form) for B2B audiences. Idiomatic, not literal."
        )

        prompt = f"""You are a B2B copywriter for an IT consulting firm in Berlin.

Brand brief:
{_BRAND_BRIEF}

Your task: Draft revised copy for the **{section}** section of the website.
Section context: {section_ctx}
Language: {lang.upper()} — {lang_note}
{"Additional instruction: " + instruction if instruction else ""}
{_PRICING_GUARD if is_pricing else ""}

Requirements:
- Match the authoritative, direct tone
- Highlight enterprise pedigree and Berlin-based advantage
- Keep copy concise and scannable (this is a web page, not a document)
- If writing DE, use "Sie" throughout
- {"Use price placeholders only — never invent specific rates" if is_pricing else "Focus on outcomes and enterprise credibility"}
- Return the copy ONLY — no explanation, no markdown headers"""

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            msg = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=900,
                messages=[{"role": "user", "content": prompt}],
            )
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=msg,
            )
            draft_copy = msg.content[0].text.strip()
        except Exception as exc:
            log.error("services_pricing_editor.claude_error", error=str(exc))
            return AgentResult.fail(f"services_pricing_editor: Claude error — {exc}")

        payload = {
            "section": section,
            "target_lang": lang,
            "instruction": instruction,
            "draft_copy": draft_copy,
            "is_pricing": is_pricing,
        }

        return await self._queue_approval(context, section, lang, payload, "draft", log)

    # ── Critique ──────────────────────────────────────────────────────────────

    async def _critique(
        self, context: AgentContext, section: str, lang: str, instruction: str, log
    ) -> AgentResult:
        current_copy = instruction or "(no copy provided — supply current copy in 'instruction')"
        is_pricing = section.startswith("pricing")
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        try:
            msg = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=700,
                messages=[{"role": "user", "content": (
                    f"Brand brief:\n{_BRAND_BRIEF}\n\n"
                    f"Critique this {section} section copy ({lang.upper()}):\n\n"
                    f"{current_copy}\n\n"
                    f"{'Pay attention to: no specific prices should appear — use placeholders. ' if is_pricing else ''}"
                    "Give 3–5 specific, actionable improvements. Be direct and concise."
                )}],
            )
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=msg,
            )
            critique = msg.content[0].text.strip()
        except Exception as exc:
            return AgentResult.fail(f"services_pricing_editor.critique: Claude error — {exc}")

        log.info("services_pricing_editor.critique_complete", section=section)
        # Critique is read-only — no approval needed
        return AgentResult.ok(output={"section": section, "lang": lang, "critique": critique})

    # ── Redline ───────────────────────────────────────────────────────────────

    async def _redline(
        self, context: AgentContext, section: str, lang: str, instruction: str, log
    ) -> AgentResult:
        current_copy = instruction or "(no copy provided — supply current copy in 'instruction')"
        is_pricing = section.startswith("pricing")
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        prompt = (
            f"Brand brief:\n{_BRAND_BRIEF}\n\n"
            f"Produce a redlined suggestion for this {section} section copy ({lang.upper()}).\n\n"
            f"CURRENT COPY:\n{current_copy}\n\n"
            f"{'RULE: Never introduce specific prices — use placeholders only. ' if is_pricing else ''}"
            "Format: show ORIGINAL lines (prefix ~~) and SUGGESTED replacements (prefix +) "
            "for each change. Keep unchanged lines as-is. Be surgical — minimal diff."
        )

        try:
            msg = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=msg,
            )
            redline = msg.content[0].text.strip()
        except Exception as exc:
            return AgentResult.fail(f"services_pricing_editor.redline: Claude error — {exc}")

        payload = {
            "section": section,
            "target_lang": lang,
            "original_copy": instruction,
            "redline": redline,
            "is_pricing": is_pricing,
        }

        return await self._queue_approval(context, section, lang, payload, "redline", log)

    # ── Shared approval helper ─────────────────────────────────────────────────

    async def _queue_approval(
        self,
        context: AgentContext,
        section: str,
        lang: str,
        payload: dict,
        action_label: str,
        log,
    ) -> AgentResult:
        try:
            from app.agents.registry import registry
            approval_mgr = registry.get("approval_manager")
            approval_result = await approval_mgr(context, {
                "action": "create",
                "action_name": f"services_pricing_editor.publish.{section}.{lang}",
                "risk_level": "P4",
                "payload": payload,
                "justification": (
                    f"Services/Pricing copy {action_label} — section: {section}, lang: {lang}. "
                    "P4 review required before publishing to WordPress. "
                    "Verify no live prices were introduced."
                ),
                "requested_by": self.name,
            })
        except Exception as exc:
            log.error("services_pricing_editor.approval_error", error=str(exc))
            return AgentResult.fail(f"services_pricing_editor: approval error — {exc}")

        approval_id = (
            approval_result.output.get("approval_id") if approval_result.success else None
        )
        log.info(
            "services_pricing_editor.queued",
            section=section,
            lang=lang,
            action=action_label,
            approval_id=approval_id,
        )

        return AgentResult.needs_approval(
            approval_id=approval_id or "unknown",
            action=f"services_pricing_editor.publish.{section}.{lang}",
        )
