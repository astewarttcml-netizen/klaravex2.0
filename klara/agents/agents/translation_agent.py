"""
app/agents/translation_agent.py
────────────────────────────────
TranslationAgent — P2 content translation.

Fetches an existing WordPress page/post via REST API, translates the content
between EN and DE using Claude (preserving all HTML structure), then queues
a P3 ApprovalRequest for Anthony to review before the translation is pushed
to WordPress as a draft.

Supports two modes (resolved automatically):
  update_page  — target_page_id provided: PATCH an existing WP page with
                 the translation (e.g. EN About page → update DE About page)
  create_post  — no target_page_id: create a new WP draft post/page with
                 the translation (e.g. EN blog post → new DE draft)

Input:
  source_page_id:  int   — WP page/post ID to fetch and translate (required)
  source_language: str   — "en" | "de" (default "en")
  target_language: str   — "de" | "en" (default "de")
  target_page_id:  int   — WP page/post ID to update (optional; omit to create new)
  post_type:       str   — "page" | "post" (used only in create_post mode; default "post")

Permission: P2 — reads public WP content; queues P3 approval before any write.
"""
from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)

_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "de": "German (Deutsch)",
}

_TRANSLATE_PROMPT = """\
You are translating WordPress page content for Klaravex (klaravex.de).
Anthony Stewart is a senior enterprise IT consultant based in Berlin, Germany, \
specialising in Microsoft 365, Azure, Entra ID, Intune, Meraki, VMware, and IT security.

Translate the following HTML content from {source_lang_name} to {target_lang_name}.

RULES — follow these exactly:
1. Preserve ALL HTML tags exactly as written: <h1>, <h2>, <p>, <ul>, <li>, <strong>,
   <em>, <a href="...">, <div class="...">, etc.
2. Translate only the visible text between tags.
3. Do NOT translate URLs, CSS class names, element IDs, or HTML attribute names.
4. DO translate alt="" and title="" attribute values (they are visible/accessible text).
5. Keep technical proper nouns in English: Microsoft 365, Azure, Entra ID, Intune,
   SharePoint, PowerShell, VMware, Meraki, Citrix, PKI, VPN, LAN, WLAN, VLAN, DSGVO.
   Exception: "Cloud" may become "Cloud" or "Datenwolke" in DE depending on context.
6. For German (DE) output: use formal "Sie" throughout, never "du".
7. Match the register: professional, direct, enterprise-grade — no marketing fluff.
8. Output ONLY the translated HTML — no preamble, no explanation, no markdown fences.

SOURCE TITLE: {title}

SOURCE CONTENT (HTML):
{content_html}
"""

_TITLE_PROMPT = """\
Translate this page title from {source_lang_name} to {target_lang_name}.
Keep it concise and professional.
For DE: use formal register, keep English technical terms (Azure, Microsoft, etc.).
Return ONLY the translated title — no quotes, no explanation.

Title: {title}
"""


