"""
app/agents/blog_case_study_draft.py
──────────────────────────────────────
Blog / Case Study Draft Agent (Agent 30 — BLOG)

Creates draft blog posts and case study structures for klaravex.de.
Uses Claude to produce authoritative, enterprise-grade IT content.

Permission level: P3 (draft queued as ApprovalRequest — never published directly)

Actions:
  draft   — Generate a full draft for a blog post or case study
  outline — Generate a structured outline (lower risk, faster to review)

Content types:
  blog_post      — Technical or advisory article (600–1000 words)
  case_study     — Client engagement writeup (uses placeholders, not real names)
  linkedin_post  — Short thought-leadership post (150–300 words)
  how_to_guide   — Step-by-step technical guide (750–1200 words)

Blocked: inventing specific client names, logos, testimonials, or real outcomes.
         All client references must use placeholders: [CLIENT], [INDUSTRY], [OUTCOME].
Fallback: leave TODO markers for verified facts rather than fabricating.
"""
from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

_VALID_CONTENT_TYPES = {
    "blog_post",
    "case_study",
    "linkedin_post",
    "how_to_guide",
}

_CONTENT_TYPE_CONFIG = {
    "blog_post": {
        "label": "Blog Post",
        "length": "600–1000 words",
        "format": "H1 title, intro paragraph, 3–4 H2 sections with body copy, conclusion with CTA",
        "max_tokens": 1800,
    },
    "case_study": {
        "label": "Case Study",
        "length": "500–800 words",
        "format": (
            "Sections: Challenge, Solution, Implementation, Outcome. "
            "Use [CLIENT], [INDUSTRY], [CITY/REGION] placeholders — NEVER fabricate real names."
        ),
        "max_tokens": 1500,
    },
    "linkedin_post": {
        "label": "LinkedIn Post",
        "length": "150–300 words",
        "format": "Opening hook (no headline), 3–4 short paragraphs, 1 CTA line, 3–5 hashtags",
        "max_tokens": 700,
    },
    "how_to_guide": {
        "label": "How-To Guide",
        "length": "750–1200 words",
        "format": "H1 title, intro with target audience, numbered steps (H2 per step), summary",
        "max_tokens": 2000,
    },
}

_BRAND_BRIEF = """
Business: Klaravex — freelance IT consulting for expats and international businesses.
Owner: Anthony Stewart (British, based in Berlin). Enterprise background: Merrill Lynch, World Bank, FDH Aero.
Audience: English-speaking expats + international companies needing enterprise-grade IT in Berlin.
Tone: Authoritative, direct, practical. Demonstrates deep expertise without being condescending.
Content focus: Azure, Microsoft 365, Entra ID, Intune, network security, enterprise IT support.
SEO: Target expat professionals and international businesses searching for English-speaking IT support in Berlin.
"""

_FABRICATION_GUARD = """
CRITICAL RULES — do not break these:
1. NEVER invent client names, company names, logos, or specific testimonials.
2. NEVER state specific measurable outcomes (e.g. "saved 40% costs") unless given to you.
3. For case studies: use [CLIENT], [CLIENT_INDUSTRY], [OUTCOME], [TIMEFRAME] as placeholders.
4. Leave TODO: [VERIFY] markers for any statistic or factual claim you cannot confirm.
5. Do NOT invent regulatory deadlines or compliance mandates unless they are publicly known.
"""


