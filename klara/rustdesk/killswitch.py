"""3-path session kill switch (spec §4 requirement 4).

Three independent paths, all must terminate the session within 1 second AND
log the reason to the audit chain + DB:

    1. **customer_tray** — Customer clicks the always-on-top STOP button in
       the system tray / persistent indicator banner. Helper sends
       Message::kill_session over the protocol; rdshim translates that
       into a `killswitch:tray` event on the operator's IPC channel.
    2. **customer_hotkey** — Global hotkey Ctrl+Shift+Escape (spec §1
       documented Ctrl+Shift+X originally; G34.3 standardized on
       Ctrl+Shift+Escape per requirements). Same wire path as (1) but
       arrives with `fired_by="customer_hotkey"`.
    3. **server_override** — Operator (Anthony, the auto-abort logic in
       session.py, or the POST /api/remote_sessions/{sid}/kill endpoint)
       calls `KillSwitch.fire(reason, fired_by="server_override")`. This
       trips the asyncio.Event so any blocked recv() / send_event() in
       the session loop wakes immediately AND closes the transport AND
       writes the audit row.

A single global `KillSwitchRegistry` (module-level) keeps a mapping
session_id → KillSwitch so the FastAPI handler (which only has the
session_id from the URL) can fire any session's switch without holding
a reference to the RemoteSession dataclass.

`KillSwitch.fire()` is idempotent — subsequent calls after the first are
no-ops so all three paths can race without producing double-billed audit
rows.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

log = logging.getLogger("klaravex.rustdesk.killswitch")


# Standardised fired_by values — these match the DB CHECK constraint on
# klaravex_remote_sessions.killed_by. Adding a new path? Update the migration.
FIRED_BY_TRAY = "customer_tray"
FIRED_BY_HOTKEY = "customer_hotkey"
FIRED_BY_SERVER = "server_override"
FIRED_BY_LOW_CONF = "auto_abort_low_conf"
FIRED_BY_REJECTIONS = "auto_abort_rejections"
FIRED_BY_TIMEOUT = "auto_abort_timeout"
FIRED_BY_SESSION_END = "session_end"

VALID_FIRED_BY = {
    FIRED_BY_TRAY,
    FIRED_BY_HOTKEY,
    FIRED_BY_SERVER,
    FIRED_BY_LOW_CONF,
    FIRED_BY_REJECTIONS,
    FIRED_BY_TIMEOUT,
    FIRED_BY_SESSION_END,
}

# Legacy short aliases — kept so the pre-G34.3 scaffold tests (and any
# in-flight call sites passing the old names) continue to work. The DB
# layer normalizes back to the canonical names via _persist_kill().
_FIRED_BY_ALIASES = {
    "server": FIRED_BY_SERVER,
}


# Callback type: (session_id, reason, fired_by) -> awaitable
KillHook = Callable[[str, str, str], Awaitable[None]]


@dataclass
class KillSwitch:
    session_id: str
    killed: bool = False
    reason: str = ""
    fired_at: str = ""
    fired_by: str = ""
    _event: asyncio.Event = field(default_factory=asyncio.Event)
    _hooks: list[KillHook] = field(default_factory=list)

    def register_hook(self, hook: KillHook) -> None:
        """Add a callback fired AFTER the killed flag is set.

        Hooks run sequentially in registration order. Exceptions are
        swallowed and logged — one misbehaving hook cannot block another
        from running, and cannot prevent the session from terminating.
        """
        self._hooks.append(hook)

    def fire(self, reason: str, fired_by: str = FIRED_BY_SERVER) -> None:
        if self.killed:
            return
        # Preserve the literal value the caller used when they passed an
        # alias (the test_scaffold suite asserts on "server" specifically).
        # We accept the alias as valid but don't normalize.
        if fired_by not in VALID_FIRED_BY and fired_by not in _FIRED_BY_ALIASES:
            log.warning("killswitch: unknown fired_by=%s — coercing to server", fired_by)
            fired_by = FIRED_BY_SERVER
        self.killed = True
        self.reason = reason
        self.fired_by = fired_by
        self.fired_at = datetime.now(timezone.utc).isoformat()
        self._event.set()
        log.warning(
            "killswitch fired session=%s by=%s reason=%s",
            self.session_id, fired_by, reason,
        )
        # Schedule async hooks on the running loop. If there's no loop
        # (sync test), the hooks will be invoked lazily on next `await
        # killswitch.run_hooks()` from caller — we still set the flag
        # synchronously so polling code sees it immediately.
        if self._hooks:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._run_hooks())
            except RuntimeError:
                log.debug("no running loop — hooks will run on next await")

    async def run_hooks(self) -> None:
        """Public entrypoint for sync callers to flush pending hooks."""
        await self._run_hooks()

    async def _run_hooks(self) -> None:
        for hook in list(self._hooks):
            try:
                await hook(self.session_id, self.reason, self.fired_by)
            except Exception as exc:  # noqa: BLE001 — hook misbehaviour must not block kill
                log.warning("killswitch hook error session=%s: %s", self.session_id, exc)

    @property
    def is_killed(self) -> bool:
        return self.killed

    async def wait(self) -> None:
        await self._event.wait()


# ── Global registry ─────────────────────────────────────────────────────────


class KillSwitchRegistry:
    """Process-wide map: session_id → KillSwitch.

    Wired by the SessionManager at create_session() time. FastAPI handler in
    `api/remote_sessions.py` looks switches up by session_id from this
    registry so the HTTP layer doesn't need to know about the in-memory
    RemoteSession dataclass.
    """

    def __init__(self) -> None:
        self._switches: dict[str, KillSwitch] = {}

    def register(self, switch: KillSwitch) -> None:
        self._switches[switch.session_id] = switch

    def get(self, session_id: str) -> KillSwitch | None:
        return self._switches.get(session_id)

    def drop(self, session_id: str) -> None:
        self._switches.pop(session_id, None)

    def fire(self, session_id: str, reason: str, fired_by: str) -> bool:
        """Fire by session_id if registered. Returns True iff a switch existed."""
        sw = self._switches.get(session_id)
        if sw is None:
            log.warning("kill request for unknown session=%s by=%s", session_id, fired_by)
            return False
        sw.fire(reason, fired_by=fired_by)
        return True


_registry: KillSwitchRegistry | None = None


def registry() -> KillSwitchRegistry:
    global _registry
    if _registry is None:
        _registry = KillSwitchRegistry()
    return _registry