class TranslationAgent(BaseAgent):
    name = "translation_agent"
    description = (
        "Fetches a WordPress page or post, translates its content between EN and DE "
        "using Claude (preserving HTML structure), and queues a P3 ApprovalRequest for "
        "Anthony to review before the translation is pushed to WordPress as a draft. "
        "Supports update_page (patches existing WP page) and create_post (new WP draft) modes."
    )
    permission_level = PermissionLevel.P2

    # ─────────────────────────────────────────────────────────────────────────
    # Entry point
    # ─────────────────────────────────────────────────────────────────────────

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        source_page_id  = input_data.get("source_page_id")
        source_language = input_data.get("source_language", "en").lower().strip()
        target_language = input_data.get("target_language", "de").lower().strip()
        target_page_id  = input_data.get("target_page_id")   # None → create new
        post_type       = input_data.get("post_type", "post")

        if not source_page_id:
            return AgentResult.fail(
                "translation_agent: 'source_page_id' is required", agent=self.name
            )
        if source_language not in _LANG_NAMES:
            return AgentResult.fail(
                f"translation_agent: unsupported source_language '{source_language}' — use 'en' or 'de'",
                agent=self.name,
            )
        if target_language not in _LANG_NAMES:
            return AgentResult.fail(
                f"translation_agent: unsupported target_language '{target_language}' — use 'en' or 'de'",
                agent=self.name,
            )
        if source_language == target_language:
            return AgentResult.fail(
                "translation_agent: source_language and target_language must differ",
                agent=self.name,
            )

        log = logger.bind(
            agent=self.name,
            source_page_id=source_page_id,
            source_language=source_language,
            target_language=target_language,
            target_page_id=target_page_id,
            request_id=str(context.request_id),
        )

        # ── 1. Fetch source content from WP REST API ──────────────────────────
        log.info("translation_agent.fetching_source")
        fetch = await self._fetch_wp_content(context, int(source_page_id))
        if not fetch["ok"]:
            return AgentResult.fail(
                f"translation_agent: could not fetch WP page {source_page_id}: {fetch['error']}",
                agent=self.name,
            )

        source_title   = fetch["title"]
        source_content = fetch["content_html"]
        detected_type  = fetch.get("post_type", post_type)  # "page" | "post"

        if not source_content.strip():
            return AgentResult.fail(
                f"translation_agent: WP page {source_page_id} has empty content — nothing to translate",
                agent=self.name,
            )

        log.info(
            "translation_agent.source_ready",
            title=source_title,
            content_chars=len(source_content),
            detected_type=detected_type,
        )

        # ── 2. Translate via Claude ───────────────────────────────────────────
        source_lang_name = _LANG_NAMES[source_language]
        target_lang_name = _LANG_NAMES[target_language]

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        log.info("translation_agent.calling_claude", model=context.settings.anthropic_model)
        try:
            # Translate content (potentially large — allow up to 8192 tokens output)
            content_response = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=8192,
                messages=[{
                    "role": "user",
                    "content": _TRANSLATE_PROMPT.format(
                        source_lang_name=source_lang_name,
                        target_lang_name=target_lang_name,
                        title=source_title,
                        content_html=source_content,
                    ),
                }],
            )
            try:
                from app.services.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=context.settings.anthropic_model,
                    response=content_response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            translated_content = content_response.content[0].text.strip()

            # Translate title (small, fast)
            title_response = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=128,
                messages=[{
                    "role": "user",
                    "content": _TITLE_PROMPT.format(
                        source_lang_name=source_lang_name,
                        target_lang_name=target_lang_name,
                        title=source_title,
                    ),
                }],
            )
            try:
                from app.services.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=context.settings.anthropic_model,
                    response=title_response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            translated_title = title_response.content[0].text.strip()

        except Exception as exc:
            log.error("translation_agent.claude_error", error=str(exc))
            return AgentResult.fail(
                f"translation_agent: LLM error — {exc}", agent=self.name
            )

        log.info(
            "translation_agent.translation_complete",
            translated_title=translated_title,
            translated_chars=len(translated_content),
        )

        # ── 3. Queue P3 ApprovalRequest ───────────────────────────────────────
        mode = "update_page" if target_page_id else "create_post"
        approval_payload = {
            "source_page_id":  int(source_page_id),
            "target_page_id":  int(target_page_id) if target_page_id else None,
            "source_language": source_language,
            "target_language": target_language,
            "source_title":    source_title,
            "title":           translated_title,
            "content_html":    translated_content,
            "post_type":       detected_type,
            "mode":            mode,
        }

        justification = (
            f"Translation {source_language.upper()}→{target_language.upper()}: "
            f"'{source_title}' → '{translated_title}' "
            f"({'update WP page ' + str(target_page_id) if target_page_id else 'create new ' + detected_type})"
        )

        try:
            from app.agents.registry import registry
            approval_mgr    = registry.get("approval_manager")
            approval_result = await approval_mgr(context, {
                "action":        "create",
                "action_name":   "translation_agent.publish",
                "risk_level":    "P3",
                "payload":       approval_payload,
                "justification": justification,
                "requested_by":  self.name,
            })
        except Exception as exc:
            log.error("translation_agent.approval_queue_error", error=str(exc))
            return AgentResult.fail(
                f"translation_agent: could not queue approval — {exc}", agent=self.name
            )

        approval_id = (
            approval_result.output.get("approval_id")
            if approval_result.success
            else None
        )

        log.info(
            "translation_agent.queued",
            approval_id=approval_id,
            mode=mode,
            source_page_id=source_page_id,
            target_page_id=target_page_id,
        )

        return AgentResult.needs_approval(
            approval_id=approval_id or "unknown",
            action="translation_agent.publish",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # WP REST API fetch helper
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_wp_content(self, context: AgentContext, page_id: int) -> dict:
        """
        Fetch rendered content from WP REST API (unauthenticated; works for published).
        Tries /pages/{id} first, then /posts/{id}.

        Returns:
            {"ok": True, "title": str, "content_html": str, "post_type": str}
            {"ok": False, "error": str}
        """
        import aiohttp

        site    = context.settings.wp_site_url.rstrip("/")
        timeout = aiohttp.ClientTimeout(total=15)

        async with aiohttp.ClientSession() as http:
            for endpoint, ptype in (("pages", "page"), ("posts", "post")):
                url = f"{site}/wp-json/wp/v2/{endpoint}/{page_id}"
                try:
                    async with http.get(url, timeout=timeout) as resp:
                        if resp.status == 200:
                            body    = await resp.json(content_type=None)
                            title   = body.get("title",   {}).get("rendered", "")
                            content = body.get("content", {}).get("rendered", "")
                            return {
                                "ok":           True,
                                "title":        title,
                                "content_html": content,
                                "post_type":    ptype,
                            }
                        # 404 → try next endpoint
                except aiohttp.ClientError as exc:
                    logger.warning(
                        "translation_agent.fetch_error", url=url, error=str(exc)
                    )

        return {
            "ok":    False,
            "error": (
                f"WP REST API returned 404 for page_id={page_id} on both "
                f"/pages/ and /posts/ endpoints. The page may not be published "
                f"or the ID may be wrong."
            ),
        }
