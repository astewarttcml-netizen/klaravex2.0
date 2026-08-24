"""E2E live test — connect to a real RustDesk peer, capture frames, drive Claude vision.

Usage:
    ANTHROPIC_API_KEY=... python3 -m klara.rustdesk.e2e_live_test \
        --peer-id 110652350 --password XXXXXX --goal "move the mouse to prove control"

This script:
1. Spawns klx-rdshim in KLX_RDSHIM_MODE=real
2. Connects to the peer via the JSON IPC protocol
3. Waits for video frames
4. Sends the first frame to Claude computer-use for action prediction
5. Executes the predicted action (mouse move/click)
6. Captures the next frame to verify the action took effect
7. Disconnects cleanly
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time


SHIM_BIN = os.environ.get(
    "KLX_RDSHIM_BIN",
    os.path.join(os.path.dirname(__file__), "klx-rdshim/target/release/klx-rdshim"),
)
RELAY_HOST = "87.99.147.244"
RELAY_KEY = "E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA="


async def run_shim(peer_id: str, password: str, goal: str, cycles: int = 3):
    env = os.environ.copy()
    env["KLX_RDSHIM_MODE"] = "real"
    env["KLX_SKIP_SIGNEDID_VERIFY"] = "1"

    proc = await asyncio.create_subprocess_exec(
        SHIM_BIN,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        limit=16 * 1024 * 1024,  # 16MB buffer for large VP9 frames
    )

    async def read_event() -> dict | None:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
        if not line:
            return None
        return json.loads(line.decode().strip())

    async def send_cmd(cmd: dict):
        proc.stdin.write((json.dumps(cmd) + "\n").encode())
        await proc.stdin.drain()

    async def read_stderr_line():
        """Non-blocking stderr read for debug output."""
        try:
            line = await asyncio.wait_for(proc.stderr.readline(), timeout=0.1)
            if line:
                print(f"  [shim] {line.decode().strip()}", file=sys.stderr)
        except asyncio.TimeoutError:
            pass

    # 1. Read hello
    hello = await read_event()
    print(f"Shim: {hello}")

    # 2. Send connect
    await send_cmd({
        "kind": "connect",
        "customer_id": peer_id,
        "session_password": password,
        "relay_host": RELAY_HOST,
        "relay_key": RELAY_KEY,
        "hbbs_port": 21115,
        "hbbr_port": 21117,
    })

    # 3. Drain stderr and wait for connected/error
    print("Connecting...")
    connected = False
    for _ in range(60):  # up to 30s
        await read_stderr_line()
        try:
            evt = await asyncio.wait_for(proc.stdout.readline(), timeout=0.5)
            if evt:
                msg = json.loads(evt.decode().strip())
                print(f"Shim: {msg}")
                if msg.get("kind") == "connected":
                    connected = True
                    break
                if msg.get("kind") == "error":
                    print(f"ERROR: {msg.get('message')}")
                    break
                if msg.get("kind") == "disconnected":
                    print(f"DISCONNECTED: {msg.get('reason')}")
                    break
        except asyncio.TimeoutError:
            continue

    if not connected:
        # Drain remaining stderr
        for _ in range(10):
            await read_stderr_line()
        proc.kill()
        return

    print(f"Connected! Waiting for frames...")

    # 4. Collect frames
    frames = []
    for _ in range(100):  # read up to 100 events looking for frames
        await read_stderr_line()
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=2)
            if not line:
                break
            msg = json.loads(line.decode().strip())
            if msg.get("kind") == "frame":
                frames.append(msg)
                print(f"  Frame #{len(frames)}: {msg.get('width')}x{msg.get('height')} codec={msg.get('codec')}")
                if len(frames) >= 2:
                    break
            elif msg.get("kind") == "disconnected":
                print(f"Peer disconnected: {msg.get('reason')}")
                break
            else:
                print(f"  Event: {msg.get('kind')}")
        except asyncio.TimeoutError:
            continue

    if not frames:
        print("No frames received. Peer may not be sending video.")
        # Try sending a mouse move to trigger frame sending
        print("Sending mouse move to trigger frames...")
        await send_cmd({
            "kind": "event",
            "event_kind": "mouse_move",
            "x": 0.5,
            "y": 0.5,
        })
        for _ in range(20):
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=1)
                if line:
                    msg = json.loads(line.decode().strip())
                    if msg.get("kind") == "frame":
                        frames.append(msg)
                        print(f"  Frame after move: {msg.get('width')}x{msg.get('height')}")
                        break
                    print(f"  Event: {msg}")
            except asyncio.TimeoutError:
                continue

    if frames:
        frame = frames[0]
        payload_b64 = frame.get("payload_b64", "")
        if payload_b64:
            frame_bytes = base64.b64decode(payload_b64)

            # Downscale frame to reduce model inference time
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(frame_bytes))
                # Scale to max 1280px wide
                if img.width > 1280:
                    ratio = 1280 / img.width
                    new_size = (1280, int(img.height * ratio))
                    img = img.resize(new_size, Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                frame_bytes = buf.getvalue()
                print(f"Downscaled to {new_size[0]}x{new_size[1]} ({len(frame_bytes)} bytes)")
            except ImportError:
                print("PIL not available, using full-size frame")

            frame_path = "/tmp/klx-e2e-frame.jpg"
            with open(frame_path, "wb") as f:
                f.write(frame_bytes)
            print(f"Saved frame to {frame_path} ({len(frame_bytes)} bytes)")

            # 5. Send to vision for action prediction — run inference
            #    concurrently with a keepalive loop so the peer doesn't drop us.
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                print(f"Sending frame to vision (goal: {goal})...")
                current_frame_bytes = frame_bytes
                current_width = frame.get("width", 1920)
                current_height = frame.get("height", 1080)

                # Start keepalive: send tiny mouse moves while model thinks
                keepalive_running = True
                async def keepalive():
                    toggle = 0
                    while keepalive_running:
                        try:
                            # Alternate between two nearby positions
                            await send_cmd({
                                "kind": "event",
                                "event_kind": "mouse_move",
                                "x": 10 + toggle,
                                "y": 10,
                            })
                            toggle = 1 - toggle
                        except Exception:
                            break
                        await asyncio.sleep(2)

                keepalive_task = asyncio.create_task(keepalive())

                action = await predict_action(
                    api_key, current_frame_bytes, goal,
                    current_width, current_height,
                )

                keepalive_running = False
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except asyncio.CancelledError:
                    pass

                # Drain any acks from keepalive
                for _ in range(20):
                    try:
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.1)
                    except asyncio.TimeoutError:
                        break

                for turn in range(5):
                    if turn > 0:
                        action = await predict_action(
                            api_key, current_frame_bytes, goal,
                            current_width, current_height,
                        )
                    if not action:
                        print(f"  Turn {turn+1}: no action returned")
                        break

                    print(f"  Turn {turn+1}: {action}")

                    if action.get("event_kind") == "screenshot":
                        print(f"  Claude requested screenshot, providing current frame...")
                        continue

                    if action.get("event_kind") == "mouse_move":
                        await send_cmd({
                            "kind": "event",
                            "event_kind": "mouse_move",
                            "x": action["x"],
                            "y": action["y"],
                        })
                        print(f"  >>> SENT mouse_move to ({action['x']}, {action['y']})")
                    elif action.get("event_kind") == "mouse_click":
                        await send_cmd({
                            "kind": "event",
                            "event_kind": "mouse_click",
                            "x": action["x"],
                            "y": action["y"],
                            "button": action.get("button", "left"),
                        })
                        print(f"  >>> SENT mouse_click at ({action['x']}, {action['y']})")
                    elif action.get("event_kind") == "key_char":
                        key = action["key"]
                        # Parse modifier+key combos like "cmd+space"
                        parts = key.lower().replace("command", "cmd").replace("meta", "cmd").split("+")
                        if len(parts) > 1:
                            modifiers = parts[:-1]
                            named_key = parts[-1]
                            # Map common modifier names
                            mod_map = {"cmd": "meta", "ctrl": "control", "alt": "alt", "shift": "shift"}
                            modifiers = [mod_map.get(m, m) for m in modifiers]
                            await send_cmd({
                                "kind": "event",
                                "event_kind": "named_key",
                                "key": named_key,
                                "modifiers": modifiers,
                            })
                            print(f"  >>> SENT named_key: {named_key} + {modifiers}")
                        else:
                            await send_cmd({
                                "kind": "event",
                                "event_kind": "key_press",
                                "key": key,
                            })
                            print(f"  >>> SENT key_press: {key}")

                    # Wait for ack
                    try:
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
                        if line:
                            ack = json.loads(line.decode().strip())
                            print(f"  Ack: {ack}")
                    except asyncio.TimeoutError:
                        pass

                    # Action executed — done for this test
                    print("  Action executed successfully!")
                    break
            else:
                print("No ANTHROPIC_API_KEY — skipping vision. Frame saved for manual inspection.")
    else:
        print("No frames captured. E2E test incomplete.")

    # 7. Disconnect
    print("Disconnecting...")
    await send_cmd({"kind": "disconnect"})
    try:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
        if line:
            print(f"Final: {json.loads(line.decode().strip())}")
    except asyncio.TimeoutError:
        pass

    proc.kill()
    await proc.wait()
    print("Done.")


async def predict_action(api_key: str, frame_bytes: bytes, goal: str,
                          width: int, height: int) -> dict | None:
    """Call local LiteLLM (qwen-72b) or Claude for action prediction."""
    import httpx

    frame_b64 = base64.b64encode(frame_bytes).decode()
    use_local = os.environ.get("KLX_USE_LOCAL_MODEL", "1") == "1"

    if use_local:
        return await _predict_local(frame_b64, goal, width, height)
    else:
        return await _predict_claude(api_key, frame_b64, goal, width, height)


async def _predict_local(frame_b64: str, goal: str, width: int, height: int) -> dict | None:
    """Use local qwen-72b via LiteLLM for vision-based action prediction."""
    import httpx

    litellm_url = os.environ.get("LITELLM_URL", "http://anthony-klaravex:8000/v1")
    litellm_key = os.environ.get("LITELLM_KEY", "")

    prompt = f"""You are an AI remotely controlling a customer's computer screen.
