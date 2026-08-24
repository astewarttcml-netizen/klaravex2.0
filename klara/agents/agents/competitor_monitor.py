"""
app/agents/competitor_monitor.py
──────────────────────────────────
CompetitorMonitorAgent — fetches public homepage content from competitor
IT-consulting websites and uses Claude to generate a structured competitive
intelligence report for Klaravex.

Permission level: P1 (read-only: external HTTP, Claude API, optional email).

Input keys:
  competitors   list[str]  — competitor URLs to analyse (max 5 evaluated).
                             If empty or absent the hardcoded default list is used.
  focus_areas   list[str]  — optional topics to guide analysis
                             e.g. ["pricing", "services", "USPs"].
  notify        bool       — send the report to approval_notify_email (default True).

Output keys:
  report             str        — Claude-generated Markdown competitive analysis.
  competitors_checked int       — number of URLs successfully fetched.
  failed_urls        list[str]  — URLs that could not be fetched (logged + skipped).
  emailed            bool       — whether the report email was sent.
"""
from __future__ import annotations

import re
from typing import Any

import httpx
import structlog
from anthropic import AsyncAnthropic

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.services.email_sender import send_transactional_email

logger = structlog.get_logger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_COMPETITORS: list[str] = [
    "https://example-itservice-berlin.de",   # replace with real competitor
    "https://example-it-support.de",         # replace with real competitor
    "https://example-managed-services.de",   # replace with real competitor
]

_MAX_COMPETITORS = 5
_TEXT_TRUNCATE = 3000   # chars of visible text per competitor page
_HTTP_TIMEOUT = 15.0
_HTTP_UA = "Mozilla/5.0 (compatible; LokiBot/1.0)"


def _extract_visible_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace to extract visible page text."""
    # Remove <script> and <style> blocks entirely (content is not visible text)
    text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace runs (including newlines) to a single space
    text = re.sub(r"\s+", " ", text).strip()
    return text


class CompetitorMonitorAgent(BaseAgent):
    """
    Fetches public homepages for a list of competitor IT-consulting websites,
    extracts visible text, and sends the full batch to Claude for competitive
    analysis.  Returns a Markdown report highlighting service offerings, pricing
    signals, USPs, gaps, and talking points for Klaravex.

    Competitor URLs that fail (timeout, HTTP 4xx/5xx, connection error) are
    logged as warnings and skipped — a partial result is always returned rather
    than failing the whole run.
    """

    name = "competitor_monitor"
    description = (
        "Fetches public data from competitor IT consulting websites and uses "
        "Claude to generate a brief competitive intelligence report for "
        "Klaravex."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )
        settings = context.settings

        # ── Resolve inputs ────────────────────────────────────────────────────
        raw_competitors: list[str] = input_data.get("competitors") or []
        if not raw_competitors:
            raw_competitors = _DEFAULT_COMPETITORS
            log.info("competitor_monitor.using_defaults", count=len(raw_competitors))

        # Cap at max to control API cost
        competitors: list[str] = raw_competitors[:_MAX_COMPETITORS]
        if len(raw_competitors) > _MAX_COMPETITORS:
            log.warning(
                "competitor_monitor.capped",
                original=len(raw_competitors),
                capped=_MAX_COMPETITORS,
            )

        focus_areas: list[str] = input_data.get("focus_areas") or []
        notify: bool = bool(input_data.get("notify", True))

        # ── Fetch competitor pages ────────────────────────────────────────────
        snippets: list[dict[str, str]] = []
        failed_urls: list[str] = []

        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _HTTP_UA},
        ) as client:
            for url in competitors:
                try:
                    log.debug("competitor_monitor.fetching", url=url)
                    resp = await client.get(url)
                    resp.raise_for_status()
                    visible = _extract_visible_text(resp.text)
                    snippets.append({
                        "url": url,
                        "text": visible[:_TEXT_TRUNCATE],
                    })
                    log.info(
                        "competitor_monitor.fetched",
                        url=url,
                        chars=min(len(visible), _TEXT_TRUNCATE),
                    )
                except httpx.TimeoutException:
                    log.warning("competitor_monitor.timeout", url=url)
                    failed_urls.append(url)
                except httpx.HTTPStatusError as exc:
                    log.warning(
                        "competitor_monitor.http_error",
                        url=url,
                        status=exc.response.status_code,
                    )
                    failed_urls.append(url)
                except Exception as exc:
                    log.warning("competitor_monitor.fetch_error", url=url, error=str(exc))
                    failed_urls.append(url)

        if not snippets:
            return AgentResult.fail(
                error="All competitor URLs failed to fetch. No data available for analysis.",
                failed_urls=failed_urls,
            )

        # ── Build Claude prompt ───────────────────────────────────────────────
        focus_block = ""
        if focus_areas:
            focus_list = "\n".join(f"- {area}" for area in focus_areas)
            focus_block = (
                f"\n\nPay particular attention to the following areas in your analysis:\n"
                f"{focus_list}"
            )

        competitor_blocks = "\n\n".join(
            f"--- COMPETITOR {i + 1}: {s['url']} ---\n{s['text']}"
            for i, s in enumerate(snippets)
        )

        prompt = f"""You are a competitive intelligence analyst for Klaravex (klaravex.de),
