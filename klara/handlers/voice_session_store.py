"""Lightweight in-process session store for Twilio voice call context.

Stores arbitrary string values keyed by CallSid so that issue descriptions
collected early in the call flow (before payment) are available to the
troubleshoot handler after payment confirmation.

Not persisted across restarts — acceptable because calls are short-lived.
"""

_store: dict[str, dict[str, str]] = {}


def set_value(call_sid: str, key: str, value: str) -> None:
    _store.setdefault(call_sid, {})[key] = value


def get_value(call_sid: str, key: str, default: str = "") -> str:
    return _store.get(call_sid, {}).get(key, default)


def clear(call_sid: str) -> None:
    _store.pop(call_sid, None)
