"""Fast mouse test — no vision, just connect and move mouse."""
import asyncio, json, os, sys

SHIM = os.path.join(os.path.dirname(__file__), "klx-rdshim/target/release/klx-rdshim")

async def main():
    peer_id = sys.argv[1]
    password = sys.argv[2]

    env = os.environ.copy()
    env["KLX_RDSHIM_MODE"] = "real"
    env["KLX_SKIP_SIGNEDID_VERIFY"] = "1"

    proc = await asyncio.create_subprocess_exec(
        SHIM, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env, limit=16*1024*1024,
    )

    async def send(cmd):
        proc.stdin.write((json.dumps(cmd) + "\n").encode())
        await proc.stdin.drain()

    async def read():
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
        return json.loads(line.decode().strip()) if line else None

    # Hello
    print(await read())

    # Connect
    await send({"kind":"connect","customer_id":peer_id,"session_password":password,
                "relay_host":"87.99.147.244","relay_key":"E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA=",
                "hbbs_port":21115,"hbbr_port":21117})

    # Wait for connected
    while True:
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            if not line: break
            msg = json.loads(line.decode().strip())
            print(msg)
            if msg.get("kind") == "connected":
                break
            if msg.get("kind") in ("error", "disconnected"):
                proc.kill()
                return
        except asyncio.TimeoutError:
            break

    # Drain stderr
    while True:
        try:
            l = await asyncio.wait_for(proc.stderr.readline(), timeout=0.1)
            if l: print(f"  [shim] {l.decode().strip()}", file=sys.stderr)
            else: break
        except asyncio.TimeoutError:
            break

    # Give stream_session time to start
    await asyncio.sleep(1)

    # Send mouse events with delays
    moves = [
        (100, 100), (300, 300), (500, 500), (700, 400),
        (960, 600), (1200, 800), (500, 200), (960, 600),
    ]
    for x, y in moves:
        print(f"Moving mouse to ({x}, {y})...")
        await send({"kind":"event","event_kind":"mouse_move","x":x,"y":y})
        await asyncio.sleep(0.3)
        # Read any response
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.2)
            if line:
                msg = json.loads(line.decode().strip())
                if msg.get("kind") == "event_ack":
                    print(f"  ack: seq={msg.get('sequence')} status={msg.get('status')}")
                elif msg.get("kind") == "frame":
                    print(f"  frame: {msg.get('width')}x{msg.get('height')}")
                else:
                    print(f"  {msg}")
        except asyncio.TimeoutError:
            pass

    # Click
    print("Clicking at (960, 600)...")
    await send({"kind":"event","event_kind":"mouse_click","x":960,"y":600,"button":"left"})
    await asyncio.sleep(0.5)

    # Disconnect
    await send({"kind":"disconnect"})
    await asyncio.sleep(0.5)
    proc.kill()
    print("Done.")

asyncio.run(main())
