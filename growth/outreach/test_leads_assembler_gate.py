"""Assembler must emit a gate-APPROVED leads draft even when scrapers dump noise."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from growth.gatekeeper.adjudicate import evaluate
from growth.outreach.leads_assembler import assemble_from_research

NOISY_BUNDLE = """## Signals
| signal_id | scraper | excerpt |
|-----------|---------|---------|
| web-01 | web_scanner | Missing HSTS header (Strict-Transport-Security) |
| soc-04 | social_hook | News: "He Said, “I Want to Live.” But He Refused Care" |
| news-04 | news_mentions | News: "I Profiled Lindy West After Her Marriage Memoir" |
| forum-01 | forum_mentions | HackerNews: "Ask HN: How do I get press coverage for my startup as a high schooler?" |
| tech-01 | tech_stack | Cloud: Azure |
"""


def _research_dir(tmp: Path) -> Path:
    slug = "acme-clinic-acmeclinic-com"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / slug).mkdir()
    (tmp / slug / "bundle.summary.md").write_text(NOISY_BUNDLE, encoding="utf-8")
    (tmp / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "test-run",
                "enriched": [
                    {
                        "slug": slug,
                        "research_confidence": 0.6,
                        "prospect": {
                            "company_name": "Acme Clinic",
                            "domain": "acmeclinic.com",
                            "contact_first_name": "Pat",
                            "contact_last_name": "Lee",
                            "contact_email": "pat@acmeclinic.com",
                            "contact_title": "Office Manager",
                            "city": "Austin",
                            "state": "Texas",
                            "vertical": "medical",
                        },
                    }
                ],
                "skipped": [],
            }
        ),
        encoding="utf-8",
    )
    return tmp


class LeadsAssemblerGateTests(unittest.TestCase):
    def test_noisy_research_assembles_to_approved_draft(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            research = _research_dir(tmp / "research")
            out = tmp / "outbox.md"
            result = assemble_from_research(research_dir=research, output_path=out, run_id="test-run")
            self.assertEqual(result["drafted_count"], 1)
            body = out.read_text(encoding="utf-8")
            self.assertNotIn("Apollo", body)
            self.assertNotIn("Hunter", body)
            self.assertNotIn("Azure", body)
            self.assertNotIn("I Want to Live", body)
            self.assertNotIn("high schooler", body)
            self.assertIn("Missing HSTS header", body)
            verdict = evaluate(body, "leads")
            self.assertEqual(verdict["status"], "APPROVED", verdict)

    def test_apollo_in_draft_is_rejected(self) -> None:
        text = (
            "# Leads\n\n## Prospect Shortlist\n\n- **Acme** — medical; drafted; source: Apollo\n\n"
            "## RESEARCH — prospect-1-acme\n**Confidence Score:** 0.50\n\n"
            "**Signal Table:**\n| signal_id | scraper | excerpt |\n| web-01 | web_scanner | Missing HSTS |\n\n"
            "## OUTREACH — prospect-1-acme\n\n**Subject Line:** Hello\n\n"
            "**Email Body:**\n\nDear Pat,\n\nKlaravex found a gap [web-01].\n\nklaravex.com\n"
        )
        verdict = evaluate(text, "leads")
        self.assertEqual(verdict["status"], "REJECTED")
        self.assertEqual(verdict["checks"]["Language"][0], "FAIL")


if __name__ == "__main__":
    unittest.main()
