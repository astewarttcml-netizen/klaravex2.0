"""
app/agents/seo_content_writer.py
──────────────────────────────────
SeoContentWriterAgent — P3 content publishing.

Generates SEO-optimised blog posts and service page content for
klaravex.de, then queues the draft for P3 human approval.
After approval, the website_deploy agent publishes to WordPress as a draft.

Input:
  - keyword: str          — target SEO keyword (required)
  - title: str            — optional post title (auto-generated if omitted)
  - content_type: str     — "blog_post" (default) | "service_page" | "faq"
  - language: str         — "en" (default) | "de"
  - word_count: int       — target word count (default 800)

Output: queued approval record with full post content.

Permission: P3 — publishing to public website.
"""
from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

_BLOG_PROMPT_EN = """\
You are writing a blog post for Klaravex (klaravex.de).
Anthony Stewart is an enterprise IT consultant based in Berlin serving
English-speaking expats, international businesses, and German SMBs.

Target keyword: {keyword}
Content type:   {content_type}
Target length:  ~{word_count} words

Anthony's expertise: Azure, Entra ID, Intune, Meraki, VMware, M365,
PowerShell, IT security, hybrid cloud, networking, PKI.

Write in English. Structure:
  - SEO-optimised H1 title containing the keyword
  - Meta description (155 chars, keyword included)
  - Introduction (hook + why this matters)
  - 3–4 H2 sections with practical advice
  - Conclusion with a clear CTA to contact Klaravex
  - Avoid filler phrases like "In today's digital landscape"

Output format (use these exact markers):
TITLE: <title>
META: <meta description>
CONTENT:
<full post body in HTML paragraphs — use <h2>, <p>, <ul>/<li> tags>
"""

_BLOG_PROMPT_DE = """\
Du schreibst einen Blogbeitrag für Klaravex (klaravex.de).
Anthony Stewart ist IT-Consultant in Berlin für englischsprachige Expats,
internationale Unternehmen und deutsche KMU.

Ziel-Keyword: {keyword}
Content-Typ:  {content_type}
Ziellänge:    ~{word_count} Wörter

Kompetenzen: Azure, Entra ID, Intune, Meraki, VMware, M365,
PowerShell, IT-Sicherheit, Hybrid Cloud, Netzwerk, PKI.

Schreibe auf Deutsch. Struktur:
  - SEO-optimierter H1-Titel mit dem Keyword
  - Meta-Beschreibung (max. 155 Zeichen, Keyword enthalten)
  - Einleitung (Hook + Relevanz)
  - 3–4 H2-Abschnitte mit praktischen Tipps
  - Fazit mit CTA zu Klaravex
  - Keine Füllsätze wie "In der heutigen digitalen Welt"

Ausgabeformat (exakt diese Marker):
TITLE: <Titel>
META: <Meta-Beschreibung>
CONTENT:
<vollständiger Beitragstext als HTML — <h2>, <p>, <ul>/<li>>
"""


class SeoContentWriterAgent(BaseAgent):
    name = "seo_content_writer"
    description = (
        "Generates SEO-optimised blog posts and service page content for "
        "klaravex.de. Target keyword, content type, language, and word count "
        "are configurable. Queues draft for P3 approval, then website_deploy publishes. "
        "P3 — external content publishing."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        keyword      = input_data.get("keyword", "").strip()
        content_type = input_data.get("content_type", "blog_post")
        language     = input_data.get("language", "en")
        word_count   = int(input_data.get("word_count", 800))

        if not keyword:
            return AgentResult.fail("seo_content_writer: keyword is required", agent=self.name)

        prompt_template = _BLOG_PROMPT_DE if language == "de" else _BLOG_PROMPT_EN
        prompt = prompt_template.format(
            keyword=keyword,
            content_type=content_type,
            word_count=word_count,
        )

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            from klara.rarv.runtime.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="_PROMPT",
                content=str(_PROMPT),
            )
        except Exception:
            pass

        try:
            response = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}],
            )
            try:
                from klara.rarv.runtime.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=context.settings.anthropic_model,
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            raw = response.content[0].text.strip()
        except Exception as exc:
            logger.error("seo_content_writer.claude_error", error=str(exc))
            return AgentResult.fail(f"seo_content_writer: LLM error — {exc}", agent=self.name)

        # ── Parse structured output ──────────────────────────────────────────
        title = meta = content = ""
        for line in raw.splitlines():
            if line.startswith("TITLE:"):
                title = line[6:].strip()
            elif line.startswith("META:"):
                meta = line[5:].strip()
        if "CONTENT:" in raw:
            content = raw.split("CONTENT:", 1)[1].strip()

        if not title:
            title = f"{keyword.title()} — Klaravex"
        if not content:
            content = raw  # fallback: use full output

        # ── Queue for P3 approval (website_deploy will publish after) ────────
        payload = {
            "keyword":      keyword,
            "content_type": content_type,
            "language":     language,
            "title":        title,
            "meta":         meta,
            "content_html": content,
        }
        try:
            from app.agents.registry import registry
            approval_mgr = registry.get("approval_manager")
            approval_result = await approval_mgr(context, {
                "action":       "create",
                "action_name":  "seo_content_writer.publish",
                "risk_level":   "P3",
                "payload":      payload,
                "justification": f"SEO {content_type} draft: '{title}' (keyword: {keyword})",
                "requested_by": self.name,
            })
        except Exception as exc:
            logger.error("seo_content_writer.approval_error", error=str(exc))
            return AgentResult.fail(f"seo_content_writer: approval error — {exc}", agent=self.name)

        approval_id = (
            approval_result.output.get("approval_id") if approval_result.success else None
        )
        logger.info("seo_content_writer.queued", keyword=keyword, title=title, approval_id=approval_id)

        return AgentResult.needs_approval(
            approval_id=approval_id or "unknown",
            action="seo_content_writer.publish",
        )
