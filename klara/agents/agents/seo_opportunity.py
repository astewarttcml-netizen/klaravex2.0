"""
app/agents/seo_opportunity.py
──────────────────────────────
SEOOpportunityAgent — analyses the Klaravex website pages and
aggregates lead services_interest data to surface keyword opportunities,
content gaps, and quick-win SEO recommendations.

Permission level: P1 (read-only: external HTTP, DB read, Claude API, optional email).

Input keys:
  page_urls  list[str]  — specific page URLs to analyse.
                          Default: homepage, /services, /kontakt derived from
                          settings.wp_site_url.
  notify     bool       — send the report to approval_notify_email (default True).

Output keys:
  report            str             — Claude-generated Markdown SEO opportunity report.
  top_lead_services list[tuple]     — top 10 (service, count) pairs from lead data.
  pages_analysed    int             — number of pages successfully fetched.
  emailed           bool            — whether the report email was sent.
"""
from __future__ import annotations

import json
import re

import httpx
import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.lead import Lead
from app.services.email_sender import send_transactional_email

logger = structlog.get_logger(__name__)

_TEXT_TRUNCATE = 3000   # chars of visible text per page
_HTTP_TIMEOUT = 15.0
_HTTP_UA = "Mozilla/5.0 (compatible; LokiBot/1.0)"
_DEFAULT_PATHS = ["/", "/services", "/kontakt"]


def _extract_visible_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace to extract visible page text."""
    # Remove <script> and <style> blocks entirely
    text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace runs to single space
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _resolve_page_urls(settings, page_urls: list[str]) -> list[str]:
    """
    Return the list of full URLs to fetch.  If page_urls is empty or absent,
    build defaults from settings.wp_site_url + _DEFAULT_PATHS.
    """
    if page_urls:
        return page_urls

    base = settings.wp_site_url.rstrip("/")
    return [base + path for path in _DEFAULT_PATHS]


class SEOOpportunityAgent(BaseAgent):
    """
    Analyses the Klaravex website and lead inquiry data to identify
    SEO keyword opportunities and content gaps.

    The agent:
    1. Fetches each target page via httpx and extracts visible text.
    2. Queries the leads table to aggregate the most frequently requested
       services (services_interest JSON field).
    3. Sends page content + lead demand signals to Claude for SEO analysis.
    4. Optionally emails the report to approval_notify_email.

    Any page fetch failure is logged as a warning and skipped — a partial
    result is always returned rather than failing the full run.
    """

    name = "seo_opportunity"
    description = (
        "Analyses the Klaravex website and lead inquiry data to "
        "identify SEO keyword opportunities and content gaps."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )
        settings = context.settings
        db = context.db

        # ── Resolve inputs ────────────────────────────────────────────────────
        raw_urls: list[str] = input_data.get("page_urls") or []
        target_urls = _resolve_page_urls(settings, raw_urls)
        notify: bool = bool(input_data.get("notify", True))

        log.info("seo_opportunity.starting", pages=len(target_urls))

        # ── Fetch website pages ───────────────────────────────────────────────
        page_snippets: list[dict[str, str]] = []
        failed_pages: list[str] = []

        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _HTTP_UA},
        ) as client:
            for url in target_urls:
                try:
                    log.debug("seo_opportunity.fetching", url=url)
                    resp = await client.get(url)
                    resp.raise_for_status()
                    visible = _extract_visible_text(resp.text)
                    page_snippets.append({
                        "url": url,
                        "text": visible[:_TEXT_TRUNCATE],
                    })
                    log.info(
                        "seo_opportunity.fetched",
                        url=url,
                        chars=min(len(visible), _TEXT_TRUNCATE),
                    )
                except httpx.TimeoutException:
                    log.warning("seo_opportunity.timeout", url=url)
                    failed_pages.append(url)
                except httpx.HTTPStatusError as exc:
                    log.warning(
                        "seo_opportunity.http_error",
                        url=url,
                        status=exc.response.status_code,
                    )
                    failed_pages.append(url)
                except Exception as exc:
                    log.warning("seo_opportunity.fetch_error", url=url, error=str(exc))
                    failed_pages.append(url)

        if not page_snippets:
            return AgentResult.fail(
                error="All target pages failed to fetch. Cannot perform SEO analysis.",
                failed_pages=failed_pages,
            )

        # ── Aggregate lead services_interest ─────────────────────────────────
        top_services: list[tuple[str, int]] = []
        try:
            result = await db.execute(
                select(Lead.services_interest).where(
                    Lead.services_interest.isnot(None)
                )
            )
            raw_values = result.scalars().all()

            counts: dict[str, int] = {}
            for si in raw_values:
                try:
                    items = json.loads(si) if isinstance(si, str) else si
                    for item in (items if isinstance(items, list) else []):
                        key = str(item).strip()
                        if key:
                            counts[key] = counts.get(key, 0) + 1
                except Exception:
                    pass

            top_services = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
            log.info(
                "seo_opportunity.lead_services",
                unique_services=len(counts),
                top_count=len(top_services),
            )
        except Exception as exc:
            # Non-fatal — proceed with empty services list
            log.warning("seo_opportunity.lead_query_error", error=str(exc))

        # ── Build Claude prompt ───────────────────────────────────────────────
        page_blocks = "\n\n".join(
            f"--- PAGE: {s['url']} ---\n{s['text']}"
            for s in page_snippets
        )

        if top_services:
            services_table = "\n".join(
                f"  {i + 1}. {service} ({count} lead{'s' if count != 1 else ''})"
                for i, (service, count) in enumerate(top_services)
            )
            lead_demand_block = (
                f"\n\n## Lead Demand Signals\n"
                f"The following services appear most frequently in inbound lead inquiries "
                f"(services_interest field from CRM):\n"
                f"{services_table}"
            )
        else:
            lead_demand_block = (
                "\n\n## Lead Demand Signals\n"
                "No services_interest data available in the CRM at this time."
            )

        prompt = f"""You are an SEO strategist with deep expertise in B2B IT services and