class BlogCaseStudyDraftAgent(BaseAgent):
    name = "blog_case_study_draft"
    description = (
        "Drafts blog posts, case studies, LinkedIn posts, and how-to guides for "
        "klaravex.de. Never fabricates client details. "
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
        content_type = input_data.get("content_type", "blog_post").strip().lower()
        topic = input_data.get("topic", "").strip()
        instruction = input_data.get("instruction", "").strip()
        target_lang = input_data.get("target_lang", "en").lower()

        if content_type not in _VALID_CONTENT_TYPES:
            return AgentResult.fail(
                f"Unknown content_type '{content_type}'. Valid: {sorted(_VALID_CONTENT_TYPES)}"
            )
        if not topic:
            return AgentResult.fail("blog_case_study_draft requires 'topic' field.")
        if target_lang not in ("en", "de"):
            return AgentResult.fail("target_lang must be 'en' or 'de'")

        log.info(
            "blog_case_study_draft.start",
            action=action,
            content_type=content_type,
            topic=topic[:60],
            lang=target_lang,
        )

        if action == "draft":
            return await self._draft(context, content_type, topic, instruction, target_lang, log)
        elif action == "outline":
            return await self._outline(context, content_type, topic, instruction, target_lang, log)
        else:
            return AgentResult.fail(f"Unknown action '{action}'. Valid: draft, outline")

    # ── Draft ─────────────────────────────────────────────────────────────────

    async def _draft(
        self,
        context: AgentContext,
        content_type: str,
        topic: str,
        instruction: str,
        lang: str,
        log,
    ) -> AgentResult:
        cfg = _CONTENT_TYPE_CONFIG[content_type]
        lang_note = (
            "Write in formal English for international B2B audiences."
            if lang == "en"
            else "Write in formal German (Sie-form). Idiomatic, not literal. Keep IT terms in English."
        )

        prompt = f"""You are a senior B2B content writer for an IT consulting firm in Berlin.

Brand brief:
{_BRAND_BRIEF}

Your task: Write a complete {cfg['label']} draft on the following topic.

TOPIC: {topic}
{"Additional instruction: " + instruction if instruction else ""}

Format: {cfg['format']}
Length: {cfg['length']}
Language: {lang.upper()} — {lang_note}

{_FABRICATION_GUARD}

Return the content ONLY — ready to paste into WordPress. No meta-commentary."""

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            msg = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=cfg["max_tokens"],
                system=(
                    "You are a precise B2B copywriter. Follow the fabrication rules exactly. "
                    "Use TODO: [VERIFY] for any unconfirmed facts. Never make up client outcomes."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            from klara.rarv.runtime.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=msg,
            )
            draft = msg.content[0].text.strip()
        except Exception as exc:
            log.error("blog_case_study_draft.claude_error", error=str(exc))
            return AgentResult.fail(f"blog_case_study_draft: Claude error — {exc}")

        # Flag if draft may contain fabricated content
        fabrication_risk = any(
            marker in draft.lower()
            for marker in ["%", "percent", "saved", "reduced by", "increased by"]
        )

        payload = {
            "content_type": content_type,
            "topic": topic,
            "target_lang": lang,
            "instruction": instruction,
            "draft": draft,
            "fabrication_risk_flag": fabrication_risk,
        }

        return await self._queue_approval(context, content_type, topic, payload, "draft", log)

    # ── Outline ───────────────────────────────────────────────────────────────

    async def _outline(
        self,
        context: AgentContext,
        content_type: str,
        topic: str,
        instruction: str,
        lang: str,
        log,
    ) -> AgentResult:
        cfg = _CONTENT_TYPE_CONFIG[content_type]

        try:
            client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
            msg = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=700,
                messages=[{"role": "user", "content": (
                    f"Brand brief:\n{_BRAND_BRIEF}\n\n"
                    f"Create a structured outline for a {cfg['label']} on: {topic}\n"
                    f"{'Additional instruction: ' + instruction if instruction else ''}\n"
                    f"Language: {lang.upper()}\n\n"
                    f"Format: {cfg['format']}\n\n"
                    "Return: heading structure with 2–3 bullet notes per section. "
                    "No full prose. Flag any section needing real client data with [VERIFY]."
                )}],
            )
            from klara.rarv.runtime.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=msg,
            )
            outline = msg.content[0].text.strip()
        except Exception as exc:
            return AgentResult.fail(f"blog_case_study_draft.outline: Claude error — {exc}")

        log.info("blog_case_study_draft.outline_complete", content_type=content_type)
        # Outlines are low-risk — return directly without approval
        return AgentResult.ok(output={
            "content_type": content_type,
            "topic": topic,
            "lang": lang,
            "outline": outline,
        })

    # ── Shared approval helper ─────────────────────────────────────────────────

    async def _queue_approval(
        self,
        context: AgentContext,
        content_type: str,
        topic: str,
        payload: dict,
        action_label: str,
        log,
    ) -> AgentResult:
        fabrication_flag = payload.get("fabrication_risk_flag", False)
        safe_topic = topic[:50].replace(" ", "_").lower()

        try:
            from app.agents.registry import registry
            approval_mgr = registry.get("approval_manager")
            approval_result = await approval_mgr(context, {
                "action": "create",
                "action_name": f"blog_case_study_draft.publish.{content_type}",
                "risk_level": "P3",
                "payload": payload,
                "justification": (
                    f"Blog/Content draft ({action_label}) — type: {content_type}, topic: {topic[:80]}. "
                    f"{'⚠ Fabrication risk flag set — check for invented stats or client details. ' if fabrication_flag else ''}"
                    "Needs editorial review and fact-check before publishing to WordPress."
                ),
                "requested_by": self.name,
            })
        except Exception as exc:
            log.error("blog_case_study_draft.approval_error", error=str(exc))
            return AgentResult.fail(f"blog_case_study_draft: approval error — {exc}")

        approval_id = (
            approval_result.output.get("approval_id") if approval_result.success else None
        )
        log.info(
            "blog_case_study_draft.queued",
            content_type=content_type,
            action=action_label,
            approval_id=approval_id,
            fabrication_risk=fabrication_flag,
        )

        return AgentResult.needs_approval(
            approval_id=approval_id or "unknown",
            action=f"blog_case_study_draft.publish.{content_type}",
        )
