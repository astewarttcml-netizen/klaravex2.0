"""
app/agents/content_calendar.py
───────────────────────────────
ContentCalendarAgent — generates a structured multi-week content calendar for
Klaravex's blog and social media channels.

The calendar is driven by:
  - Real lead inquiry data (top requested services extracted from leads.services_interest)
  - Seasonal/temporal context (current month, upcoming German holidays/events)
  - Consultant-supplied focus topics (optional override)

Output format per entry:
  Week#, Topic, Headline (EN + DE), Content type, Target keyword, CTA

Permission: P2 — output is a recommendation for the consultant; no external
publishing occurs in this agent. Publishing is handled by SeoContentWriterAgent
and SocialMediaManagerAgent after consultant review.

Pipeline position: standalone / on-demand, or scheduled weekly via Celery beat.
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.lead import Lead
from klara.rarv.runtime.email_sender import send_transactional_email

logger = structlog.get_logger(__name__)

# ── Maximum configurable constraints ─────────────────────────────────────────
MAX_WEEKS = 8
DEFAULT_WEEKS = 4

# ── Prompt ────────────────────────────────────────────────────────────────────
CALENDAR_PROMPT = """\
You are a content strategist for Klaravex — a boutique IT consulting
firm serving German SMBs and IT decision-makers. The firm offers services
including managed IT, cloud migration, cybersecurity, Microsoft 365, network
infrastructure, and IT support.

Your task: generate a structured {weeks}-week content calendar for blog posts
and social media (LinkedIn + Instagram).

CONTEXT
-------
Current date: {current_date} (Berlin time)
Current month: {current_month}
Top services requested by inbound leads (by frequency):
{top_services_list}
{focus_topics_section}

AUDIENCE
--------
- Primary: German SMB owners, IT managers, and operations leads (10–250 employees)
- Secondary: International companies with German operations
- Pain points: outdated infrastructure, security gaps, M365 adoption, GDPR compliance

REQUIREMENTS
------------
- Each week must have exactly 3 content items:
    1. Blog post (SEO-focused, targets a long-tail German/English keyword)
    2. LinkedIn post (thought leadership, 150–250 words recommended in the calendar)
    3. Instagram post (visual concept + short caption idea)
- Headlines must be provided in BOTH English and German
- CTAs should be specific and actionable (e.g. "Book a free 30-min IT audit")
- Leverage seasonal context (month, upcoming German IT events, fiscal year timing)
- Prioritise topics drawn from top_services above — these reflect real demand
- Avoid generic "10 tips" content; prefer specific, credible, practitioner-level angles

OUTPUT FORMAT
-------------
Return a valid JSON object with this exact structure:

{{
  "calendar": [
    {{
      "week": 1,
      "items": [
        {{
          "type": "Blog",
          "topic": "<concise topic phrase>",
          "headline_en": "<English headline>",
          "headline_de": "<German headline>",
          "target_keyword": "<primary SEO keyword>",
          "angle": "<one-sentence editorial angle>",
          "cta": "<specific call-to-action>",
          "seasonal_hook": "<why this is timely this month, or empty string>"
        }},
        {{
          "type": "LinkedIn",
          ...same fields...
        }},
        {{
          "type": "Instagram",
          ...same fields...
        }}
      ]
    }}
    ...repeat for each week...
  ],
  "editorial_note": "<2–3 sentence strategic summary of the calendar theme>"
}}