German/DACH digital marketing.

Your task is to analyse the current website content of Klaravex and the inbound
lead demand signals from their CRM to produce an actionable SEO opportunity report.

**About Klaravex:**
- Freelance IT consulting business in Berlin run by Anthony Stewart
- Enterprise background: Merrill Lynch, World Bank Group, FDH Aero
- Services: IT infrastructure, networking, security assessments, Microsoft 365, Azure,
  Meraki, Intune, Citrix ADC, VMware, hybrid cloud, managed services
- Target market: SMBs in Berlin and DACH region (10–500 employees)
- Website: bilingual EN/DE (WordPress + TranslatePress)

---

## Current Website Content ({len(page_snippets)} pages analysed)

{page_blocks}
{lead_demand_block}

---

## Your Task

Produce a structured Markdown SEO Opportunity Report covering:

### 1. High-Value Keyword Opportunities
Identify 10–15 specific keywords or keyword clusters that have strong commercial intent
and match the services offered. For each, note: search intent, estimated competition
(Low/Medium/High), and whether the site currently targets it.

### 2. Content Gaps
Which services that leads are requesting are poorly or not covered on the current website?
What pages are missing entirely?

### 3. Pages to Create or Expand
Specific recommendations for new landing pages or expansions to existing pages.
Include suggested page title, target keyword, and 2–3 bullet points on what to cover.

### 4. Title Tag & Meta Description Recommendations
Review the visible page titles and recommend improved versions for each page analysed.

### 5. Quick Wins (implement in < 1 week)
3–5 immediate changes that require minimal content effort but would improve ranking signals.

### 6. Long-Term Plays (1–3 months)
2–3 strategic content investments with the highest expected traffic/conversion return.

Be direct, specific, and commercially useful. Avoid generic SEO advice.
All keyword suggestions should be realistic for a boutique Berlin IT consultancy, not
an enterprise software vendor with a massive content team."""

        # ── Call Claude ───────────────────────────────────────────────────────
        log.info(
            "seo_opportunity.calling_claude",
            pages_fetched=len(page_snippets),
            lead_services=len(top_services),
        )
        try:
            anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await anthropic_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            try:
                from app.services.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=settings.anthropic_model,
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            report: str = response.content[0].text
        except Exception as exc:
            log.error("seo_opportunity.claude_error", error=str(exc), exc_info=True)
            return AgentResult.fail(error=f"Claude API call failed: {exc}")

        log.info(
            "seo_opportunity.report_generated",
            report_chars=len(report),
            pages_analysed=len(page_snippets),
        )

        # ── Optional email notification ───────────────────────────────────────
        emailed = False
        if notify and settings.approval_notify_email:
            services_text = (
                "\n".join(f"  {i + 1}. {s} ({c})" for i, (s, c) in enumerate(top_services))
                if top_services
                else "  No lead services data available."
            )
            pages_text = "\n".join(f"- {s['url']}" for s in page_snippets)
            body_text = (
                f"SEO Opportunity Report\n"
                f"Generated by Klaravex\n\n"
                f"Pages analysed:\n{pages_text}\n\n"
                f"Top lead service requests:\n{services_text}\n\n"
                f"{report}"
            )
            body_html = _markdown_to_simple_html(body_text)

            emailed = await send_transactional_email(
                settings,
                to_email=settings.approval_notify_email,
                to_name="Klaravex",
                subject=(
                    f"Klaravex: SEO Opportunity Report "
                    f"({len(page_snippets)} pages, {len(top_services)} lead services)"
                ),
                body_html=body_html,
                body_text=body_text,
            )
            log.info("seo_opportunity.email_sent", emailed=emailed)

        return AgentResult.ok(
            output={
                "report": report,
                "top_lead_services": top_services,
                "pages_analysed": len(page_snippets),
                "emailed": emailed,
            }
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _markdown_to_simple_html(text: str) -> str:
    """
    Minimal Markdown → HTML conversion for email body.
    Handles headers (###/##/#), bold (**), code fences, horizontal rules,
    list items, and blank lines.
    """
    lines: list[str] = []
    in_code = False

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if in_code:
                lines.append("</pre>")
                in_code = False
            else:
                lines.append("<pre style='background:#f4f4f4;padding:8px;'>")
                in_code = True
            continue

        if in_code:
            lines.append(line)
            continue

        if line.startswith("### "):
            lines.append(f"<h3>{_escape_html(line[4:])}</h3>")
        elif line.startswith("## "):
            lines.append(f"<h2>{_escape_html(line[3:])}</h2>")
        elif line.startswith("# "):
            lines.append(f"<h1>{_escape_html(line[2:])}</h1>")
        elif line.startswith("---"):
            lines.append("<hr>")
        elif line.startswith("- ") or line.startswith("* "):
            content = _inline_markdown(_escape_html(line[2:]))
            lines.append(f"<li>{content}</li>")
        elif line.strip() == "":
            lines.append("<br>")
        else:
            lines.append(f"<p>{_inline_markdown(_escape_html(line))}</p>")

    return (
        "<html><body style='font-family:sans-serif;max-width:800px;margin:auto;'>"
        + "\n".join(lines)
        + "</body></html>"
    )


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline_markdown(text: str) -> str:
    """Convert **bold** markers to <strong> tags."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
