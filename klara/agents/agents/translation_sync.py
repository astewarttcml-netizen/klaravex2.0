"""
app/agents/translation_sync.py
────────────────────────────────
TranslationSyncAgent — P2 read-only maintenance scan.

Fetches each /de/ page on klaravex.de, parses HTML with
BeautifulSoup, and flags text blocks that appear to be untranslated English.

Detection heuristic (per block):
  - English signal:  count of common English function words in the block text
  - German signal:   count of German-specific patterns (umlauts ä/ö/ü/ß +
                     conjunctions weil/und/oder/dass/ist/sind/für)
  - Flag condition:  english_word_count >= 5 AND german_indicator_count < 3

All results are written to translation_audit_log, grouped by audit_run_id.
After scanning, an HTML email summary is sent to the owner (approval_notify_email).

No writes to WordPress — this is strictly a read-only diagnostic.

Permissions: P2 — no approval gate, auto-executes on request.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import NamedTuple
from uuid import uuid4

import structlog

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.translation_audit import TranslationAuditEntry
from app.services.email_sender import send_transactional_email

logger = structlog.get_logger(__name__)

# ── Pages to scan ─────────────────────────────────────────────────────────────

DE_PAGES: list[str] = [
    "https://klaravex.de/de/",
    "https://klaravex.de/de/ueber-uns/",        # WP page ID 121 — renamed from /de/about/ 2026-05-14
    "https://klaravex.de/de/dienstleistungen/", # WP page ID 120 — renamed from /de/services/ 2026-05-14
    "https://klaravex.de/de/preisgestaltung/",  # WP page ID 269 — created 2026-05-14
    "https://klaravex.de/de/kontakt/",          # WP page ID 122 — renamed from /de/contact/ 2026-05-14
]

# Tags whose text content is inspected for language
CONTENT_TAGS: tuple[str, ...] = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td")

# ── Detection vocabulary ──────────────────────────────────────────────────────

# Common English function words — single-word token matches, word-boundary anchored
_ENGLISH_WORDS: frozenset[str] = frozenset({
    "the", "and", "or", "for", "with", "your", "you", "that", "this",
    "are", "have", "will", "from", "not", "can", "also", "by", "an",
    "at", "be", "which", "as", "it", "we", "our", "all", "but",
})

# German-specific patterns: umlauts, eszett, and common German-only words
_GERMAN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[äöüÄÖÜß]"),
    re.compile(r"\b(weil|und|oder|dass|ist|sind|für)\b", re.IGNORECASE),
]

# Thresholds
_MIN_ENGLISH_WORDS: int = 5
_MAX_GERMAN_INDICATORS: int = 3   # flag if FEWER than this


# ── Internal result container ─────────────────────────────────────────────────

class BlockAnalysis(NamedTuple):
    page_url: str
    block_tag: str
    block_text_snippet: str
    english_word_count: int
    german_indicator_count: int
    flagged: bool


# ── Agent ─────────────────────────────────────────────────────────────────────

class TranslationSyncAgent(BaseAgent):
    name = "translation_sync"
    description = (
        "Scans /de/ pages on klaravex.de for untranslated English text blocks. "
        "Stores per-block results in translation_audit_log and emails a report to the owner. "
        "Read-only — no writes to WordPress."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        audit_run_id = str(uuid4())
        log = logger.bind(
            agent=self.name,
            audit_run_id=audit_run_id,
            request_id=context.request_id,
        )
        log.info("translation_sync.start", pages=len(DE_PAGES))

        # ── Lazy imports — kept here to avoid startup overhead ─────────────────
        try:
            import aiohttp
            from bs4 import BeautifulSoup
        except ImportError as exc:
            log.error("translation_sync.import_error", error=str(exc))
            return AgentResult.fail(
                f"Missing dependency: {exc}. "
                "Install aiohttp and beautifulsoup4 in requirements.txt."
            )

        # ── Fetch and analyse each page ───────────────────────────────────────
        all_analyses: list[BlockAnalysis] = []

        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; LokiTranslationBot/1.0; "
                "+https://klaravex.de)"
            ),
            "Accept-Language": "de-DE,de;q=0.9",
        }

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for page_url in DE_PAGES:
                page_log = log.bind(page_url=page_url)
                try:
                    async with session.get(page_url) as resp:
                        if resp.status != 200:
                            page_log.warning(
                                "translation_sync.page_fetch_error",
                                status=resp.status,
                            )
                            continue
                        html = await resp.text(encoding="utf-8", errors="replace")

                    analyses = _analyse_page(page_url, html)
                    page_log.info(
                        "translation_sync.page_scanned",
                        blocks_inspected=len(analyses),
                        blocks_flagged=sum(1 for a in analyses if a.flagged),
                    )
                    all_analyses.extend(analyses)

                except aiohttp.ClientError as exc:
                    page_log.error("translation_sync.fetch_failed", error=str(exc))
                    continue

        # ── Persist results ───────────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        entries: list[TranslationAuditEntry] = []

        for analysis in all_analyses:
            entry = TranslationAuditEntry(
                id=str(uuid4()),
                page_url=analysis.page_url,
                block_tag=analysis.block_tag,
                block_text_snippet=analysis.block_text_snippet,
                english_word_count=analysis.english_word_count,
                german_indicator_count=analysis.german_indicator_count,
                flagged=analysis.flagged,
                audit_run_id=audit_run_id,
                detected_at=now,
            )
            context.db.add(entry)
            entries.append(entry)

        await context.db.flush()

        flagged = [a for a in all_analyses if a.flagged]
        log.info(
            "translation_sync.persisted",
            total_blocks=len(all_analyses),
            flagged_blocks=len(flagged),
        )

        # ── Send email report ─────────────────────────────────────────────────
        email_sent = False
        if flagged:
            subject = (
                f"Translation Audit: {len(flagged)} untranslated "
                f"block{'s' if len(flagged) != 1 else ''} found on /de/"
            )
            body_html = _build_email_html(flagged, audit_run_id, now)
            body_text = _build_email_text(flagged, audit_run_id, now)

            recipient = context.settings.approval_notify_email
            email_sent = await send_transactional_email(
                context.settings,
                to_email=recipient,
                to_name="Anthony",
                subject=subject,
                body_html=body_html,
                body_text=body_text,
            )
            log.info(
                "translation_sync.email_sent",
                to=recipient,
                flagged=len(flagged),
                sent=email_sent,
            )
        else:
            log.info("translation_sync.no_issues_found", pages_scanned=len(DE_PAGES))

        return AgentResult.ok(
            output={
                "audit_run_id": audit_run_id,
                "pages_scanned": len(DE_PAGES),
                "total_blocks_inspected": len(all_analyses),
                "flagged_blocks": len(flagged),
                "email_sent": email_sent,
            }
        )


# ── Page analysis ─────────────────────────────────────────────────────────────

def _analyse_page(page_url: str, html: str) -> list[BlockAnalysis]:
    """Parse HTML and return a BlockAnalysis for every content block found."""
    from bs4 import BeautifulSoup  # local import — module may not be installed

    soup = BeautifulSoup(html, "html.parser")

    # Remove script, style, noscript, nav, footer, header noise
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()

    results: list[BlockAnalysis] = []

    for element in soup.find_all(CONTENT_TAGS):
        raw_text = element.get_text(separator=" ", strip=True)

        # Skip very short blocks — they're usually UI labels or icon text
        if len(raw_text) < 20:
            continue

        eng_count = _count_english_words(raw_text)
        de_count = _count_german_indicators(raw_text)
        flagged = eng_count >= _MIN_ENGLISH_WORDS and de_count < _MAX_GERMAN_INDICATORS

        results.append(
            BlockAnalysis(
                page_url=page_url,
                block_tag=element.name,
                block_text_snippet=raw_text[:500],
                english_word_count=eng_count,
                german_indicator_count=de_count,
                flagged=flagged,
            )
        )

    return results


def _count_english_words(text: str) -> int:
    """Count how many English function words appear in text (word-boundary aware)."""
    tokens = re.findall(r"\b\w+\b", text.lower())
    return sum(1 for t in tokens if t in _ENGLISH_WORDS)


def _count_german_indicators(text: str) -> int:
    """Count German-specific pattern matches in text."""
    total = 0
    for pattern in _GERMAN_PATTERNS:
        total += len(pattern.findall(text))
    return total


# ── Email builders ────────────────────────────────────────────────────────────

def _build_email_html(
    flagged: list[BlockAnalysis],
    audit_run_id: str,
    run_at: datetime,
) -> str:
    rows = ""
    for block in flagged:
        snippet_escaped = (
            block.block_text_snippet
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        rows += (
            f"<tr>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;font-size:13px'>{block.page_url}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;font-size:13px'>&lt;{block.block_tag}&gt;</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;font-size:13px'>{snippet_escaped[:200]}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;text-align:center;font-size:13px'>"
            f"{block.english_word_count}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;text-align:center;font-size:13px'>"
            f"{block.german_indicator_count}</td>"
            f"</tr>"
        )

    return f"""
