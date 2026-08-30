"""Per-action side-effect sent-log (gate decision #41).

Every external side effect (proposal sent, message posted, bid placed,
email dispatched) is recorded with a deterministic idempotency key BEFORE/AT
execution. Retries after any failure query the log and skip already-sent
actions instead of starting from zero — no double-sends.

Storage: append-only JSONL at growth/data/sent-log.jsonl, fsync'd on write.
CLI for charter sessions and ops:
    python -m growth.outreach.sent_log check <action_key>   # exit 0 if sent
    python -m growth.outreach.sent_log record <action_key> --stream leads \
        --action email --target alice@example.com [--meta '{"k":"v"}']
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_GROWTH_ROOT = Path(__file__).resolve().parents[1]
SENT_LOG_PATH = Path(
    os.getenv("GROWTH_SENT_LOG", str(_GROWTH_ROOT / "data" / "sent-log.jsonl"))
).resolve()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_action_key(stream: str, source: str, action: str, target: str) -> str:
    """Deterministic idempotency key for one external side effect.

    source: stable identifier of the originating artifact (e.g. outbox file
    name); action: verb (email/proposal/post/bid); target: recipient/handle.
    """
    raw = f"{stream}|{source}|{action}|{target}".lower().strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _iter_entries(path: Path = SENT_LOG_PATH):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def already_sent(action_key: str, *, path: Path = SENT_LOG_PATH) -> dict[str, Any] | None:
    """Return the sent-log entry for action_key, or None if never sent."""
    found = None
    for entry in _iter_entries(path):
        if entry.get("action_key") == action_key:
            found = entry
    return found


def record_sent(
    action_key: str,
    *,
    stream: str,
    action: str,
    target: str,
    run_id: str | None = None,
    meta: dict[str, Any] | None = None,
    path: Path = SENT_LOG_PATH,
) -> dict[str, Any]:
    """Append a side-effect record. Caller must have already checked
    already_sent(); this function is deliberately not conditional so callers
    surface races instead of silently swallowing them."""
    entry = {
        "action_key": action_key,
        "stream": stream,
        "action": action,
        "target": target,
        "run_id": run_id,
        "sent_at": _utcnow(),
        "meta": meta or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return entry


def main() -> int:
    p = argparse.ArgumentParser(description="Growth side-effect sent-log")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="exit 0 if action_key already sent")
    c.add_argument("action_key")
    r = sub.add_parser("record", help="record a sent side effect")
    r.add_argument("action_key")
    r.add_argument("--stream", required=True)
    r.add_argument("--action", required=True)
    r.add_argument("--target", required=True)
    r.add_argument("--run-id", default=None)
    r.add_argument("--meta", default=None, help="JSON object of extra metadata")
    args = p.parse_args()

    if args.cmd == "check":
        entry = already_sent(args.action_key)
        if entry:
            print(json.dumps(entry, ensure_ascii=False))
            return 0
        return 1
    meta = json.loads(args.meta) if args.meta else None
    entry = record_sent(
        args.action_key,
        stream=args.stream,
        action=args.action,
        target=args.target,
        run_id=args.run_id,
        meta=meta,
    )
    print(json.dumps(entry, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
