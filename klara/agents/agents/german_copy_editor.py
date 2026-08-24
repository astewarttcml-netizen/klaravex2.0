"""
app/agents/german_copy_editor.py
──────────────────────────────────
German Copy Editor (Agent 29 — DE)

Edits, improves, and translates German B2B copy for klaravex.de.
Ensures formal Sie-form, idiomatic German, and brand consistency.

Permission level: P3 (output queued as ApprovalRequest — no direct publish)

Actions:
  translate — Translate English copy to formal German (Sie-form)
  review    — Review existing German copy and return critique + suggestions
  improve   — Rewrite provided German copy with improvements (queues approval)

Blocked: legal translation finalization; publishing without approval.
Fallback: flag ambiguous business wording for human review.
"""
from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)

_BRAND_BRIEF_DE = """
Unternehmen: Klaravex — selbständige IT-Beratung für Expats und internationale Unternehmen.
Inhaber: Anthony Stewart (Brite, ansässig in Berlin).
Zielgruppe: Englischsprachige Expats und internationale Firmen mit Bedarf an enterprise-grade IT in Berlin.
Tonalität: Professionell, direkt, vertrauenserweckend. KEIN Startup-Jargon, keine übertriebene Begeisterung.
Differenzierungsmerkmale: Enterprise-Erfahrung (Merrill Lynch, World Bank, FDH Aero), Berlin-ansässig, zweisprachig EN/DE.
Kernleistungen: Azure/Microsoft 365, Entra ID, Intune, Netzwerksicherheit, IT-Support.
Sprachregeln:
  - Ausschließlich "Sie"-Form (formal).
  - Idiomatisches, natürliches Deutsch — keine wörtliche Übersetzung aus dem Englischen.
  - Fachbegriffe aus dem IT-Bereich dürfen auf Englisch bleiben (z. B. Azure, Entra ID).
  - Satzstruktur: klar, prägnant, scanbar für Webseiten.
  - Rechtliche Formulierungen (Impressum, Datenschutz) NICHT eigenständig finalisieren.
"""

_LEGAL_SECTIONS = {"impressum", "datenschutz", "privacy", "legal", "agb", "terms"}