Return ONLY the JSON. No markdown fences, no commentary outside the JSON.
"""


class ContentCalendarAgent(BaseAgent):
    """
    Generates a 4-week (default) or up to 8-week bilingual content calendar
    for Klaravex's blog and social media.

    Input:
        weeks (int)           — weeks to plan, default 4, max 8
        focus_topics (list)   — optional topic override list
        notify (bool)         — email calendar to approval_notify_email, default True

    Output:
        calendar_markdown     — formatted Markdown version of the calendar
        calendar_json         — raw structured calendar from Claude
        weeks                 — number of weeks planned
        top_lead_topics       — list of (service, count) tuples used as input
        emailed               — whether notification email was sent
    """

    name = "content_calendar"
    description = (
        "Uses lead inquiry data and seasonal context to generate a 4-week content "
        "calendar for Klaravex blog and social media."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        db = context.db
        settings = context.settings

        # ── Input parsing ─────────────────────────────────────────────────────
        weeks = min(int(input_data.get("weeks", DEFAULT_WEEKS)), MAX_WEEKS)
        focus_topics: list[str] = input_data.get("focus_topics") or []
        notify: bool = input_data.get("notify", True)

        log.info("content_calendar.start", weeks=weeks, focus_topics=focus_topics)

        # ── Step 1: Aggregate top services from lead data ─────────────────────
        raw_si = (
            await db.execute(
                select(Lead.services_interest).where(
                    Lead.services_interest.isnot(None)
                )
            )
        ).scalars().all()

        counts: dict[str, int] = {}
        for si in raw_si:
            try:
                items = json.loads(si) if isinstance(si, str) else si
                for item in (items if isinstance(items, list) else []):
                    key = str(item).strip()
                    if key:
                        counts[key] = counts.get(key, 0) + 1
            except Exception:
                pass

        top_services: list[tuple[str, int]] = sorted(
            counts.items(), key=lambda x: x[1], reverse=True
        )[:8]

        log.debug("content_calendar.top_services", services=top_services)

        # ── Step 2: Temporal context ──────────────────────────────────────────
        now = datetime.now(ZoneInfo("Europe/Berlin"))
        current_date = now.strftime("%Y-%m-%d")
        current_month = now.strftime("%B %Y")

        # ── Step 3: Build Claude prompt ───────────────────────────────────────
        if top_services:
            top_services_list = "\n".join(
                f"  - {svc} ({cnt} enquiries)" for svc, cnt in top_services
            )
        else:
            top_services_list = "  (no lead data yet — use general IT consulting topics)"

        if focus_topics:
            focus_topics_section = (
                "MANDATORY FOCUS TOPICS (must appear in the calendar):\n"
                + "\n".join(f"  - {t}" for t in focus_topics)
            )
        else:
            focus_topics_section = ""

        prompt = CALENDAR_PROMPT.format(
            weeks=weeks,
            current_date=current_date,
            current_month=current_month,
            top_services_list=top_services_list,
            focus_topics_section=focus_topics_section,
        )

        # ── Step 4: Call Claude ───────────────────────────────────────────────
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        try:
            response = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            try:
                from klara.rarv.runtime.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=settings.anthropic_model,
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            raw_text = response.content[0].text.strip()
        except Exception as exc:
            log.error("content_calendar.claude_error", error=str(exc))
            return AgentResult.fail(f"Claude API error: {exc}")

        # ── Step 5: Parse calendar JSON ───────────────────────────────────────
        calendar_data = _parse_json(raw_text)
        if not calendar_data or "calendar" not in calendar_data:
            log.error("content_calendar.parse_error", raw=raw_text[:300])
            return AgentResult.fail(
                "Could not parse structured calendar from Claude response."
            )

        # ── Step 6: Render Markdown ───────────────────────────────────────────
        calendar_markdown = _render_markdown(
            calendar_data, weeks, current_month, top_services
        )

        # ── Step 7: Email to consultant if requested ──────────────────────────
        emailed = False
        notify_email = getattr(settings, "approval_notify_email", None)

        if notify and notify_email:
            subject = f"Klaravex — {weeks}-Week Content Calendar ({current_month})"
            body_text = _render_plain_text(calendar_data, weeks, current_month)
            body_html = _render_html(calendar_data, weeks, current_month, top_services)

            emailed = await send_transactional_email(
                settings,
                to_email=notify_email,
                to_name="Klaravex",
                subject=subject,
                body_html=body_html,
                body_text=body_text,
            )
            log.info(
                "content_calendar.emailed",
                to=notify_email,
                sent=emailed,
            )
        elif notify and not notify_email:
            log.warning(
                "content_calendar.notify_skipped",
                reason="approval_notify_email not configured",
            )

        log.info(
            "content_calendar.complete",
            weeks=weeks,
            items_generated=sum(
                len(w.get("items", [])) for w in calendar_data.get("calendar", [])
            ),
            emailed=emailed,
        )

        return AgentResult.ok(
            output={
                "calendar_markdown": calendar_markdown,
                "calendar_json": calendar_data,
                "weeks": weeks,
                "top_lead_topics": top_services,
                "emailed": emailed,
                "generated_at": current_date,
                "tokens_used": response.usage.output_tokens,
            }
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict | None:
    """Extract the first JSON object from a Claude response string."""
    import re

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _render_markdown(
    data: dict,
    weeks: int,
    month: str,
    top_services: list[tuple[str, int]],
) -> str:
    lines: list[str] = [
        f"# Klaravex — {weeks}-Week Content Calendar",
        f"*Generated for {month}*",
        "",
    ]

    if top_services:
        lines.append("## Top Lead Enquiry Topics")
        for svc, cnt in top_services:
            lines.append(f"- **{svc}** — {cnt} enquiries")
        lines.append("")

    editorial = data.get("editorial_note", "")
    if editorial:
        lines.append("## Editorial Strategy")
        lines.append(editorial)
        lines.append("")

    for week_data in data.get("calendar", []):
        week_num = week_data.get("week", "?")
        lines.append(f"## Week {week_num}")
        lines.append("")

        for item in week_data.get("items", []):
            content_type = item.get("type", "Content")
            lines.append(f"### {content_type}")
            lines.append(f"**Topic:** {item.get('topic', '')}")
            lines.append(f"**Headline (EN):** {item.get('headline_en', '')}")
            lines.append(f"**Headline (DE):** {item.get('headline_de', '')}")
            lines.append(f"**Target Keyword:** `{item.get('target_keyword', '')}`")
            lines.append(f"**Angle:** {item.get('angle', '')}")
            lines.append(f"**CTA:** {item.get('cta', '')}")
            seasonal = item.get("seasonal_hook", "")
            if seasonal:
                lines.append(f"**Seasonal Hook:** {seasonal}")
            lines.append("")

    return "\n".join(lines)


def _render_plain_text(data: dict, weeks: int, month: str) -> str:
    lines: list[str] = [
        f"IT EXPERTS BERLIN — {weeks}-WEEK CONTENT CALENDAR ({month})",
        "=" * 60,
        "",
    ]
    editorial = data.get("editorial_note", "")
    if editorial:
        lines += ["EDITORIAL STRATEGY", editorial, ""]

    for week_data in data.get("calendar", []):
        week_num = week_data.get("week", "?")
        lines.append(f"WEEK {week_num}")
        lines.append("-" * 40)
        for item in week_data.get("items", []):
            lines.append(f"[{item.get('type', '')}]")
            lines.append(f"  Topic:      {item.get('topic', '')}")
            lines.append(f"  EN:         {item.get('headline_en', '')}")
            lines.append(f"  DE:         {item.get('headline_de', '')}")
            lines.append(f"  Keyword:    {item.get('target_keyword', '')}")
            lines.append(f"  Angle:      {item.get('angle', '')}")
            lines.append(f"  CTA:        {item.get('cta', '')}")
            seasonal = item.get("seasonal_hook", "")
            if seasonal:
                lines.append(f"  Seasonal:   {seasonal}")
            lines.append("")
        lines.append("")

    return "\n".join(lines)


def _render_html(
    data: dict,
    weeks: int,
    month: str,
    top_services: list[tuple[str, int]],
) -> str:
    type_colours = {
        "Blog": "#1a73e8",
        "LinkedIn": "#0a66c2",
        "Instagram": "#c13584",
    }

    parts: list[str] = [
        "<div style='font-family:Arial,sans-serif;max-width:800px;color:#222;'>",
        f"<h2 style='color:#1a73e8;'>Klaravex — {weeks}-Week Content Calendar</h2>",
        f"<p style='color:#666;font-size:14px;'>Generated for {month}</p>",
    ]

    if top_services:
        parts.append("<h3>Top Lead Enquiry Topics</h3><ul>")
        for svc, cnt in top_services:
            parts.append(
                f"<li><strong>{svc}</strong> &mdash; {cnt} enquiries</li>"
            )
        parts.append("</ul>")

    editorial = data.get("editorial_note", "")
    if editorial:
        parts.append(
            f"<div style='background:#f0f4ff;padding:12px 16px;border-left:4px solid #1a73e8;"
            f"margin:16px 0;'><strong>Editorial Strategy:</strong> {editorial}</div>"
        )

    for week_data in data.get("calendar", []):
        week_num = week_data.get("week", "?")
        parts.append(
            f"<h2 style='border-bottom:2px solid #1a73e8;padding-bottom:4px;'>"
            f"Week {week_num}</h2>"
        )
        for item in week_data.get("items", []):
            content_type = item.get("type", "Content")
            colour = type_colours.get(content_type, "#333")
            parts.append(
                f"<div style='border:1px solid #ddd;border-radius:6px;"
                f"padding:12px 16px;margin:10px 0;border-left:5px solid {colour};'>"
            )
            parts.append(
                f"<span style='background:{colour};color:#fff;font-size:12px;"
                f"padding:2px 8px;border-radius:3px;'>{content_type}</span>"
            )
            parts.append(f"<p><strong>Topic:</strong> {item.get('topic', '')}</p>")
            parts.append(
                f"<p><strong>EN:</strong> {item.get('headline_en', '')}<br>"
                f"<strong>DE:</strong> {item.get('headline_de', '')}</p>"
            )
            parts.append(
                f"<p><strong>Keyword:</strong> "
                f"<code>{item.get('target_keyword', '')}</code></p>"
            )
            parts.append(f"<p><strong>Angle:</strong> {item.get('angle', '')}</p>")
            parts.append(f"<p><strong>CTA:</strong> {item.get('cta', '')}</p>")
            seasonal = item.get("seasonal_hook", "")
            if seasonal:
                parts.append(
                    f"<p style='color:#666;font-size:13px;'>"
                    f"<em>Seasonal hook: {seasonal}</em></p>"
                )
            parts.append("</div>")

    parts.append("</div>")
    return "".join(parts)
