"""G34.1 operator-side end-to-end binding test.

Spawns the `mock_customer_shim.py` as a real subprocess speaking the v0
JSON line protocol (the same contract the Rust `klx-rdshim` binary
implements), drives it via `RustDeskClient` in bound mode, and asserts:

    1. The full `connect()` handshake succeeds against a real subprocess.
    2. `frames()` yields decoded JPEG `Frame` objects with the expected
       dimensions and codec.
    3. `send_event(mouse_move)` propagates through stdin and changes the
       simulated cursor position — verifiable by decoding the next frame
       and finding the red cursor dot at the new normalized location.
    4. `send_event(paste_text)` propagates and appears in the
       customer-side simulation (blue text strip).
    5. `close()` cleanly tears down the subprocess.

These cover the operator-side binding contract regardless of whether
the underlying shim is the Python mock (this test) or the Rust binary
(future tests can override `KLX_RDSHIM_BIN` and reuse this file). When
the Rust binary's `connect` lands in G34.2a, removing the
`xfail_real_shim` marker on a future variant of this test proves the
swap landed cleanly.

Run: `python3 -m pytest infra/rustdesk_controller/tests/test_operator_e2e.py -q`

Requires Pillow on the test rig (`pip install Pillow`) so the mock shim
can render JPEG frames the operator decodes back into RGB to inspect
the cursor.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import protocol  # noqa: E402
from rustdesk_controller.protocol import (  # noqa: E402
    ConnectionConfig,
    EventKind,
    InputEvent,
    RustDeskClient,
)


# Path to the mock shim entry script — invoked as `python3 -m
# rustdesk_controller.mock_customer_shim` so the package import path
# resolves cleanly inside the spawned subprocess.
MOCK_MODULE = "rustdesk_controller.mock_customer_shim"

# A shell wrapper that runs the python module. We use a shell script
# wrapper because `build_shim_argv()` produces a single-binary argv —
# wrapping the `python3 -m …` invocation in a one-line shell makes the
# Python module satisfy the "spawn a binary" contract that the real
# Rust shim will satisfy in G34.2a.
WRAPPER_SCRIPT_TEMPLATE = """#!/usr/bin/env bash
# Auto-generated wrapper — invokes mock_customer_shim as a subprocess.
# Sets PYTHONPATH so `rustdesk_controller` is importable.
export PYTHONPATH="{infra_root}:${{PYTHONPATH:-}}"
exec "{python}" -u -m {module} "$@"
"""


@pytest.fixture
def mock_shim_binary(tmp_path: Path) -> Path:
    """Write a one-line shell wrapper that invokes mock_customer_shim.

    Returned path is executable. Tests pass it to `RustDeskClient`'s
    `shim_bin=` kwarg.
    """
    pillow_check()
    wrapper = tmp_path / "klx-rdshim-mock"
    wrapper.write_text(
        WRAPPER_SCRIPT_TEMPLATE.format(
            infra_root=str(ROOT / "infra"),
            python=sys.executable,
            module=MOCK_MODULE,
        )
    )
    wrapper.chmod(0o755)
    return wrapper


def pillow_check() -> None:
    """Skip the test if Pillow isn't installed — the mock needs it."""
    try:
        import PIL  # noqa: F401
    except ImportError:
        pytest.skip("Pillow not installed — mock_customer_shim cannot render frames")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _decode_jpeg(payload: bytes) -> tuple[int, int, "PIL.Image.Image"]:  # noqa: F821
    from PIL import Image

    img = Image.open(io.BytesIO(payload))
    img.load()
    return img.width, img.height, img


def _find_red_cursor(img) -> tuple[float, float] | None:  # noqa: ANN001
    """Locate the centroid of bright-red pixels in the frame.

    Returns normalized (x, y) in 0–1 of frame width / height. None if
    no red pixels are bright enough (frame may be all-black on the
    very first capture).
    """
    pixels = img.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = pixels[x, y][:3]
            # JPEG quantization smears the pure-red dot; threshold is
            # loose so we still find it.
            if r > 150 and g < 100 and b < 100:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    return cx / img.width, cy / img.height


