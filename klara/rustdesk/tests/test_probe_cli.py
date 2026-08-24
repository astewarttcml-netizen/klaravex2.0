"""Tests for G34.6 dry-run CLI --probe flag.

The --probe path must short-circuit BEFORE create_session/consent/recording,
so operators can verify shim configuration on a new host without producing
a customer-facing audit row. These tests assert:

  1. --probe --prefer-shim=no exits 0, prints kind="stub", does no I/O.
  2. --probe --prefer-shim=yes with a fake binary path exits 2 + reports
     "error" without spawning a session.
  3. --probe --prefer-shim=auto with KLX_RDSHIM_BIN unset reports "stub".
  4. --probe with KLX_RDSHIM_BIN set to a spawnable Python mock shim
     reports kind="shim" and returns the binary path.

Run: `python3 -m pytest infra/rustdesk_controller/tests -q` from repo root.
"""

from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import __main__ as cli  # noqa: E402
from rustdesk_controller.factory import SHIM_ENV_VAR  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────


def _run_main(argv: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(argv)
    raw = buf.getvalue().strip()
    assert raw, "probe should always print JSON"
    return rc, json.loads(raw)


def _write_mock_shim(tmp_path: Path) -> Path:
    """Write a Python script that talks the v0 hello handshake then exits.

    Cannot use a `#!/usr/bin/env python3` shebang inside the sandboxed
    temp dir on macOS (Mistake #7 — "Exec format error"). Instead we
    invoke `sys.executable <script>` via $KLX_RDSHIM_BIN pointing at a
    one-line wrapper. The wrapper itself just exec's sys.executable.
    """
    script = tmp_path / "mock_shim.py"
    script.write_text(
        "import json, sys\n"
        "print(json.dumps({"
        "\"kind\":\"hello\","
        "\"shim_version\":\"klx-rdshim 0.1.0\","
        "\"librustdesk_commit\":\"mock-probe\""
        "}), flush=True)\n"
        "for line in sys.stdin:\n"
        "    try:\n"
        "        msg = json.loads(line)\n"
        "    except Exception:\n"
        "        continue\n"
        "    if msg.get('kind') == 'disconnect':\n"
        "        break\n"
    )
    return script


# ── test cases ─────────────────────────────────────────────────────────────


def test_probe_prefer_shim_no_returns_stub_with_no_io(monkeypatch):
    """--probe --prefer-shim=no must use the stub and report it as such."""
    monkeypatch.delenv(SHIM_ENV_VAR, raising=False)
    rc, report = _run_main(["--probe", "--prefer-shim", "no"])
    assert rc == 0
    assert report["mode"] == "probe"
    assert report["ok"] is True
    assert report["shim_configured"] is False
    assert report["transport"]["kind"] == "stub"
    assert report["transport"]["binary"] is None
    assert "not set" in report["transport"]["reason"]


def test_probe_auto_with_env_unset_reports_stub(monkeypatch):
    """Default --prefer-shim=auto with KLX_RDSHIM_BIN unset = stub."""
    monkeypatch.delenv(SHIM_ENV_VAR, raising=False)
    rc, report = _run_main(["--probe"])
    assert rc == 0
    assert report["transport"]["kind"] == "stub"
    assert report["shim_configured"] is False


def test_probe_prefer_shim_yes_with_missing_binary_reports_error(monkeypatch):
    """Forcing the shim with a non-existent binary exits 2 + reports error.

    Operators rely on this exit code in CI to fail fast when the shim is
    misconfigured, rather than discovering it at session-start time.
    """
    monkeypatch.delenv(SHIM_ENV_VAR, raising=False)
    rc, report = _run_main([
        "--probe",
        "--prefer-shim", "yes",
        "--shim-binary", "/nonexistent/klx-rdshim-does-not-exist",
    ])
    assert rc == 2
    assert report["ok"] is False
    assert report["transport"]["kind"] == "error"
    assert "not found" in report["transport"]["reason"].lower() or \
           "FileNotFoundError" in report["transport"]["reason"] or \
           "no such file" in report["transport"]["reason"].lower()


def test_probe_with_real_mock_shim_reports_shim_kind(monkeypatch, tmp_path):
    """End-to-end: KLX_RDSHIM_BIN points at sys.executable, extra argv
    pushes the Python mock shim script as argv[1]. The probe should spawn,
    handshake, close, and report kind="shim"."""

    script = _write_mock_shim(tmp_path)

    # Use the build_shim_argv hook so [sys.executable, script_path] is the
    # actual spawn list. Easiest path: monkeypatch build_shim_argv to
    # always return that pair regardless of $KLX_RDSHIM_BIN. This sidesteps
    # the Mistake #7 shebang issue without changing the production code path.
    from rustdesk_controller import factory as factory_mod
    from rustdesk_controller import rdshim_ipc

    real_build = rdshim_ipc.build_shim_argv

    def _patched_build_shim_argv(binary=None, extra=()):  # noqa: D401
        return [sys.executable, str(script), *extra]

    monkeypatch.setattr(rdshim_ipc, "build_shim_argv", _patched_build_shim_argv)
    monkeypatch.setattr(factory_mod, "build_shim_argv", _patched_build_shim_argv)
    monkeypatch.setenv(SHIM_ENV_VAR, str(script))

    rc, report = _run_main(["--probe", "--prefer-shim", "yes"])

    # Restore (monkeypatch handles this, but be explicit).
    assert rc == 0, f"expected 0, got {rc}: {report}"
    assert report["ok"] is True
    assert report["transport"]["kind"] == "shim"
    assert report["transport"]["binary"] == sys.executable
    assert "handshake succeeded" in report["transport"]["reason"]


def test_probe_does_not_create_session_or_consent_record(monkeypatch, tmp_path):
    """Regression guard: --probe must NOT touch session.manager() or
    consent. A failure here means we accidentally re-introduced a code
    path that produces customer-facing audit rows during diagnostics."""

    monkeypatch.delenv(SHIM_ENV_VAR, raising=False)

    # Sentinel: replace manager().create_session with a method that fails
    # the test if invoked.
    from rustdesk_controller import session as session_mod

    real_create = session_mod.SessionManager.create_session

    def _explode(self, *a, **kw):  # noqa: D401
        raise AssertionError("--probe must not create a session")

    monkeypatch.setattr(session_mod.SessionManager, "create_session", _explode)
    try:
        rc, report = _run_main(["--probe", "--prefer-shim", "no"])
    finally:
        monkeypatch.setattr(session_mod.SessionManager, "create_session", real_create)

    assert rc == 0
    assert report["transport"]["kind"] == "stub"


def test_probe_report_includes_controller_version_and_timestamp(monkeypatch):
    """G34.6+: --probe must emit controller_version + probe_timestamp so
    support tickets correlate which controller version produced which
    transport selection at what wall-clock time. Without these fields,
    operators have to reconstruct the timeline from log timestamps
    after the fact — that loses the diagnostic context."""
    import datetime as _dt

    from rustdesk_controller import __version__ as expected_version

    monkeypatch.delenv(SHIM_ENV_VAR, raising=False)
    rc, report = _run_main(["--probe", "--prefer-shim", "no"])
    assert rc == 0

    assert report.get("controller_version") == expected_version, (
        "probe report must include the controller version so support "
        "tickets pin the diagnostic to a known release"
    )

    ts = report.get("probe_timestamp")
    assert isinstance(ts, str) and ts, "probe_timestamp must be a non-empty string"
    # ISO-8601 with Z suffix; must parse to a recent UTC instant.
    parsed = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, "probe_timestamp must carry tzinfo"
    delta = _dt.datetime.now(_dt.timezone.utc) - parsed
    assert _dt.timedelta(seconds=0) <= delta <= _dt.timedelta(seconds=30), (
        f"probe_timestamp should be within 30s of now, got delta={delta}"
    )
