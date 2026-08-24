"""Dry-run CLI for the G34 RustDesk controller.

Runs the session loop end-to-end against the stub transport + stub vision
predictor, so the full state machine, audit chain, recording sink, and
killswitch wiring can be smoke-tested locally without standing up the real
RustDesk relay or burning an Anthropic computer-use call.

Usage::

    python3 -m rustdesk_controller --email cust@example.com --region us --goal "fix wifi"

What it does:

    1. Creates a session via the SessionManager.
    2. Records customer consent (hash-chained audit entry #0).
    3. Runs N predict -> confirm -> execute cycles with a stub PredictedAction.
    4. Calls end("fixed") and prints the recorder summary + audit chain check.

Exit code:

    0  — session ended cleanly, audit chain intact
    1  — audit chain failed verification (regression)
    2  — bad args or killswitch fired before N cycles completed

This is intentionally NOT a deployable entrypoint — it lives next to the
package so engineers can run it locally / from CI as a sanity check that the
scaffolded contracts still wire together.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

from . import __version__ as CONTROLLER_VERSION
from .factory import SHIM_ENV_VAR, shim_configured, transport_factory
from .protocol import ConnectionConfig, EventKind, Frame, InputEvent
from .session import RemoteSession, SessionState, manager
from .vision import PredictedAction, VisionPredictor


class _DryRunVision(VisionPredictor):
    """Returns a high-confidence centre-screen click — no API call."""

    def __init__(self) -> None:
        super().__init__(api_key="dry-run")

    async def predict(self, frame: Frame, goal: str) -> PredictedAction:  # noqa: D401
        return PredictedAction(
            event=InputEvent(
                kind=EventKind.MOUSE_CLICK, x=0.5, y=0.5, button="left",
            ),
            target_description=f"(dry-run) centre of screen for goal: {goal!r}",
            rationale=f"Dry-run action #{frame.sequence + 1} to demonstrate the loop.",
            confidence=0.95,
        )


def _stub_frame(sequence: int) -> Frame:
    return Frame(
        session_id="dry-run",
        sequence=sequence,
        width=1920,
        height=1080,
        codec="jpeg",
        payload=b"\xff\xd8\xff\xd9",
        timestamp_ms=0,
    )


async def _wait_for_state(
    sess: RemoteSession, target: SessionState, timeout: float = 2.0,
) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if sess.state == target:
            return
        await asyncio.sleep(0.005)
    raise TimeoutError(f"state never reached {target!r} (current={sess.state!r})")


async def _run_cycle(sess: RemoteSession, sequence: int) -> dict[str, object]:
    future = sess.request_next_action(_stub_frame(sequence))
    await _wait_for_state(sess, SessionState.AWAITING_CONFIRM)
    result = await sess.confirm(True)
    executed = await future
    return {"cycle": sequence + 1, "executed": bool(executed), **result}


async def _run(
    email: str, region: str, goal: str, cycles: int, sink_root: Path,
) -> int:
    sess = manager().create_session(
        customer_email=email, customer_region=region, goal=goal,
    )

    # Replace defaults so this is repeatable + isolated from prod sinks.
    sess.vision = _DryRunVision()
    sess.transport._connected = True  # skip the relay handshake stub
    from .recording import SessionRecorder

    sess.recorder = SessionRecorder(
        session_id=sess.session_id,
        customer_email=email,
        customer_region=region,
        sink_dir=sink_root / sess.session_id,
    )

    sess.record_consent(ip_address="127.0.0.1", user_agent="rustdesk-controller-dryrun/1")

    cycle_results: list[dict[str, object]] = []
    for i in range(cycles):
        if sess.killswitch.is_killed:
            print(
                f"killswitch fired before cycle {i + 1}: {sess.killswitch.reason}",
                file=sys.stderr,
            )
            sess.end("handoff")
            return 2
        cycle_results.append(await _run_cycle(sess, i))

    summary = sess.end("fixed")

    report = {
        "session_id": sess.session_id,
        "state": sess.state.value,
        "cycles": cycle_results,
        "audit_chain_intact": summary["audit_chain_intact"],
        "recording": {
            "enabled": summary["enabled"],
            "events_written": summary.get("events_written", 0),
        },
        "audit_entries": len(sess.audit.entries),
    }
    print(json.dumps(report, indent=2))

    return 0 if summary["audit_chain_intact"] else 1


async def _probe(prefer_shim: bool | None, binary: str | None) -> int:
    """Print which transport the factory would pick, without spawning a session.

    Used by operators to verify shim configuration on a new host before they
    risk a real consent record. Short-circuits BEFORE session creation,
    consent recording, or the first computer-use API call.

    Note: `prefer_shim=False` keeps the probe pure (no subprocess spawn);
    `prefer_shim=True` or auto-detect will actually attempt to spawn the
    shim and run the v0 hello handshake — that's the real diagnostic.
    """
    cfg = ConnectionConfig()
    report: dict[str, object] = {
        "mode": "probe",
        "controller_version": CONTROLLER_VERSION,
        "probe_timestamp": datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "env": {SHIM_ENV_VAR: os.environ.get(SHIM_ENV_VAR, "")},
        "shim_configured": shim_configured(),
        "relay_host": cfg.relay_host,
    }
    try:
        transport, selection = await transport_factory(
            cfg, prefer_shim=prefer_shim, binary=binary,
        )
    except FileNotFoundError as exc:
        report["transport"] = {
            "kind": "error",
            "reason": f"shim binary not found: {exc}",
            "binary": binary,
        }
        report["ok"] = False
        print(json.dumps(report, indent=2))
        return 2
    except Exception as exc:  # noqa: BLE001
        report["transport"] = {
            "kind": "error",
            "reason": f"{type(exc).__name__}: {exc}",
            "binary": binary,
        }
        report["ok"] = False
        print(json.dumps(report, indent=2))
        return 2

    report["transport"] = {
        "kind": selection.kind,
        "reason": selection.reason,
        "binary": selection.binary,
    }
    report["ok"] = True
    # If we spawned a real shim, close it so the probe doesn't leak a
    # subprocess. The stub branch has no resources to release.
    if selection.kind == "shim":
        try:
            await transport.close()
        except Exception:  # noqa: BLE001
            pass

    print(json.dumps(report, indent=2))
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m rustdesk_controller",
        description="Dry-run the G34 session loop end-to-end (no live relay).",
    )
    p.add_argument("--email", default="dryrun@klaravex.com")
    p.add_argument("--region", default="us", choices=["us", "eu"])
    p.add_argument("--goal", default="fix wifi")
    p.add_argument("--cycles", type=int, default=2)
    p.add_argument(
        "--sink-root",
        type=Path,
        default=Path(".loki/remote-sessions/dry-run"),
        help="Where the dry-run recording + audit JSONL land.",
    )
    p.add_argument(
        "--probe",
        action="store_true",
        help=(
            "Print which transport (shim|stub) the factory would pick and "
            "exit without creating a session or recording consent."
        ),
    )
    p.add_argument(
        "--prefer-shim",
        choices=["auto", "yes", "no"],
        default="auto",
        help=(
            "Override transport selection for --probe: 'auto' (default) "
            "reads $KLX_RDSHIM_BIN; 'yes' forces the shim (may spawn); "
            "'no' forces the stub (no I/O)."
        ),
    )
    p.add_argument(
        "--shim-binary",
        default=None,
        help="Explicit klx-rdshim binary path (overrides $KLX_RDSHIM_BIN).",
    )
    return p.parse_args(argv)


def _resolve_prefer_shim(flag: str) -> bool | None:
    if flag == "auto":
        return None
    return flag == "yes"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.probe:
        return asyncio.run(
            _probe(
                prefer_shim=_resolve_prefer_shim(args.prefer_shim),
                binary=args.shim_binary,
            )
        )
    if args.cycles < 1:
        print("--cycles must be >= 1", file=sys.stderr)
        return 2
    args.sink_root.mkdir(parents=True, exist_ok=True)
    return asyncio.run(
        _run(args.email, args.region, args.goal, args.cycles, args.sink_root)
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