async def _drain_frames(
    client: RustDeskClient,
    n: int,
    timeout: float = 5.0,
) -> list[protocol.Frame]:
    """Pull `n` frames from the client with an overall timeout."""
    out: list[protocol.Frame] = []
    deadline = time.monotonic() + timeout
    async for frame in client.frames():
        out.append(frame)
        if len(out) >= n:
            return out
        if time.monotonic() > deadline:
            return out
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_operator_connects_and_receives_first_frame(
    mock_shim_binary: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: spawn shim, handshake, receive at least one JPEG frame."""

    async def runner() -> None:
        cfg = ConnectionConfig(
            customer_id="MOCK-CUSTOMER-001",
            session_password="test-pw",
            fps_to_controller=30.0,
        )
        client = RustDeskClient(cfg, shim_bin=str(mock_shim_binary))

        t0 = time.monotonic()
        await client.connect()
        connect_ms = (time.monotonic() - t0) * 1000

        try:
            frames = await _drain_frames(client, n=1, timeout=5.0)
        finally:
            await client.close()

        assert connect_ms < 5000, f"connect took {connect_ms:.0f}ms (>5s)"
        assert len(frames) >= 1
        first = frames[0]
        assert first.codec == "jpeg"
        assert first.width == 320
        assert first.height == 240
        # Confirm we can actually decode the bytes — proves the binary
        # round-trip through base64+JSON is lossless.
        w, h, _img = _decode_jpeg(first.payload)
        assert (w, h) == (320, 240)

    asyncio.run(runner())


def test_operator_mouse_move_propagates_to_customer(
    mock_shim_binary: Path,
) -> None:
    """send_event(mouse_move) updates the simulated cursor position.

    We send a move to (0.2, 0.8), let the mock shim render a few more
    frames, then decode the most recent frame and verify the red cursor
    dot has moved near the target normalized coordinates.
    """

    async def runner() -> None:
        cfg = ConnectionConfig(
            customer_id="MOCK-CUSTOMER-002",
            session_password="test-pw",
        )
        client = RustDeskClient(cfg, shim_bin=str(mock_shim_binary))
        await client.connect()
        try:
            # Drain initial frames so we know the connection is live.
            initial = await _drain_frames(client, n=2, timeout=3.0)
            assert len(initial) >= 1

            target_x, target_y = 0.2, 0.8

            t0 = time.monotonic()
            await client.send_event(
                InputEvent(kind=EventKind.MOUSE_MOVE, x=target_x, y=target_y)
            )
            send_ms = (time.monotonic() - t0) * 1000

            # Pull a few more frames so the cursor-move has time to
            # show up in the next render. The mock renders at 30 fps so
            # 5 frames covers a clear post-move state.
            post_move = await _drain_frames(client, n=8, timeout=3.0)
            assert post_move, "no frames after mouse_move"

            # Inspect the last frame — it has the latest cursor state.
            _, _, last_img = _decode_jpeg(post_move[-1].payload)
            located = _find_red_cursor(last_img)
            assert located is not None, "no red cursor pixels in post-move frame"
            cx, cy = located

            # Allow some tolerance: JPEG quantization + 8px dot radius
            # smear the centroid by ~0.025 of canvas in each axis.
            assert abs(cx - target_x) < 0.08, f"cursor x {cx:.3f} != target {target_x}"
            assert abs(cy - target_y) < 0.08, f"cursor y {cy:.3f} != target {target_y}"

            # Round-trip latency for the input command itself (subprocess
            # stdin write + drain). This is the floor on operator input
            # responsiveness — the visual feedback loop adds frame-period.
            assert send_ms < 200, f"send_event RTT {send_ms:.1f}ms unexpectedly slow"
        finally:
            await client.close()

    asyncio.run(runner())


def test_operator_paste_text_propagates_to_customer(
    mock_shim_binary: Path,
) -> None:
    """send_event(paste_text) is acked and reflected in the customer state.

    The mock renders typed text as a blue strip of length proportional
    to the text, so the operator can confirm propagation visually.
    """

    async def runner() -> None:
        cfg = ConnectionConfig(
            customer_id="MOCK-CUSTOMER-003",
            session_password="test-pw",
        )
        client = RustDeskClient(cfg, shim_bin=str(mock_shim_binary))
        await client.connect()
        try:
            await _drain_frames(client, n=1, timeout=3.0)
            await client.send_event(
                InputEvent(
                    kind=EventKind.PASTE_TEXT,
                    text="hello klaravex",
                )
            )
            post = await _drain_frames(client, n=6, timeout=3.0)
            assert post, "no frames after paste_text"

            _, _, img = _decode_jpeg(post[-1].payload)
            # Blue strip on row 2 — read a single pixel at the expected
            # location and confirm it is blueish.
            pixels = img.load()
            blue_pixel = pixels[5, 2][:3]
            assert blue_pixel[2] > 100, f"expected blue pixel at (5,2), got {blue_pixel}"
        finally:
            await client.close()

    asyncio.run(runner())


def test_operator_close_terminates_shim_cleanly(
    mock_shim_binary: Path,
) -> None:
    """`close()` writes `disconnect`, the shim exits 0, no zombies."""

    async def runner() -> None:
        cfg = ConnectionConfig(
            customer_id="MOCK-CUSTOMER-004",
            session_password="test-pw",
        )
        client = RustDeskClient(cfg, shim_bin=str(mock_shim_binary))
        await client.connect()
        # Grab the subprocess handle so we can assert it exited cleanly.
        proc = client._shim_transport.process  # type: ignore[union-attr]
        await _drain_frames(client, n=1, timeout=3.0)

        await client.close()

        # Wait briefly for the process to actually finish flushing.
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pytest.fail("shim did not exit within 3s of client.close()")
        # Mock returns 0 on clean disconnect.
        assert proc.returncode == 0, f"shim exit={proc.returncode}"

    asyncio.run(runner())


def test_operator_frame_loop_latency_under_budget(
    mock_shim_binary: Path,
) -> None:
    """Measure end-to-end frame latency.

    The mock emits at 30 fps; the operator at 1.5 fps real-world. This
    test measures the floor — how fast the operator CAN process frames
    when the LLM is removed from the loop. The budget is generous so
    CI noise doesn't flake it.
    """

    async def runner() -> None:
        cfg = ConnectionConfig(
            customer_id="MOCK-CUSTOMER-005",
            session_password="test-pw",
        )
        client = RustDeskClient(cfg, shim_bin=str(mock_shim_binary))
        await client.connect()
        try:
            n_frames = 10
            t0 = time.monotonic()
            frames = await _drain_frames(client, n=n_frames, timeout=5.0)
            elapsed = time.monotonic() - t0
            assert len(frames) == n_frames, (
                f"only got {len(frames)} of {n_frames} frames in {elapsed:.2f}s"
            )
            per_frame_ms = (elapsed / n_frames) * 1000
            # Mock targets 30 fps = 33.3 ms/frame; the JSON+base64
            # transport adds maybe 1 ms. We give 100 ms headroom.
            assert per_frame_ms < 100, f"per-frame latency {per_frame_ms:.1f}ms over budget"
            print(f"\n[g34.1-e2e] per-frame latency: {per_frame_ms:.1f}ms over {n_frames} frames")
        finally:
            await client.close()

    asyncio.run(runner())


def test_operator_failed_connect_surfaces_clearly(
    mock_shim_binary: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the (simulated) relay is unreachable, the operator gets a clear error.

    Activated by setting `KLX_MOCK_FAIL_CONNECT=1` in the shim's
    environment — the mock emits `error{relay_unreachable}` then
    disconnects, and the Python side raises `IPCProtocolError`.
    """
    from rustdesk_controller.rdshim_ipc import IPCProtocolError

    async def runner() -> None:
        monkeypatch.setenv("KLX_MOCK_FAIL_CONNECT", "1")
        cfg = ConnectionConfig(
            customer_id="MOCK-CUSTOMER-006",
            session_password="test-pw",
        )
        client = RustDeskClient(cfg, shim_bin=str(mock_shim_binary))
        with pytest.raises(IPCProtocolError) as excinfo:
            await client.connect()
        # The error chain should mention the underlying relay_unreachable
        # code so operators don't have to dig.
        assert "relay_unreachable" in str(excinfo.value)
        # connect() failed cleanly — client should not be in a connected state.
        assert client._connected is False

    asyncio.run(runner())


def test_operator_in_process_mode_still_works_when_no_shim_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backwards-compat: without `shim_bin=` or env, client stays in-process.

    Pre-G34.1 callers (session-loop unit tests, dry-run CLI) must keep
    working unchanged.
    """

    async def runner() -> None:
        monkeypatch.delenv("KLX_RDSHIM_BIN", raising=False)
        cfg = ConnectionConfig(
            customer_id="STUB-001",
            session_password="stub-pw",
        )
        client = RustDeskClient(cfg)  # no shim_bin
        await client.connect()
        try:
            assert client._shim_transport is None  # in-process mode
            # send_event in in-process mode is a no-op log — must not raise.
            await client.send_event(
                InputEvent(kind=EventKind.MOUSE_MOVE, x=0.1, y=0.1)
            )
            # Inject a synthetic frame; frames() must yield it.
            synthetic = protocol.Frame(
                session_id="STUB-001",
                sequence=0,
                width=1,
                height=1,
                codec="jpeg",
                payload=b"\xff\xd8\xff\xd9",
                timestamp_ms=0,
            )
            await client._inject_frame_for_tests(synthetic)
            iterator = client.frames()
            got = await asyncio.wait_for(iterator.__anext__(), timeout=2.0)
            assert got is synthetic
        finally:
            await client.close()

    asyncio.run(runner())
