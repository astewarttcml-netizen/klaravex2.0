"""Mock customer-side shim — Python conformance impl of klx-rdshim v0.

This module provides an EXECUTABLE Python script that speaks the same v0
JSON line protocol the Rust `klx-rdshim` binary speaks (per
`G34.1-binding-decision.md`). It exists for two reasons:

  1. **MVP velocity.** The Hetzner Rust cross-compile pipeline is still
     under construction (see G34.2a). The mock shim lets us prove the
     full Python-side operator binding loop — `_connect` →
     `_recv_frame` → `_send_event` round-trip — without librustdesk on
     the host.

  2. **Bisectable transport.** Because the mock speaks the EXACT same
     JSON wire protocol, swapping in the real Rust binary is a
     `$KLX_RDSHIM_BIN=/path/to/klx-rdshim` env flip with no Python-side
     code change. Today's e2e test against this mock is tomorrow's
     conformance test against the real binary.

Behavior when spawned as `python3 -m rustdesk_controller.mock_customer_shim`:

    1. Emits `hello` on stdout (klx-rdshim 0.1.0 / mock-customer-shim).
    2. Reads `connect` from stdin → emits `connected` with a synthetic
       session id + 320x240 framebuffer (small enough to keep test
       latency low; production frames are bigger).
    3. Begins emitting `frame` events at ~30 Hz (configurable via
       `KLX_MOCK_FPS`). Each frame is a tiny JPEG with the current cursor
       position rendered as a red dot on a black background — so the
       operator side can both decode it AND visually verify that input
       events moved the cursor.
    4. For every `event` command: applies it to the cursor state, then
       emits `event_ack` with the running sequence number.
    5. On `disconnect`: emits `disconnected{reason:"client_request"}`
       and exits 0.

The mock is intentionally faithful to the protocol contract — it emits
ALL six event kinds defined in the protocol, and refuses malformed input
in the same way the Rust shim does. If a contract change ever lands on
the Python side, this file fails first.

ENVIRONMENT FLAGS (for tests):
    KLX_MOCK_FPS           — frames per second; default 30
    KLX_MOCK_FRAMES        — exit after N frames; default 0 (run forever)
    KLX_MOCK_WIDTH         — framebuffer width;  default 320
    KLX_MOCK_HEIGHT        — framebuffer height; default 240
    KLX_MOCK_FAIL_CONNECT  — if set, emit relay_unreachable error instead
                              of `connected` (used by negative-path tests)
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
from dataclasses import dataclass, field

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover — test rig has Pillow
    sys.stderr.write(f"mock_customer_shim requires Pillow: {exc}\n")
    sys.exit(2)


# Must satisfy `rdshim_ipc.EvtHello.major_version` — that property takes
# the last whitespace-separated token then splits on dots. So we encode
# the mock marker inside the librustdesk_commit field instead of after
# the semver, leaving the version token as a clean dotted triple.
SHIM_VERSION = "klx-rdshim 0.1.0"
LIBRUSTDESK_COMMIT = "mock-no-link (mock-customer-shim)"


@dataclass
class CursorState:
    """Tracks the simulated customer-side cursor position + button state."""

    x: float = 0.5  # normalized 0–1 of framebuffer width
    y: float = 0.5  # normalized 0–1 of framebuffer height
    last_button: str | None = None
    last_key: str | None = None
    typed_text: str = ""
    modifiers: tuple[str, ...] = field(default_factory=tuple)


def emit(obj: dict) -> None:
    """Write one line of JSON to stdout and flush.

    The Python operator's `_reader_loop` blocks on `readline()` — a
    missing flush would cause indefinite stalls.
    """
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def render_frame(width: int, height: int, cursor: CursorState, seq: int) -> bytes:
    """Render the cursor + sequence number as a tiny JPEG.

    Keeping the frame deterministic and small (a few hundred bytes)
    means the e2e test can assert on byte content without exploding
    the wire protocol over JSON.
    """
    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Red cursor dot. Clamped so the radius doesn't drift off-canvas at edges.
    cx = max(4, min(width - 5, int(cursor.x * width)))
    cy = max(4, min(height - 5, int(cursor.y * height)))
    draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 0, 0))

    # White sequence counter in the top-left, 1 pixel wide. Survives
    # JPEG compression as a 4-bit luminance bar — tests can introspect
    # the raw pixel to confirm frame ordering.
    bar_len = max(1, seq % width)
    draw.rectangle([0, 0, bar_len, 1], fill=(255, 255, 255))

    # If the customer "typed text", echo it as a faint blue strip on row 2 —
    # length proportional to text length. Lets the test confirm paste_text
    # round-trips into the customer-side simulation.
    if cursor.typed_text:
        n = min(width - 1, len(cursor.typed_text))
        draw.rectangle([0, 2, n, 3], fill=(0, 0, 200))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70, optimize=True)
    return buf.getvalue()


def apply_event(event: dict, cursor: CursorState) -> None:
    """Mutate the cursor state per the incoming event command.

    Mirrors the EventKind enum on the Python protocol side.
    """
    kind = event.get("event_kind", "")
    if kind == "mouse_move":
        if event.get("x") is not None:
            cursor.x = float(event["x"])
        if event.get("y") is not None:
            cursor.y = float(event["y"])
    elif kind == "mouse_click":
        cursor.last_button = event.get("button") or "left"
    elif kind == "mouse_scroll":
        cursor.last_button = "scroll"
    elif kind in ("key_down", "key_up", "key_press"):
        cursor.last_key = event.get("key") or ""
        mods = event.get("modifiers") or []
        if isinstance(mods, list):
            cursor.modifiers = tuple(str(m) for m in mods)
    elif kind == "paste_text":
        cursor.typed_text += event.get("text") or ""


def read_command_nonblocking(timeout_s: float) -> str | None:
    """Poll stdin with `select` so the frame loop never stalls waiting for input.

    Returns the line if one is available within `timeout_s`, else None.
    EOF surfaces as the empty string so callers can distinguish.
    """
    import select

    r, _, _ = select.select([sys.stdin], [], [], timeout_s)
    if not r:
        return None
    line = sys.stdin.readline()
    return line  # "" on EOF, otherwise "<json>\n"


def main() -> int:
    fps = float(os.environ.get("KLX_MOCK_FPS", "30"))
    max_frames = int(os.environ.get("KLX_MOCK_FRAMES", "0"))
    width = int(os.environ.get("KLX_MOCK_WIDTH", "320"))
    height = int(os.environ.get("KLX_MOCK_HEIGHT", "240"))
    fail_connect = bool(os.environ.get("KLX_MOCK_FAIL_CONNECT", ""))

    # 1. hello (always first, before reading any input)
    emit(
        {
            "kind": "hello",
            "shim_version": SHIM_VERSION,
            "librustdesk_commit": LIBRUSTDESK_COMMIT,
        }
    )

    # 2. Wait for connect command. Block here — the operator must send it.
    line = sys.stdin.readline()
    if not line:
        return 0  # peer closed before connect
    try:
        cmd = json.loads(line)
    except json.JSONDecodeError as exc:
        emit({"kind": "error", "code": "invalid_json", "message": str(exc)})
        return 1
    if cmd.get("kind") != "connect":
        emit(
            {
                "kind": "error",
                "code": "unexpected_command",
                "message": f"first command must be connect, got {cmd.get('kind')!r}",
            }
        )
        return 1

    if fail_connect:
        emit(
            {
                "kind": "error",
                "code": "relay_unreachable",
                "message": "KLX_MOCK_FAIL_CONNECT=1; simulating unreachable relay",
            }
        )
        emit({"kind": "disconnected", "reason": "error"})
        return 0

    session_id = f"K-MOCK-{int(time.time())}"
    emit(
        {
            "kind": "connected",
            "session_id": session_id,
            "width": width,
            "height": height,
        }
    )

    # 3. Frame loop. We pump frames at `fps` AND poll stdin between
    # frames so events get acked promptly. This is the shape librustdesk
    # would actually use: capture thread + input thread interleaved.
    cursor = CursorState()
    frame_period = 1.0 / fps if fps > 0 else 0.0
    event_seq = 0
    frames_emitted = 0
    next_frame_at = time.monotonic()

    while True:
        # Time-budget left until next frame
        now = time.monotonic()
        wait = max(0.0, next_frame_at - now)
        line = read_command_nonblocking(timeout_s=wait)

        if line is not None:
            if line == "":  # EOF
                emit({"kind": "disconnected", "reason": "peer_closed"})
                return 0
            try:
                cmd = json.loads(line)
            except json.JSONDecodeError as exc:
                emit({"kind": "error", "code": "invalid_json", "message": str(exc)})
                continue
            kind = cmd.get("kind")
            if kind == "disconnect":
                emit({"kind": "disconnected", "reason": "client_request"})
                return 0
            if kind == "event":
                apply_event(cmd, cursor)
                event_seq += 1
                emit(
                    {
                        "kind": "event_ack",
                        "sequence": event_seq,
                        "status": "sent",
                    }
                )
            elif kind == "connect":
                emit(
                    {
                        "kind": "error",
                        "code": "already_connected",
                        "message": "connect command after session start",
                    }
                )
            else:
                emit(
                    {
                        "kind": "error",
                        "code": "unknown_kind",
                        "message": f"unknown command kind {kind!r}",
                    }
                )

        # Emit a frame if it's due
        now = time.monotonic()
        if now >= next_frame_at:
            payload = render_frame(width, height, cursor, frames_emitted)
            emit(
                {
                    "kind": "frame",
                    "session_id": session_id,
                    "sequence": frames_emitted,
                    "width": width,
                    "height": height,
                    "codec": "jpeg",
                    "payload_b64": base64.b64encode(payload).decode("ascii"),
                    "timestamp_ms": int(time.time() * 1000),
                }
            )
            frames_emitted += 1
            next_frame_at = now + frame_period
            if max_frames and frames_emitted >= max_frames:
                emit({"kind": "disconnected", "reason": "frame_budget_reached"})
                return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # Operator closed stdin before we finished draining — clean exit.
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
