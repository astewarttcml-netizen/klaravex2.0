"""G34.2 operator-side end-to-end binding test — against the REAL Rust shim.

This is the conformance partner to `test_operator_e2e.py`. The original
file is locked to the Python `mock_customer_shim` because that file is
the contract definition. This file runs the SAME 7 scenarios — but
points the operator at `target/release/klx-rdshim` so the assertions
prove the Rust binary speaks the v0 protocol identically.

Skip-when policy:
    - The compiled binary at `klx-rdshim/target/release/klx-rdshim` must
      exist. If it doesn't, the suite is skipped (not failed) so devs
      who haven't built it locally don't fail CI. The build is reproducible
      via `klx-rdshim/build.sh`.

The 7 scenarios mirror `test_operator_e2e.py` 1:1:
    1. connect + first JPEG frame
    2. mouse_move propagates to cursor centroid
    3. paste_text propagates to blue strip
    4. close() terminates the binary cleanly (exit 0)
    5. frame-loop latency under budget
    6. KLX_MOCK_FAIL_CONNECT path surfaces relay_unreachable
    7. in-process mode still works when KLX_RDSHIM_BIN is empty

Pass criteria here = Rust binary is wire-compatible with mock_customer_shim.
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

REAL_SHIM = (
    ROOT
    / "infra"
    / "rustdesk_controller"
    / "klx-rdshim"
    / "target"
    / "release"
    / "klx-rdshim"
)


def _require_real_shim() -> Path:
    if not REAL_SHIM.exists() or not os.access(REAL_SHIM, os.X_OK):
        pytest.skip(
            f"real shim not built at {REAL_SHIM}; run "
            "`infra/rustdesk_controller/klx-rdshim/build.sh` first",
        )
    return REAL_SHIM


@pytest.fixture
def real_shim_binary() -> Path:
    """Resolve and require the compiled Rust shim binary."""
    pillow_check()
    return _require_real_shim()


def pillow_check() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError:
        pytest.skip("Pillow not installed — cannot decode the shim's JPEG frames")


def _decode_jpeg(payload: bytes):
    from PIL import Image

    img = Image.open(io.BytesIO(payload))
    img.load()
    return img.width, img.height, img


def _find_red_cursor(img):
    pixels = img.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = pixels[x, y][:3]
            if r > 150 and g < 100 and b < 100:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    return cx / img.width, cy / img.height


async def _drain_frames(client, n: int, timeout: float = 5.0):
    out = []
    deadline = time.monotonic() + timeout
    async for frame in client.frames():
        out.append(frame)
        if len(out) >= n:
            return out
        if time.monotonic() > deadline:
            return out
    return out


def test_real_shim_connects_and_receives_first_frame(real_shim_binary: Path) -> None:
    async def runner() -> None:
        cfg = ConnectionConfig(
            customer_id="RUST-CUSTOMER-001",
            session_password="test-pw",
            fps_to_controller=30.0,
        )
        client = RustDeskClient(cfg, shim_bin=str(real_shim_binary))
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
        w, h, _img = _decode_jpeg(first.payload)
        assert (w, h) == (320, 240)

    asyncio.run(runner())


def test_real_shim_mouse_move_propagates_to_customer(real_shim_binary: Path) -> None:
    async def runner() -> None:
        cfg = ConnectionConfig(
            customer_id="RUST-CUSTOMER-002",
            session_password="test-pw",
        )
        client = RustDeskClient(cfg, shim_bin=str(real_shim_binary))
        await client.connect()
        try:
            initial = await _drain_frames(client, n=2, timeout=3.0)
            assert len(initial) >= 1

            target_x, target_y = 0.2, 0.8

            t0 = time.monotonic()
            await client.send_event(
                InputEvent(kind=EventKind.MOUSE_MOVE, x=target_x, y=target_y)
            )
            send_ms = (time.monotonic() - t0) * 1000

            post_move = await _drain_frames(client, n=8, timeout=3.0)
            assert post_move, "no frames after mouse_move"
            _, _, last_img = _decode_jpeg(post_move[-1].payload)
            located = _find_red_cursor(last_img)
            assert located is not None, "no red cursor pixels in post-move frame"
            cx, cy = located
            assert abs(cx - target_x) < 0.08, (
                f"cursor x {cx:.3f} != target {target_x}"
            )
            assert abs(cy - target_y) < 0.08, (
                f"cursor y {cy:.3f} != target {target_y}"
            )
            assert send_ms < 200, (
                f"send_event RTT {send_ms:.1f}ms unexpectedly slow"
            )
        finally:
            await client.close()

    asyncio.run(runner())


def test_real_shim_paste_text_propagates_to_customer(real_shim_binary: Path) -> None:
    async def runner() -> None:
        cfg = ConnectionConfig(
            customer_id="RUST-CUSTOMER-003",
            session_password="test-pw",
        )
        client = RustDeskClient(cfg, shim_bin=str(real_shim_binary))
        await client.connect()
        try:
            await _drain_frames(client, n=1, timeout=3.0)
            await client.send_event(
                InputEvent(kind=EventKind.PASTE_TEXT, text="hello klaravex")
            )
            post = await _drain_frames(client, n=6, timeout=3.0)
            assert post, "no frames after paste_text"
            _, _, img = _decode_jpeg(post[-1].payload)
            pixels = img.load()
            blue_pixel = pixels[5, 2][:3]
            assert blue_pixel[2] > 100, (
                f"expected blue pixel at (5,2), got {blue_pixel}"
            )
        finally:
            await client.close()

    asyncio.run(runner())


def test_real_shim_close_terminates_cleanly(real_shim_binary: Path) -> None:
    async def runner() -> None:
        cfg = ConnectionConfig(
            customer_id="RUST-CUSTOMER-004",
            session_password="test-pw",
        )
        client = RustDeskClient(cfg, shim_bin=str(real_shim_binary))
        await client.connect()
        proc = client._shim_transport.process  # type: ignore[union-attr]
        await _drain_frames(client, n=1, timeout=3.0)
        await client.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pytest.fail("shim did not exit within 3s of client.close()")
        assert proc.returncode == 0, f"shim exit={proc.returncode}"

    asyncio.run(runner())


def test_real_shim_frame_loop_latency_under_budget(real_shim_binary: Path) -> None:
    async def runner() -> None:
        cfg = ConnectionConfig(
            customer_id="RUST-CUSTOMER-005",
            session_password="test-pw",
        )
        client = RustDeskClient(cfg, shim_bin=str(real_shim_binary))
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
            assert per_frame_ms < 100, (
                f"per-frame latency {per_frame_ms:.1f}ms over budget"
            )
            print(
                f"\n[real-shim-e2e] per-frame latency: {per_frame_ms:.1f}ms "
                f"over {n_frames} frames"
            )
        finally:
            await client.close()

    asyncio.run(runner())


def test_real_shim_failed_connect_surfaces_clearly(
    real_shim_binary: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rustdesk_controller.rdshim_ipc import IPCProtocolError

    async def runner() -> None:
        monkeypatch.setenv("KLX_MOCK_FAIL_CONNECT", "1")
        cfg = ConnectionConfig(
            customer_id="RUST-CUSTOMER-006",
            session_password="test-pw",
        )
        client = RustDeskClient(cfg, shim_bin=str(real_shim_binary))
        with pytest.raises(IPCProtocolError) as excinfo:
            await client.connect()
        assert "relay_unreachable" in str(excinfo.value)
        assert client._connected is False

    asyncio.run(runner())


def test_real_shim_in_process_mode_still_works_when_no_shim_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identical to the mock-side version — confirmed once more here so the
    full 7-test parity is provable from one suite."""

    async def runner() -> None:
        monkeypatch.delenv("KLX_RDSHIM_BIN", raising=False)
        cfg = ConnectionConfig(
            customer_id="STUB-001",
            session_password="stub-pw",
        )
        client = RustDeskClient(cfg)
        await client.connect()
        try:
            assert client._shim_transport is None
            await client.send_event(
                InputEvent(kind=EventKind.MOUSE_MOVE, x=0.1, y=0.1)
            )
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