<html>
<body style="font-family:Arial,sans-serif;color:#333;max-width:900px;margin:0 auto">
  <h2 style="color:#1a1a2e">Translation Audit Report — /de/ Pages</h2>
  <p>
    <strong>{len(flagged)}</strong> block{'s' if len(flagged) != 1 else ''} appear
    to contain untranslated English text.<br>
    <small>Audit run: <code>{audit_run_id}</code> &nbsp;|&nbsp;
    Scanned: {run_at.strftime('%Y-%m-%d %H:%M UTC')}</small>
  </p>
  <table style="border-collapse:collapse;width:100%">
    <thead>
      <tr style="background:#1a1a2e;color:#fff">
        <th style="padding:8px 10px;text-align:left">Page URL</th>
        <th style="padding:8px 10px;text-align:left">Tag</th>
        <th style="padding:8px 10px;text-align:left">Snippet</th>
        <th style="padding:8px 10px;text-align:center">EN words</th>
        <th style="padding:8px 10px;text-align:center">DE signals</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  <p style="margin-top:20px;font-size:12px;color:#666">
    Fix flagged blocks in TranslatePress or WPCode, then re-run the audit
    via <code>POST /api/v1/admin/translation-sync/audit</code> to confirm.
  </p>
</body>
</html>
""".strip()


def _build_email_text(
    flagged: list[BlockAnalysis],
    audit_run_id: str,
    run_at: datetime,
) -> str:
    lines = [
        "Translation Audit Report — /de/ Pages",
        "=" * 40,
        f"Flagged blocks: {len(flagged)}",
        f"Audit run:      {audit_run_id}",
        f"Scanned:        {run_at.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"{'Page URL':<50} {'Tag':<6} {'EN words':>8}  {'DE signals':>10}  Snippet",
        "-" * 100,
    ]
    for block in flagged:
        lines.append(
            f"{block.page_url:<50} "
            f"<{block.block_tag}> "
            f"{block.english_word_count:>8}  "
            f"{block.german_indicator_count:>10}  "
            f"{block.block_text_snippet[:80]}"
        )
    lines += [
        "",
        "Fix flagged blocks in TranslatePress or WPCode, then re-run the audit.",
    ]
    return "\n".join(lines)
