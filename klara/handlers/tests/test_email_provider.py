"""Unit tests for lib/email.py provider dispatch (T14.2).

Verifies:
- EMAIL_PROVIDER=graph routes to Graph backend.
- EMAIL_PROVIDER=smtp routes to SMTP backend.
- Unknown EMAIL_PROVIDER values fall back to Graph (with a warning).
- send_email() swallows backend exceptions and never raises.

Run: pytest infra/klara.handlers/tests/test_email_provider.py -v
Or:  python -m unittest infra.klara.handlers.tests.test_email_provider
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _reload_email(env: dict[str, str]):
    """Reload lib.email with a patched os.environ so module-level constants update."""
    import os
    with patch.dict(os.environ, env, clear=False):
        if "infra.klara.handlers.lib.email" in sys.modules:
            return importlib.reload(sys.modules["infra.klara.handlers.lib.email"])
        return importlib.import_module("infra.klara.handlers.lib.email")


class TestProviderResolution(unittest.TestCase):
    def test_default_provider_is_graph(self):
        mod = _reload_email({"EMAIL_PROVIDER": "graph"})
        self.assertEqual(mod._resolve_provider(), "graph")

    def test_smtp_provider_selected(self):
        mod = _reload_email({"EMAIL_PROVIDER": "smtp"})
        self.assertEqual(mod._resolve_provider(), "smtp")

    def test_unknown_provider_falls_back_to_graph(self):
        mod = _reload_email({"EMAIL_PROVIDER": "ses"})
        with self.assertLogs("klaravex.email", level="WARNING"):
            self.assertEqual(mod._resolve_provider(), "graph")


class TestSendEmailDispatch(unittest.TestCase):
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)

    def test_graph_path_invoked_when_provider_graph(self):
        mod = _reload_email({"EMAIL_PROVIDER": "graph"})
        graph_mock = AsyncMock(return_value=True)
        smtp_mock = AsyncMock(return_value=True)
        with patch.object(mod, "_send_via_graph", graph_mock), \
             patch.object(mod, "_send_via_smtp", smtp_mock):
            self._run(mod.send_email("a@example.com", "Hi", "body"))
        graph_mock.assert_awaited_once()
        smtp_mock.assert_not_awaited()
        args = graph_mock.await_args
        self.assertEqual(args.args[0], ["a@example.com"])
        self.assertEqual(args.args[1], "Hi")

    def test_smtp_path_invoked_when_provider_smtp(self):
        mod = _reload_email({"EMAIL_PROVIDER": "smtp"})
        graph_mock = AsyncMock(return_value=True)
        smtp_mock = AsyncMock(return_value=True)
        with patch.object(mod, "_send_via_graph", graph_mock), \
             patch.object(mod, "_send_via_smtp", smtp_mock):
            self._run(mod.send_email(["a@example.com", "b@example.com"], "S", "B"))
        smtp_mock.assert_awaited_once()
        graph_mock.assert_not_awaited()
        args = smtp_mock.await_args
        self.assertEqual(args.args[0], ["a@example.com", "b@example.com"])

    def test_send_email_swallows_backend_exception(self):
        mod = _reload_email({"EMAIL_PROVIDER": "graph"})
        graph_mock = AsyncMock(side_effect=RuntimeError("Graph 500"))
        with patch.object(mod, "_send_via_graph", graph_mock):
            with self.assertLogs("klaravex.email", level="WARNING"):
                # Must not raise — magic-link flow tolerates send failure.
                self._run(mod.send_email("x@example.com", "S", "B"))

    def test_recipient_string_normalised_to_list(self):
        mod = _reload_email({"EMAIL_PROVIDER": "graph"})
        graph_mock = AsyncMock(return_value=True)
        with patch.object(mod, "_send_via_graph", graph_mock):
            self._run(mod.send_email("solo@example.com", "S", "B"))
        recipients = graph_mock.await_args.args[0]
        self.assertEqual(recipients, ["solo@example.com"])


class TestGraphBackendGuards(unittest.TestCase):
    def test_graph_skips_when_credentials_missing(self):
        mod = _reload_email({
            "EMAIL_PROVIDER": "graph",
            "MS_GRAPH_TENANT_ID": "",
            "MS_GRAPH_CLIENT_ID": "",
            "MS_GRAPH_CLIENT_SECRET": "",
        })
        with self.assertLogs("klaravex.email", level="WARNING"):
            ok = asyncio.run(mod._send_via_graph(["a@b.c"], "S", "B", None))
        self.assertFalse(ok)


class TestSmtpBackendGuards(unittest.TestCase):
    def test_smtp_skips_when_host_missing(self):
        mod = _reload_email({"EMAIL_PROVIDER": "smtp", "SMTP_HOST": ""})
        with self.assertLogs("klaravex.email", level="WARNING"):
            ok = asyncio.run(mod._send_via_smtp(["a@b.c"], "S", "B", None))
        self.assertFalse(ok)

    def test_smtp_builds_multipart_when_html_provided(self):
        mod = _reload_email({"EMAIL_PROVIDER": "smtp"})
        msg = mod._build_smtp_message(
            ["a@b.c"], "Subj", "plain body", "<p>html</p>",
        )
        self.assertEqual(msg["Subject"], "Subj")
        self.assertEqual(msg["To"], "a@b.c")
        self.assertTrue(msg.is_multipart())


if __name__ == "__main__":
    unittest.main()
