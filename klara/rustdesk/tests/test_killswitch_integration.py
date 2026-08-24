"""Integration tests for the 3 killswitch termination paths.

Verifies that customer_tray, customer_hotkey, and server_override all
terminate a session correctly, are idempotent, prevent further actions,
fire registered hooks, and race safely (only the first fire wins).

Run: `python3 -m pytest infra/rustdesk_controller/tests/test_killswitch_integration.py -q`
     from the repo root.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import killswitch, protocol, session, voice_tools  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_session(
    monkeypatch,
    *,
    session_id: str = "ks-int",
    with_frame: bool = False,
) -> tuple[session.SessionManager, session.RemoteSession]:
    """Create a SessionManager + RemoteSession and install it into voice_tools."""
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="test@example.com",
        customer_region="us",
        goal="fix wifi",
    )
    if with_frame:
        sess.cache_frame(
            protocol.Frame(
                session_id=sess.session_id,
                sequence=0,
                width=1024,
                height=768,
                codec="jpeg",
                payload=b"\x00",
                timestamp_ms=0,
            )
        )
    monkeypatch.setattr(session, "_manager", mgr, raising=False)
    return mgr, sess


# ── Path 1: customer_tray ────────────────────────────────────────────────────


def test_customer_tray_fires_killswitch(monkeypatch):
    """Path 1: customer clicks the STOP button in the tray."""
    _, sess = _make_session(monkeypatch)
    assert not sess.killswitch.is_killed

    sess.killswitch.fire(reason="customer_pressed_stop", fired_by="customer_tray")

    assert sess.killswitch.is_killed is True
    assert sess.killswitch.killed is True
    assert sess.killswitch.fired_by == "customer_tray"
    assert sess.killswitch.reason == "customer_pressed_stop"
    assert sess.killswitch.fired_at != ""


# ── Path 2: customer_hotkey ──────────────────────────────────────────────────


def test_customer_hotkey_fires_killswitch(monkeypatch):
    """Path 2: customer presses Ctrl+Shift+Escape."""
    _, sess = _make_session(monkeypatch)

    sess.killswitch.fire(reason="hotkey_escape", fired_by="customer_hotkey")

    assert sess.killswitch.is_killed is True
    assert sess.killswitch.fired_by == "customer_hotkey"
    assert sess.killswitch.reason == "hotkey_escape"


# ── Path 3: server_override ─────────────────────────────────────────────────


def test_server_override_fires_killswitch(monkeypatch):
    """Path 3: operator or API fires the kill via server_override."""
    _, sess = _make_session(monkeypatch)

    sess.killswitch.fire(reason="operator_abort", fired_by="server_override")

    assert sess.killswitch.is_killed is True
    assert sess.killswitch.fired_by == "server_override"
    assert sess.killswitch.reason == "operator_abort"


# ── Idempotency ──────────────────────────────────────────────────────────────


def test_fire_is_idempotent_second_call_is_noop(monkeypatch):
    """KillSwitch.fire() is idempotent — the second call must be a no-op
    preserving the original reason and fired_by."""
    _, sess = _make_session(monkeypatch)

    sess.killswitch.fire(reason="first_reason", fired_by="customer_tray")
    first_fired_at = sess.killswitch.fired_at

    sess.killswitch.fire(reason="second_reason", fired_by="server_override")

    assert sess.killswitch.reason == "first_reason"
    assert sess.killswitch.fired_by == "customer_tray"
    assert sess.killswitch.fired_at == first_fired_at


def test_idempotent_across_all_three_paths(monkeypatch):
    """All 3 paths fire in quick succession — only the first wins."""
    _, sess = _make_session(monkeypatch)

    sess.killswitch.fire(reason="tray_stop", fired_by="customer_tray")
    sess.killswitch.fire(reason="hotkey_stop", fired_by="customer_hotkey")
    sess.killswitch.fire(reason="server_stop", fired_by="server_override")

    assert sess.killswitch.reason == "tray_stop"
    assert sess.killswitch.fired_by == "customer_tray"


# ── Killed session blocks new actions ────────────────────────────────────────


def test_killed_session_next_screen_action_returns_killed(monkeypatch):
    """After killswitch fires, next_screen_action must return status=killed
    and must NOT dispatch a prediction."""
    _, sess = _make_session(monkeypatch, with_frame=True)

    sess.killswitch.fire(reason="customer_abort", fired_by="customer_tray")

    # Trap: if request_next_action runs, explode — it must be blocked.
    def _explode(frame):
        raise AssertionError("request_next_action must not run on killed session")

    monkeypatch.setattr(sess, "request_next_action", _explode)

    req = voice_tools.NextActionRequest(session_id=sess.session_id)
    result = asyncio.run(voice_tools.next_screen_action(req))

    assert result["status"] == "killed"
    assert result["awaiting_confirmation"] is False
    assert result["reason"] == "customer_abort"


def test_killed_session_request_next_action_raises(monkeypatch):
    """Direct call to request_next_action on a killed session raises."""
    _, sess = _make_session(monkeypatch, with_frame=True)
    sess.killswitch.fire(reason="stopped", fired_by="server_override")

    with pytest.raises(RuntimeError, match="session killed"):
        sess.request_next_action(sess.latest_frame)


# ── Kill hook mechanism ──────────────────────────────────────────────────────


def test_kill_hook_is_called_on_fire(monkeypatch):
    """register_hook() adds a callback. fire() must invoke it with the
    correct (session_id, reason, fired_by) triple."""
    _, sess = _make_session(monkeypatch)
    hook_calls: list[tuple[str, str, str]] = []

    async def _hook(sid: str, reason: str, fired_by: str) -> None:
        hook_calls.append((sid, reason, fired_by))

    sess.killswitch.register_hook(_hook)

    async def _run():
        sess.killswitch.fire(reason="hook_test", fired_by="customer_hotkey")
        # Let the scheduled hook task run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert len(hook_calls) == 1
    assert hook_calls[0] == (sess.session_id, "hook_test", "customer_hotkey")


def test_multiple_hooks_all_called_in_order(monkeypatch):
    """Multiple hooks registered — all must fire in registration order."""
    _, sess = _make_session(monkeypatch)
    call_order: list[str] = []

    async def _hook_a(sid, reason, fired_by):
        call_order.append("a")

    async def _hook_b(sid, reason, fired_by):
        call_order.append("b")

    sess.killswitch.register_hook(_hook_a)
    sess.killswitch.register_hook(_hook_b)

    async def _run():
        sess.killswitch.fire(reason="order_test", fired_by="server_override")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert call_order == ["a", "b"]


def test_misbehaving_hook_does_not_block_others(monkeypatch):
    """A hook that raises must not prevent subsequent hooks from running."""
    _, sess = _make_session(monkeypatch)
    reached: list[str] = []

    async def _exploding_hook(sid, reason, fired_by):
        raise RuntimeError("hook went boom")

    async def _good_hook(sid, reason, fired_by):
        reached.append("good")

    sess.killswitch.register_hook(_exploding_hook)
    sess.killswitch.register_hook(_good_hook)

    async def _run():
        sess.killswitch.fire(reason="resilience_test", fired_by="customer_tray")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert "good" in reached


def test_hook_not_called_on_second_fire(monkeypatch):
    """Hooks must NOT re-fire on idempotent second calls."""
    _, sess = _make_session(monkeypatch)
    hook_count = 0

    async def _counting_hook(sid, reason, fired_by):
        nonlocal hook_count
        hook_count += 1

    sess.killswitch.register_hook(_counting_hook)

    async def _run():
        sess.killswitch.fire(reason="first", fired_by="customer_tray")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        sess.killswitch.fire(reason="second", fired_by="server_override")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert hook_count == 1


# ── Race safety: 3 paths fire concurrently, no double-billing ────────────────


def test_three_paths_race_only_first_fire_wins(monkeypatch):
    """Simulate all 3 kill paths racing concurrently. Only the first one
    to call fire() sets the state; subsequent calls are no-ops.
    Hooks fire exactly once."""
    _, sess = _make_session(monkeypatch)
    hook_invocations: list[tuple[str, str]] = []

    async def _tracking_hook(sid, reason, fired_by):
        hook_invocations.append((reason, fired_by))

    sess.killswitch.register_hook(_tracking_hook)

    async def _race():
        # Fire all 3 paths as concurrent tasks.
        async def _tray():
            sess.killswitch.fire(reason="tray_stop", fired_by="customer_tray")

        async def _hotkey():
            sess.killswitch.fire(reason="hotkey_stop", fired_by="customer_hotkey")

        async def _server():
            sess.killswitch.fire(reason="server_stop", fired_by="server_override")

        await asyncio.gather(_tray(), _hotkey(), _server())
        # Drain any scheduled hook tasks.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_race())

    # Exactly one fire won.
    assert sess.killswitch.is_killed is True
    assert len(hook_invocations) == 1
    # The winner's fired_by must be one of the 3 valid paths.
    assert hook_invocations[0][1] in {
        "customer_tray",
        "customer_hotkey",
        "server_override",
    }
    # The stored state must match the hook's winning call.
    assert sess.killswitch.fired_by == hook_invocations[0][1]
    assert sess.killswitch.reason == hook_invocations[0][0]


# ── Registry integration ────────────────────────────────────────────────────


def test_registry_fire_routes_to_correct_session(monkeypatch):
    """KillSwitchRegistry.fire() must resolve by session_id and set state."""
    _, sess = _make_session(monkeypatch)
    reg = killswitch.registry()

    result = reg.fire(sess.session_id, "registry_test", "server_override")

    assert result is True
    assert sess.killswitch.is_killed is True
    assert sess.killswitch.fired_by == "server_override"


def test_registry_fire_returns_false_for_unknown_session():
    """Firing on a nonexistent session_id returns False, no crash."""
    reg = killswitch.registry()
    result = reg.fire("does-not-exist-999", "test", "server_override")
    assert result is False


# ── Audit chain integration ─────────────────────────────────────────────────


def test_killswitch_fire_emits_audit_row(monkeypatch):
    """The _on_kill hook registered in RemoteSession.__post_init__ must
    append a killswitch_fired audit entry with reason and fired_by."""
    _, sess = _make_session(monkeypatch)

    async def _run():
        sess.killswitch.fire(reason="audit_test", fired_by="customer_hotkey")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())

    kill_rows = [
        e for e in sess.audit.entries
        if e.event_type == "killswitch_fired"
    ]
    assert len(kill_rows) == 1
    assert kill_rows[0].payload["reason"] == "audit_test"
    assert kill_rows[0].payload["fired_by"] == "customer_hotkey"


def test_each_path_produces_correct_audit_fired_by(monkeypatch):
    """Verify audit row content for each of the 3 paths independently."""
    for fired_by, reason in [
        ("customer_tray", "tray_stop"),
        ("customer_hotkey", "hotkey_stop"),
        ("server_override", "server_stop"),
    ]:
        mgr = session.SessionManager()
        sess = mgr.create_session(
            customer_email="t@t.com", customer_region="us", goal="test",
        )
        monkeypatch.setattr(session, "_manager", mgr, raising=False)

        async def _fire():
            sess.killswitch.fire(reason=reason, fired_by=fired_by)
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        asyncio.run(_fire())

        rows = [
            e for e in sess.audit.entries
            if e.event_type == "killswitch_fired"
        ]
        assert len(rows) == 1, f"expected 1 audit row for {fired_by}"
        assert rows[0].payload["fired_by"] == fired_by
        assert rows[0].payload["reason"] == reason


# ── KillSwitch.wait() integration ───────────────────────────────────────────


def test_wait_unblocks_on_fire(monkeypatch):
    """KillSwitch.wait() must unblock when fire() is called."""
    _, sess = _make_session(monkeypatch)

    async def _run():
        async def _fire_soon():
            await asyncio.sleep(0.01)
            sess.killswitch.fire(reason="wait_test", fired_by="server_override")

        await asyncio.gather(_fire_soon(), sess.killswitch.wait())

    asyncio.run(_run())
    assert sess.killswitch.is_killed is True


# ── Session state after kill ─────────────────────────────────────────────────


def test_killed_session_audit_chain_stays_intact(monkeypatch):
    """Killing a session must not corrupt the audit hash chain."""
    _, sess = _make_session(monkeypatch)
    sess.record_consent(ip_address="127.0.0.1", user_agent="test-ua")

    async def _run():
        sess.killswitch.fire(reason="integrity_check", fired_by="customer_tray")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert sess.audit.verify() is True
