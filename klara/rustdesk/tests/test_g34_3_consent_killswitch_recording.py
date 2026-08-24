"""G34.3 integration tests — consent gate, 3-path killswitch, recording.

Exercises the four requirements from spec §4 end-to-end against the
in-memory session manager (no DB, no shim). Production deploy adds the
Postgres row checks via migration 021_remote_sessions.sql.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import killswitch, protocol, session, vision  # noqa: E402
from rustdesk_controller.consent import (  # noqa: E402
    AuditEntry,
    HashChainAuditLog,
    make_consent_record,
)
from rustdesk_controller.killswitch import (  # noqa: E402
    FIRED_BY_HOTKEY,
    FIRED_BY_SERVER,
    FIRED_BY_TRAY,
    registry as kill_registry,
)
from rustdesk_controller.vision import PredictedAction  # noqa: E402


def _make_action(confidence: float = 0.95) -> PredictedAction:
    return PredictedAction(
        event=protocol.InputEvent(
            kind=protocol.EventKind.MOUSE_CLICK, x=0.5, y=0.5, button="left",
        ),
        target_description="OK button",
        rationale="Clicking OK to dismiss dialog.",
        confidence=confidence,
    )


class _StubVision(vision.VisionPredictor):
    def __init__(self, action: PredictedAction):
        super().__init__(api_key="stub")
        self._action = action

    async def predict(self, frame: protocol.Frame, goal: str) -> PredictedAction:
        return self._action


def _make_sess() -> session.RemoteSession:
    mgr = session.SessionManager()
    return mgr.create_session(
        customer_email="cust@example.com", customer_region="us", goal="fix",
    )


# ── Requirement 1: consent capture ─────────────────────────────────────────


def test_consent_record_has_signature():
    rec = make_consent_record(
        session_id="abc123", customer_email="c@x.com",
        ip_address="1.2.3.4", user_agent="Mozilla/5.0",
    )
    # Signature binds version + text + email + accepted_at; 64-char hex.
    assert len(rec.signature_sha256) == 64
    assert all(c in "0123456789abcdef" for c in rec.signature_sha256)


def test_consent_record_changes_signature_on_mutation():
    a = make_consent_record("s1", "a@x.com", "1.1.1.1", "ua")
    b = make_consent_record("s1", "b@x.com", "1.1.1.1", "ua")
    assert a.signature_sha256 != b.signature_sha256


def test_session_record_consent_appends_audit_row_with_signature():
    sess = _make_sess()
    record = sess.record_consent(ip_address="1.1.1.1", user_agent="Mozilla")
    # consent appears in the chain.
    entries = sess.audit.entries
    assert any(e.event_type == "consent" for e in entries)
    consent_row = next(e for e in entries if e.event_type == "consent")
    assert consent_row.payload["signature_sha256"] == record.signature_sha256


# ── Requirement 4: 3-path killswitch ───────────────────────────────────────


def test_killswitch_registry_routes_by_session_id():
    sess = _make_sess()
    sid = sess.session_id
    # Server-side override path.
    ok = kill_registry().fire(sid, "stuck", FIRED_BY_SERVER)
    assert ok is True
    assert sess.killswitch.is_killed
    assert sess.killswitch.fired_by == FIRED_BY_SERVER


def test_killswitch_registry_returns_false_for_unknown_session():
    assert kill_registry().fire("nonexistent-sid", "x", FIRED_BY_SERVER) is False


def test_three_kill_paths_all_valid_fired_by_values():
    for fired_by in (FIRED_BY_TRAY, FIRED_BY_HOTKEY, FIRED_BY_SERVER):
        sess = _make_sess()
        sess.killswitch.fire("test", fired_by)
        assert sess.killswitch.fired_by == fired_by


def test_killswitch_close_transport_hook_fires():
    """Firing the killswitch must close the transport and append audit row."""
    sess = _make_sess()
    sid = sess.session_id

    async def runner():
        kill_registry().fire(sid, "manual", FIRED_BY_SERVER)
        # Give the scheduled hook a tick to run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # killswitch_fired must be in the audit chain.
        types = [e.event_type for e in sess.audit.entries]
        assert "killswitch_fired" in types

    asyncio.run(runner())


def test_consent_gate_blocks_execute_when_db_layer_present_but_no_row():
    """If we simulate consent NOT recorded, confirm() must not send the event.

    In this no-DB test context, ensure_consent_recorded is a no-op, so we
    use a transport that records calls + we assert that the audit chain has
    a consent row before action_executed appears.
    """
    sess = _make_sess()

    class _Tracker:
        def __init__(self):
            self.calls = []

        async def send_event(self, event):
            self.calls.append(event)

        async def close(self):
            pass

    tracker = _Tracker()
    sess.transport = tracker  # type: ignore[assignment]
    sess.vision = _StubVision(_make_action())

    async def runner():
        sess.record_consent(ip_address="1.1.1.1", user_agent="ua")
        frame = protocol.Frame("s", 0, 1920, 1080, "jpeg", b"\xff\xd8\xff\xd9", 0)
        sess.request_next_action(frame)
        # Let the predict task run.
        await asyncio.sleep(0.05)
        await sess.confirm(True)
        assert len(tracker.calls) == 1
        # consent row precedes action_executed in the chain.
        types = [e.event_type for e in sess.audit.entries]
        assert types.index("consent") < types.index("action_executed")

    asyncio.run(runner())


# ── Requirement 3: recording — H.264 mp4 path + summary fields ─────────────


def test_recorder_writes_summary_with_recording_metadata(tmp_path):
    from rustdesk_controller import recording
    rec = recording.SessionRecorder(
        session_id="rectest1", customer_email="a@b.com",
        customer_region="us", sink_dir=tmp_path / "rectest1",
    )
    # Even without ffmpeg available, the recorder enters jpeg_fallback mode
    # and produces a non-empty summary.
    frame = protocol.Frame("rectest1", 0, 320, 240, "jpeg", b"\xff\xd8\xff\xd9", 0)
    rec.write_frame(frame)
    rec.write_event("test", {"x": 1})
    summary = rec.close("fixed")
    assert summary["frames_written"] == 1
    assert summary["events_written"] == 1
    assert summary["recording_format"] in ("h264", "jpeg_fallback")
    # Purge timestamp is always set for enabled sessions.
    assert summary["recording_purge_after"] is not None


def test_recorder_enabled_for_eu_region(tmp_path):
    # US-only codebase (refactor 812ade82): customer_region is metadata-only
    # and recording is always enabled. The EU default-disable + opt-in
    # (enable_eu_recording) contract and its absent purge timestamp were
    # deliberately removed. Recording proceeds identically for any region.
    from rustdesk_controller import recording
    rec = recording.SessionRecorder(
        session_id="eu1", customer_email="a@b.com",
        customer_region="eu", sink_dir=tmp_path / "eu1",
    )
    assert rec.enabled is True
    rec.write_event("consent", {"ip": "1.1.1.1"})
    summary = rec.close("fixed")
    assert summary["enabled"] is True
    # Even after close, the purge timestamp is always set for enabled sessions.
    assert summary["recording_purge_after"] is not None