a freelance IT consulting business based in Berlin specialising in enterprise IT infrastructure,
networking, security, and managed services for SMBs.

Below is publicly visible homepage text scraped from {len(snippets)} competitor website(s).
Analyse each competitor and produce a structured Markdown report covering:

1. **Services Offered** — what IT services does each competitor advertise?
2. **Apparent USPs** — what unique positioning or differentiators do they emphasise?
3. **Pricing Signals** — any visible pricing, packages, or pricing philosophy?
4. **Target Market** — company sizes, industries, or customer segments they target?
5. **Gap Opportunities** — services or positioning angles that competitors lack and that
   Klaravex could exploit?
6. **Recommended Talking Points** — 3–5 concrete talking points Klaravex should
   emphasise when competing with these players?{focus_block}

Be direct and commercially useful. Format as clean Markdown with headers and bullet points.
If a competitor's content is sparse or generic, note that explicitly.

---

{competitor_blocks}

---

Klaravex context: Anthony Stewart, senior IT consultant with enterprise background
(Merrill Lynch, World Bank Group, FDH Aero). Services: IT infrastructure, networking,
security assessments, Microsoft 365, Azure, Meraki, Intune, Citrix ADC, VMware.
Location: Berlin. Bilingual: EN/DE. Target: SMBs in Berlin and DACH region."""

        # ── Call Claude ───────────────────────────────────────────────────────
        log.info("competitor_monitor.calling_claude", competitors_fetched=len(snippets))
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
            log.error("competitor_monitor.claude_error", error=str(exc), exc_info=True)
            return AgentResult.fail(error=f"Claude API call failed: {exc}")

        log.info(
            "competitor_monitor.report_generated",
            report_chars=len(report),
            competitors_checked=len(snippets),
            failed=len(failed_urls),
        )

        # ── Optional email notification ───────────────────────────────────────
        emailed = False
        if notify and settings.approval_notify_email:
            competitor_list_text = "\n".join(f"- {s['url']}" for s in snippets)
            failed_text = (
                ("\n\nFailed URLs (skipped):\n" + "\n".join(f"- {u}" for u in failed_urls))
                if failed_urls
                else ""
            )
            body_text = (
                f"Competitive Intelligence Report\n"
                f"Generated by Klaravex\n\n"
                f"Competitors analysed:\n{competitor_list_text}"
                f"{failed_text}\n\n"
                f"{report}"
            )
            body_html = _markdown_to_simple_html(body_text)

            emailed = await send_transactional_email(
                settings,
                to_email=settings.approval_notify_email,
                to_name="Klaravex",
                subject=f"Klaravex: Competitive Intelligence Report ({len(snippets)} competitors)",
                body_html=body_html,
                body_text=body_text,
            )
            log.info("competitor_monitor.email_sent", emailed=emailed)

        return AgentResult.ok(
            output={
                "report": report,
                "competitors_checked": len(snippets),
                "failed_urls": failed_urls,
                "emailed": emailed,
            }
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _markdown_to_simple_html(text: str) -> str:
    """
    Minimal Markdown → HTML conversion suitable for email body.
    Handles headers (##), bold (**), code fences, and newlines only —
    avoids pulling in a third-party markdown library.
    """
    lines: list[str] = []
    in_code = False

    for line in text.split("\n"):
        # Code fence toggle
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

        # Headers
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
    """Convert **bold** inline markers to <strong> tags."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
