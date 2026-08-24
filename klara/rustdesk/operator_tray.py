"""Operator-side kill UI for force-disconnect (task 16.15).

Runs on the rig (Anthony's machine). Two components:

    1. **GTK3 floating window** — always-on-top corner HUD showing session
       status (idle/active) with a KILL button. Polls the controller API.
       Zero pip dependencies — uses gi.repository (pre-installed on Ubuntu).

    2. **kill CLI** — standalone ``--kill`` mode that fires the kill and
       exits. Bind this to Ctrl+Shift+Escape in GNOME Settings → Keyboard
       Shortcuts → Custom Shortcuts.

Both paths POST to the local controller API:
    POST /api/remote-sessions/{sid}/kill

Usage:
    # Floating HUD (stays on desktop)
    python3 -m rustdesk_controller.operator_tray

    # One-shot kill (for keyboard shortcut binding)
    python3 -m rustdesk_controller.operator_tray --kill

    # Custom port/token
    python3 -m rustdesk_controller.operator_tray --port 8000 --token SECRET

Env vars (override CLI):
    KLX_CONTROLLER_PORT   — default 8000
    KLX_REMOTE_KILL_TOKEN — bearer token for /kill auth

Keyboard shortcut setup (one-time):
    GNOME Settings → Keyboard → Custom Shortcuts → Add:
      Name: Kill Klaravex Session
      Command: python3 -m rustdesk_controller.operator_tray --kill
      Shortcut: Ctrl+Shift+Escape
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("klaravex.operator_tray")


# ── Controller API client (stdlib only — no requests needed) ─────────────

class ControllerClient:
    """Thin HTTP client for the local controller API. Uses urllib (stdlib)."""

    def __init__(self, port: int, token: str) -> None:
        self.base = f"http://127.0.0.1:{port}/api/remote-sessions"
        self.token = token

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def active_sessions(self) -> list[dict[str, Any]]:
        """GET /active — returns list of active session dicts."""
        try:
            req = urllib.request.Request(
                f"{self.base}/active",
                headers=self._headers(),
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return json.loads(resp.read())
            return []
        except (urllib.error.URLError, OSError):
            return []  # controller not running — silent
        except Exception as exc:
            log.warning("active_sessions error: %s", exc)
            return []

    def kill_session(self, session_id: str, reason: str) -> bool:
        """POST /{sid}/kill — returns True if killed."""
        try:
            data = json.dumps({"reason": reason}).encode()
            req = urllib.request.Request(
                f"{self.base}/{session_id}/kill",
                data=data,
                headers=self._headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    log.info("killed session %s", session_id)
                    return True
            return False
        except Exception as exc:
            log.warning("kill %s error: %s", session_id, exc)
            return False

    def kill_all_active(self, reason: str = "operator_tray_kill") -> int:
        """Kill all active sessions. Returns count killed."""
        sessions = self.active_sessions()
        killed = 0
        for sess in sessions:
            if self.kill_session(sess["session_id"], reason):
                killed += 1
        return killed


# ── One-shot kill mode (for keyboard shortcut) ───────────────────────────

def _run_kill(client: ControllerClient) -> int:
    """Kill all active sessions and notify via libnotify. Exit immediately."""
    sessions = client.active_sessions()
    if not sessions:
        _notify("Klaravex Kill Switch", "No active sessions to kill.")
        return 0
    killed = client.kill_all_active("operator_hotkey_kill")
    _notify(
        "Klaravex Kill Switch",
        f"Killed {killed}/{len(sessions)} session(s).",
    )
    return 0 if killed == len(sessions) else 1


def _notify(title: str, body: str) -> None:
    """Send a desktop notification via notify-send (pre-installed on Ubuntu)."""
    try:
        subprocess.run(
            ["notify-send", "--urgency=critical", "--expire-time=3000", title, body],
            timeout=2,
            check=False,
        )
    except FileNotFoundError:
        log.info("%s: %s", title, body)


# ── GTK3 floating HUD ───────────────────────────────────────────────────

def _run_hud(client: ControllerClient) -> int:
    """Launch a small always-on-top GTK3 window in the bottom-right corner."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, GLib, Gtk
    except (ImportError, ValueError) as exc:
        print(f"GTK3 not available: {exc}", file=sys.stderr)
        print("Install: sudo apt install python3-gi gir1.2-gtk-3.0", file=sys.stderr)
        return 1

    # ── Window setup ─────────────────────────────────────────────────

    win = Gtk.Window(title="KLX Kill Switch")
    win.set_default_size(220, 80)
    win.set_keep_above(True)
    win.set_decorated(False)
    win.set_resizable(False)
    win.set_accept_focus(False)
    win.set_skip_taskbar_hint(True)
    win.set_skip_pager_hint(True)
    win.set_opacity(0.88)

    # Position bottom-right
    screen = Gdk.Screen.get_default()
    if screen:
        monitor = screen.get_primary_monitor()
        geom = screen.get_monitor_geometry(monitor)
        win.move(geom.x + geom.width - 240, geom.y + geom.height - 110)

    # ── Layout ───────────────────────────────────────────────────────

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    vbox.set_margin_start(8)
    vbox.set_margin_end(8)
    vbox.set_margin_top(6)
    vbox.set_margin_bottom(6)

    status_label = Gtk.Label(label="  IDLE — no active sessions")
    status_label.set_xalign(0)

    kill_button = Gtk.Button(label="KILL ALL SESSIONS")
    kill_button.set_sensitive(False)

    quit_button = Gtk.Button(label="Close")

    vbox.pack_start(status_label, False, False, 0)
    vbox.pack_start(kill_button, False, False, 0)
    vbox.pack_start(quit_button, False, False, 0)
    win.add(vbox)

    # ── Styling ──────────────────────────────────────────────────────

    css = Gtk.CssProvider()
    css.load_from_data(b"""
        window { background-color: #1a1a2e; border-radius: 8px; }
        label  { color: #aaaaaa; font-size: 11px; font-family: monospace; }
        button { font-size: 11px; }
        .kill-active { background-color: #cc0000; color: white; font-weight: bold; }
        .kill-idle   { background-color: #444444; color: #888888; }
    """)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        css,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    kill_button.get_style_context().add_class("kill-idle")

    # ── State ────────────────────────────────────────────────────────

    state = {"active": [], "last_count": 0}

    def _poll() -> bool:
        """GLib timeout callback — runs on the GTK main thread."""
        sessions = client.active_sessions()
        state["active"] = sessions
        n = len(sessions)
        changed = n != state["last_count"]
        state["last_count"] = n

        if n == 0:
            status_label.set_text("  IDLE — no active sessions")
            kill_button.set_sensitive(False)
            kill_button.set_label("KILL ALL SESSIONS")
            ctx = kill_button.get_style_context()
            ctx.remove_class("kill-active")
            ctx.add_class("kill-idle")
        else:
            goals = ", ".join(s.get("goal", "?")[:30] for s in sessions)
            status_label.set_text(f"  LIVE — {n} session(s): {goals}")
            kill_button.set_sensitive(True)
            kill_button.set_label(f"KILL {n} SESSION{'S' if n > 1 else ''}")
            ctx = kill_button.get_style_context()
            ctx.remove_class("kill-idle")
            ctx.add_class("kill-active")

        return True  # keep the timeout alive

    def _on_kill_clicked(_btn: Any) -> None:
        killed = client.kill_all_active()
        _notify("Klaravex Kill Switch", f"Killed {killed} session(s).")
        _poll()  # refresh immediately

    def _on_quit(_btn: Any) -> None:
        Gtk.main_quit()

    kill_button.connect("clicked", _on_kill_clicked)
    quit_button.connect("clicked", _on_quit)
    win.connect("destroy", Gtk.main_quit)

    # Poll every 2 seconds
    GLib.timeout_add_seconds(2, _poll)
    _poll()  # initial state

    win.show_all()
    log.info("operator HUD started — polling every 2s")
    Gtk.main()
    log.info("operator HUD stopped")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="operator-tray",
        description="Klaravex operator kill switch — GTK3 HUD or one-shot kill.",
    )
    parser.add_argument(
        "--port", type=int,
        default=int(os.environ.get("KLX_CONTROLLER_PORT", "8000")),
        help="Controller API port (default: 8000 / $KLX_CONTROLLER_PORT)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("KLX_REMOTE_KILL_TOKEN", ""),
        help="Bearer token for /kill auth (default: $KLX_REMOTE_KILL_TOKEN)",
    )
    parser.add_argument(
        "--kill", action="store_true",
        help="One-shot: kill all active sessions and exit (for keyboard shortcut).",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args(argv or sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    client = ControllerClient(port=args.port, token=args.token)

    if args.kill:
        return _run_kill(client)

    return _run_hud(client)


if __name__ == "__main__":
    raise SystemExit(main())
