"""
H10 — KB ingestion CSS-stripping tests.

Verifies _clean_html() in infra/klara.handlers/lib/kb.py removes <style>,
<script>, and HTML tags so embeddings + chunks never carry CSS gibberish
that gets surfaced as the "best match" in chat replies.

Run:
    python3 -m unittest infra.klara.handlers.tests.test_kb_clean
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

# Make "infra" importable from project root.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _load_kb():
    """Load lib/kb.py WITHOUT executing the full `from .db import get_pool`
    side effects. We synthesize a minimal `.db` stub then load the module.
    """
    kb_path = PROJECT_ROOT / "infra" / "klara.handlers" / "lib" / "kb.py"

    # Build stand-in parent packages so the relative `.db` import resolves.
    import types

    pkg_loki = types.ModuleType("klx_loki_handlers")
    pkg_loki.__path__ = []  # type: ignore[attr-defined]
    sys.modules.setdefault("klx_loki_handlers", pkg_loki)

    pkg_lib = types.ModuleType("klx_loki_handlers.lib")
    pkg_lib.__path__ = []  # type: ignore[attr-defined]
    sys.modules.setdefault("klx_loki_handlers.lib", pkg_lib)

    db_stub = types.ModuleType("klx_loki_handlers.lib.db")

    async def _stub_get_pool():  # pragma: no cover - never called in these tests
        raise RuntimeError("get_pool stubbed out for offline test")

    db_stub.get_pool = _stub_get_pool  # type: ignore[attr-defined]
    sys.modules["klx_loki_handlers.lib.db"] = db_stub

    spec = importlib.util.spec_from_file_location(
        "klx_loki_handlers.lib.kb",
        kb_path,
    )
    assert spec and spec.loader, "could not build spec for kb.py"
    module = importlib.util.module_from_spec(spec)
    sys.modules["klx_loki_handlers.lib.kb"] = module
    spec.loader.exec_module(module)
    return module


KB = _load_kb()


# Realistic WP-rendered HTML observed in production (truncated for readability).
SAMPLE_HTML = """
<style>
    body { max-width: 860px; margin: 0 auto; padding: 0 24px; }
    .kba-section { padding: 64px 0 48px; background: #fafafa; }
    .kba-section h2 { color: #1a1a1a; font-size: 28px; }
</style>
<script>
    var trackingId = "GA-12345";
    window.dataLayer = window.dataLayer || [];
    function gtag() { dataLayer.push(arguments); }
</script>
<!-- conditional CSS dropped by browsers but not by naive scrapers -->
<div class="kba-section">
    <h2>How to fix Wi-Fi connection drops</h2>
    <p>If your wireless network keeps disconnecting, start by restarting
    your router and checking for firmware updates from the vendor.</p>
    <p>If the problem persists, run an Ookla speed test and contact
    Klaravex support with the result.</p>
</div>
<script type="application/ld+json">{"@context":"https://schema.org"}</script>
"""

REAL_TEXT_FRAGMENT = "If your wireless network keeps disconnecting"
ANOTHER_REAL_FRAGMENT = "Ookla speed test"
CSS_PROPERTY_BLACKLIST = ("max-width", "padding", "margin", "font-size", "background")
CSS_CHAR_BLACKLIST = ("{", "}", ";", "<", ">")


class CleanHtmlTests(unittest.TestCase):
    def test_strips_style_block_completely(self):
        out = KB._clean_html(SAMPLE_HTML)
        self.assertNotIn(".kba-section", out)
        self.assertNotIn("max-width", out)
        self.assertNotIn("860px", out)

    def test_strips_script_block_completely(self):
        out = KB._clean_html(SAMPLE_HTML)
        self.assertNotIn("trackingId", out)
        self.assertNotIn("dataLayer", out)
        self.assertNotIn("@context", out)

    def test_no_html_braces_or_semicolons(self):
        out = KB._clean_html(SAMPLE_HTML)
        for ch in CSS_CHAR_BLACKLIST:
            self.assertNotIn(ch, out, f"forbidden char {ch!r} leaked: {out[:200]!r}")

    def test_no_css_property_names(self):
        out = KB._clean_html(SAMPLE_HTML).lower()
        for prop in CSS_PROPERTY_BLACKLIST:
            self.assertNotIn(prop, out, f"CSS prop {prop!r} leaked: {out[:200]!r}")

    def test_real_text_preserved(self):
        out = KB._clean_html(SAMPLE_HTML)
        self.assertIn(REAL_TEXT_FRAGMENT, out)
        self.assertIn(ANOTHER_REAL_FRAGMENT, out)

    def test_whitespace_collapsed(self):
        out = KB._clean_html(SAMPLE_HTML)
        # No long runs of whitespace.
        self.assertNotIn("   ", out)
        # No tabs or newlines in final output.
        self.assertNotIn("\n", out)
        self.assertNotIn("\t", out)

    def test_handles_empty_input(self):
        self.assertEqual(KB._clean_html(""), "")
        self.assertEqual(KB._clean_html(None), "")  # type: ignore[arg-type]

    def test_handles_plain_text(self):
        self.assertEqual(
            KB._clean_html("Just some plain text."),
            "Just some plain text.",
        )

    def test_entities_unescaped(self):
        out = KB._clean_html("<p>5 &gt; 3 &amp; safe</p>")
        self.assertIn("5", out)
        self.assertIn("3", out)
        self.assertIn("safe", out)

    def test_legacy_alias_routes_through_clean(self):
        # _html_to_text used to leave <style> contents — verify it now strips.
        out = KB._html_to_text(SAMPLE_HTML)
        self.assertNotIn("max-width", out)
        self.assertIn(REAL_TEXT_FRAGMENT, out)


if __name__ == "__main__":
    unittest.main()