class GermanCopyEditorAgent(BaseAgent):
    name = "german_copy_editor"
    description = (
        "Edits, improves, and translates German B2B copy for klaravex.de. "
        "Ensures formal Sie-form and idiomatic B2B German. "
        "Queues output as a P3 ApprovalRequest — never publishes directly."
    )
    permission_level = PermissionLevel.P3

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        action = input_data.get("action", "translate")
        section = input_data.get("section", "").strip().lower()
        copy_input = input_data.get("copy", "").strip()
        instruction = input_data.get("instruction", "").strip()

        if not copy_input:
            return AgentResult.fail(
                "german_copy_editor requires 'copy' field with the text to process."
            )

        # Block direct legal finalization
        if any(kw in section for kw in _LEGAL_SECTIONS):
            return AgentResult.fail(
                f"german_copy_editor: section '{section}' is a legal page. "
                "Legal German copy must go through LEG agent and legal review. "
                "Submit to approval_manager with P4 risk level via LEG agent."
            )

        log.info("german_copy_editor.start", action=action, section=section)

        if action == "translate":
            return await self._translate(context, section, copy_input, instruction, log)
        elif action == "review":
            return await self._review(context, section, copy_input, instruction, log)
        elif action == "improve":
            return await self._improve(context, section, copy_input, instruction, log)
        else:
            return AgentResult.fail(
                f"Unknown action '{action}'. Valid: translate, review, improve"
            )

    # ── Translate (EN → DE) ───────────────────────────────────────────────────

    async def _translate(
        self, context: AgentContext, section: str, english_copy: str, instruction: str, log
    ) -> AgentResult:
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        prompt = f"""You are a senior German B2B copywriter specialising in IT consulting.

Brand context:
{_BRAND_BRIEF_DE}

Translate the following English copy into formal German for the "{section}" section.
{"Additional instruction: " + instruction if instruction else ""}

ENGLISH COPY:
{english_copy}

Rules:
- Use "Sie"-form throughout. No exceptions.
- Do NOT translate idiomatically awkward constructions — rewrite for natural German flow.
- Keep IT product names in English (Azure, Entra ID, Intune, Microsoft 365, etc.).
- Match web copy conventions: short sentences, active voice, scannable structure.
- Return the German copy ONLY — no explanation, no English, no markdown headers."""

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
            german_copy = msg.content[0].text.strip()
        except Exception as exc:
            log.error("german_copy_editor.claude_error", error=str(exc))
            return AgentResult.fail(f"german_copy_editor.translate: Claude error — {exc}")

        payload = {
            "action": "translate",
            "section": section,
            "source_copy": english_copy,
            "german_copy": german_copy,
            "instruction": instruction,
        }

        return await self._queue_approval(context, section, payload, "translate", log)

    # ── Review (DE copy analysis) ─────────────────────────────────────────────

    async def _review(
        self, context: AgentContext, section: str, german_copy: str, instruction: str, log
    ) -> AgentResult:
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        try:
            msg = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=700,
                messages=[{"role": "user", "content": (
                    f"Brand context:\n{_BRAND_BRIEF_DE}\n\n"
                    f"Review this German copy for the '{section}' section:\n\n"
                    f"{german_copy}\n\n"
                    f"{'Additional context: ' + instruction if instruction else ''}\n\n"
                    "Identify:\n"
                    "1. Sie/du consistency issues (must be Sie throughout)\n"
                    "2. Non-idiomatic or literal translations from English\n"
                    "3. Tone mismatches (too casual, too formal, wrong register)\n"
                    "4. Clarity or structure issues for web copy\n"
                    "5. Any brand-voice deviations\n\n"
                    "Give specific, actionable feedback. Flag ambiguous legal wording separately."
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
            return AgentResult.fail(f"german_copy_editor.review: Claude error — {exc}")

        log.info("german_copy_editor.review_complete", section=section)
        # Review is read-only — no approval needed
        return AgentResult.ok(output={
            "action": "review",
            "section": section,
            "critique": critique,
        })

    # ── Improve (rewrite existing DE copy) ────────────────────────────────────

    async def _improve(
        self, context: AgentContext, section: str, german_copy: str, instruction: str, log
    ) -> AgentResult:
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        prompt = f"""You are a senior German B2B copywriter specialising in IT consulting.

Brand context:
{_BRAND_BRIEF_DE}

Improve the following German copy for the "{section}" section.
{"Specific improvement goal: " + instruction if instruction else "Improve clarity, tone, and idiomatic flow."}

CURRENT GERMAN COPY:
{german_copy}

Rules:
- Use "Sie"-form throughout.
- Improve idiomatic flow — fix any literal translations.
- Maintain enterprise, authoritative tone.
- Keep IT product names in English.
- Return improved German copy ONLY — no explanation."""

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
            improved_copy = msg.content[0].text.strip()
        except Exception as exc:
            return AgentResult.fail(f"german_copy_editor.improve: Claude error — {exc}")

        payload = {
            "action": "improve",
            "section": section,
            "original_copy": german_copy,
            "improved_copy": improved_copy,
            "instruction": instruction,
        }

        return await self._queue_approval(context, section, payload, "improve", log)

    # ── Shared approval helper ─────────────────────────────────────────────────

    async def _queue_approval(
        self, context: AgentContext, section: str, payload: dict, action_label: str, log
    ) -> AgentResult:
        try:
            from app.agents.registry import registry
            approval_mgr = registry.get("approval_manager")
            approval_result = await approval_mgr(context, {
                "action": "create",
                "action_name": f"german_copy_editor.publish.{section}.de",
                "risk_level": "P3",
                "payload": payload,
                "justification": (
                    f"German copy edit ({action_label}) — section: {section}. "
                    "Requires review before publishing to WordPress / TranslatePress."
                ),
                "requested_by": self.name,
            })
        except Exception as exc:
            log.error("german_copy_editor.approval_error", error=str(exc))
            return AgentResult.fail(f"german_copy_editor: approval error — {exc}")

        approval_id = (
            approval_result.output.get("approval_id") if approval_result.success else None
        )
        log.info(
            "german_copy_editor.queued",
            section=section,
            action=action_label,
            approval_id=approval_id,
        )

        return AgentResult.needs_approval(
            approval_id=approval_id or "unknown",
            action=f"german_copy_editor.publish.{section}.de",
        )