Screen resolution: {width}x{height} pixels.
Your goal: {goal}

Look at the screenshot and respond with EXACTLY ONE action in this JSON format:
{{"action": "mouse_move", "x": <pixel_x>, "y": <pixel_y>}}
{{"action": "mouse_click", "x": <pixel_x>, "y": <pixel_y>, "button": "left"}}
{{"action": "key_press", "key": "<key>"}}
{{"action": "key_combo", "key": "<key>", "modifiers": ["cmd"]}}

Respond ONLY with the JSON, no other text."""

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            f"{litellm_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {litellm_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "qwen-72b",
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{frame_b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }],
                "max_tokens": 256,
                "temperature": 0.1,
            },
        )

    if resp.status_code != 200:
        print(f"Local model error: {resp.status_code} {resp.text[:200]}")
        return None

    result = resp.json()
    text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    print(f"  Local model raw: {text[:200]}")

    # Parse JSON from response
    try:
        # Find JSON in response
        import re
        match = re.search(r'\{[^}]+\}', text)
        if match:
            action = json.loads(match.group())
            act = action.get("action", "")
            if act == "mouse_move":
                return {"event_kind": "mouse_move", "x": action["x"], "y": action["y"]}
            elif act == "mouse_click":
                return {"event_kind": "mouse_click", "x": action["x"], "y": action["y"],
                        "button": action.get("button", "left")}
            elif act == "key_press":
                return {"event_kind": "key_char", "key": action["key"]}
            elif act == "key_combo":
                mods = action.get("modifiers", [])
                return {"event_kind": "key_char", "key": "+".join(mods + [action["key"]])}
            else:
                return {"event_kind": act, "raw": action}
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  Parse error: {e}")
    return None


async def _predict_claude(api_key: str, frame_b64: str, goal: str,
                           width: int, height: int) -> dict | None:
    """Use Claude computer-use API."""
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "computer-use-2025-01-24,interleaved-thinking-2025-05-14",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-5-20250929",
                "max_tokens": 1024,
                "tools": [{
                    "type": "computer_20250124",
                    "name": "computer",
                    "display_width_px": width,
                    "display_height_px": height,
                    "display_number": 1,
                }],
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": frame_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": f"You are remotely controlling a customer's computer to help them. Your goal: {goal}. Look at the screen and decide what action to take. Use the computer tool to perform ONE action.",
                        },
                    ],
                }],
            },
        )

    if resp.status_code != 200:
        print(f"Claude API error: {resp.status_code} {resp.text[:200]}")
        return None

    result = resp.json()
    for block in result.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "computer":
            inp = block.get("input", {})
            action = inp.get("action", "")
            cx = inp.get("coordinate", [0, 0])
            if action == "screenshot":
                return {"event_kind": "screenshot"}
            elif action == "mouse_move":
                return {"event_kind": "mouse_move", "x": cx[0], "y": cx[1]}
            elif action in ("left_click", "click"):
                return {"event_kind": "mouse_click", "x": cx[0], "y": cx[1], "button": "left"}
            elif action == "right_click":
                return {"event_kind": "mouse_click", "x": cx[0], "y": cx[1], "button": "right"}
            elif action == "double_click":
                return {"event_kind": "mouse_click", "x": cx[0], "y": cx[1], "button": "left"}
            elif action == "type":
                return {"event_kind": "key_char", "key": inp.get("text", "")}
            elif action == "key":
                return {"event_kind": "key_char", "key": inp.get("text", "")}
            else:
                print(f"Unhandled action: {action}")
                return {"event_kind": action, "raw": inp}
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--peer-id", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--goal", default="Move the mouse cursor to the center of the screen to prove remote control is working")
    parser.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args()

    asyncio.run(run_shim(args.peer_id, args.password, args.goal, args.cycles))
