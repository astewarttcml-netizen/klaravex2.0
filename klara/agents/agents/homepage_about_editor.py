"""
app/agents/homepage_about_editor.py
─────────────────────────────────────
Homepage / About Editor (Agent 27 — HOME)

Drafts revised copy for the klaravex.de homepage and about page.
Uses Claude to improve trust signals, clarity, and B2B positioning.

Permission level: P3 (draft queued as ApprovalRequest before any publish)

Actions:
  draft    — Generate revised copy for a named section in EN or DE
  critique — Return actionable critique of current copy without rewriting

Sections: hero, intro, value_props, trust_signals, cta,
          about_story, about_methodology, about_background

Blocked: publishing without approval.
Fallback: save draft revision as ApprovalRequest only.
"""
from __future__ import annotations

import json

import structlog
from anthropic import AsyncAnthropic

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

_VALID_SECTIONS = {
    "hero", "intro", "value_props", "trust_signals", "cta",
    "about_story", "about_methodology", "about_background",
}

_SECTION_CONTEXT = {
    "hero": "Full-width hero: headline + sub-headline + primary CTA button",
    "intro": "Two-paragraph intro below the hero explaining what Anthony does",
    "value_props": "3–4 value proposition cards (icon + title + short description)",
    "trust_signals": "Logo strip or quote block from past clients/employers",
    "cta": "Mid-page or footer call-to-action block driving contact form",
    "about_story": "Personal background section on the About page",
    "about_methodology": "How Anthony works — methodology / process section",
    "about_background": "Enterprise background: Merrill Lynch, World Bank, FDH Aero",
}

_BRAND_BRIEF = """
Business: Klaravex — freelance IT consulting for expats and international businesses.
Owner: Anthony Stewart (British, based in Berlin).
Audience: English-speaking expats + international companies needing enterprise-grade IT in Berlin.
Tone: Authoritative, direct, reassuring. NOT startup-casual or over-enthusiastic.
Differentiators: Enterprise pedigree (Merrill Lynch, World Bank, FDH Aero), Berlin-based, bilingual EN/DE.
Key services: Azure/Microsoft 365, Entra ID, Intune, network security, IT support.
"""


class HomepageAboutEditorAgent(BaseAgent):
    name = "homepage_about_editor"
    description = (
        "Drafts revised homepage and about-page copy for klaravex.de. "
        "Queues output as a P3 ApprovalRequest — never publishes directly."
    )
    permission_level = PermissionLevel.P3

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

        log.info("homepage_about_editor.start", action=action, section=section, lang=target_lang)

        if action == "draft":
            return await self._draft(context, section, target_lang, instruction, log)
        elif action == "critique":
            return await self._critique(context, section, target_lang, instruction, log)
        else:
            return AgentResult.fail(f"Unknown action '{action}'. Valid: draft, critique")

    # ── Draft ─────────────────────────────────────────────────────────────────

    async def _draft(
        self, context: AgentContext, section: str, lang: str, instruction: str, log
    ) -> AgentResult:
        section_ctx = _SECTION_CONTEXT.get(section, "")
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

Requirements:
- Match the authoritative, direct tone
- Highlight enterprise pedigree and Berlin-based advantage
- Keep copy concise and scannable (this is a web page, not a document)
- If writing DE, use "Sie" throughout
- Return the copy ONLY — no explanation, no markdown headers"""

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            msg = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            from klara.rarv.runtime.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=msg,
            )
            draft_copy = msg.content[0].text.strip()
        except Exception as exc:
            log.error("homepage_about_editor.claude_error", error=str(exc))
            return AgentResult.fail(f"homepage_about_editor: Claude error — {exc}")

        payload = {
            "section": section,
            "target_lang": lang,
            "instruction": instruction,
            "draft_copy": draft_copy,
        }

        try:
            from app.agents.registry import registry
            approval_mgr = registry.get("approval_manager")
            approval_result = await approval_mgr(context, {
                "action": "create",
                "action_name": f"homepage_about_editor.publish.{section}.{lang}",
                "risk_level": "P3",
                "payload": payload,
                "justification": (
                    f"Homepage/About copy draft — section: {section}, lang: {lang}. "
                    "Needs review before publishing to WordPress."
                ),
                "requested_by": self.name,
            })
        except Exception as exc:
            log.error("homepage_about_editor.approval_error", error=str(exc))
            return AgentResult.fail(f"homepage_about_editor: approval error — {exc}")

        approval_id = (
            approval_result.output.get("approval_id") if approval_result.success else None
        )
        log.info(
            "homepage_about_editor.draft_queued",
            section=section,
            lang=lang,
            approval_id=approval_id,
        )

        return AgentResult.needs_approval(
            approval_id=approval_id or "unknown",
            action=f"homepage_about_editor.publish.{section}.{lang}",
        )

    # ── Critique ──────────────────────────────────────────────────────────────

    async def _critique(
        self, context: AgentContext, section: str, lang: str, instruction: str, log
    ) -> AgentResult:
        current_copy = instruction or "(no copy provided — provide current copy in 'instruction')"
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        try:
            msg = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=600,
                messages=[{"role": "user", "content": (
                    f"Brand brief:\n{_BRAND_BRIEF}\n\n"
                    f"Critique this {section} section copy ({lang.upper()}):\n\n"
                    f"{current_copy}\n\n"
                    "Give 3–5 specific, actionable improvements. Be direct."
                )}],
            )
            from klara.rarv.runtime.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=msg,
            )
            critique = msg.content[0].text.strip()
        except Exception as exc:
            return AgentResult.fail(f"homepage_about_editor.critique: Claude error — {exc}")

        log.info("homepage_about_editor.critique_complete", section=section)
        return AgentResult.ok(output={"section": section, "lang": lang, "critique": critique})
