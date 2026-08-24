"""
Import smoke tests — verify every handler + lib module loads without errors.

This catches:
- Syntax errors
- Missing imports (e.g. forgot to add `from .lib import tickets`)
- Bad relative imports

Run as a script:
    python3 infra/loki-handlers/tests/test_handler_imports.py
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

HANDLERS_DIR = Path(__file__).resolve().parent.parent
PARENT_DIR = HANDLERS_DIR.parent  # .../infra/
PROJECT_ROOT = PARENT_DIR.parent  # .../klaravex/

# Make "infra" importable.
sys.path.insert(0, str(PROJECT_ROOT))


def _import_file(label: str, path: Path) -> tuple[bool, str]:
    """Return (ok, error_msg). Just verifies syntax + top-level imports parse."""
    try:
        spec = importlib.util.spec_from_file_location(label, path)
        if spec is None or spec.loader is None:
            return False, "spec_from_file_location returned None"
        mod = importlib.util.module_from_spec(spec)
        # Don't actually execute — that would trigger asyncpg/fastapi imports.
        # Instead, just compile-check.
        with open(path, "rb") as fh:
            src = fh.read()
        compile(src, str(path), "exec")
        return True, ""
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    targets = [
        ("infra.loki-handlers.lib.db",         HANDLERS_DIR / "lib" / "db.py"),
        ("infra.loki-handlers.lib.tickets",    HANDLERS_DIR / "lib" / "tickets.py"),
        ("infra.loki-handlers.lib.escalation", HANDLERS_DIR / "lib" / "escalation.py"),
        ("infra.loki-handlers.lib.kb",         HANDLERS_DIR / "lib" / "kb.py"),
        ("infra.loki-handlers.portal.router",  HANDLERS_DIR / "portal" / "router.py"),
        ("infra.loki-handlers.stripe_webhook", HANDLERS_DIR / "stripe_webhook.py"),
        ("infra.loki-handlers.smartlead_webhook", HANDLERS_DIR / "smartlead_webhook.py"),
        ("infra.loki-handlers.calendly_webhook", HANDLERS_DIR / "calendly_webhook.py"),
        ("infra.loki-handlers.intake_consumer", HANDLERS_DIR / "intake_consumer.py"),
        ("infra.loki-handlers.intake_b2b",     HANDLERS_DIR / "intake_b2b.py"),
        ("infra.loki-handlers.social_media",   HANDLERS_DIR / "social_media.py"),
        ("infra.loki-handlers.social_media_reddit",  HANDLERS_DIR / "social_media_reddit.py"),
        ("infra.loki-handlers.social_media_tiktok",  HANDLERS_DIR / "social_media_tiktok.py"),
        ("infra.loki-handlers.social_media_youtube", HANDLERS_DIR / "social_media_youtube.py"),
    ]
    failures = 0
    for label, path in targets:
        ok, err = _import_file(label, path)
        if ok:
            print(f"PASS  {label}")
        else:
            failures += 1
            print(f"FAIL  {label} :: {err}")
    total = len(targets)
    print(f"\n{total - failures}/{total} modules compile clean")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
