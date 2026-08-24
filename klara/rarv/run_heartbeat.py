#!/usr/bin/env python3
"""
klara/rarv/run_heartbeat.py
───────────────────────────
Standalone RARV heartbeat runner — replaces the Celery task wrapper.

Invoked by the systemd timer klara-rarv-heartbeat.timer every 30 min.
Runs the 4-agent RARV pipeline (Reasoner → Writer → Reflector → Verifier)
against pending note_submissions rows and commits results to the git vault.

Usage:
    python3 klara/rarv/run_heartbeat.py [--batch-size N]

Environment (required):
    DATABASE_URL          — Azure klaravex-db-r2 (via klaravex-db-tunnel.service)
    GITHUB_VAULT_TOKEN     — GitHub PAT for the vault repo
    GITHUB_VAULT_REPO      — astewarttcml-netizen/klaravex-vault
    GITHUB_VAULT_BRANCH    — main
    LITELLM_BASE_URL       — http://localhost:8000
    LITELLM_API_KEY        — LiteLLM gateway key

Environment (optional):
    DB_SCHEMA              — klaravex (default)
    VAULT_PATH             — local vault clone path
    APP_DEBUG              — enable debug logging
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure Klaravex2.0 is on PYTHONPATH so `klara.*` resolves.
_KLARAVEX2_ROOT = Path(__file__).resolve().parents[2]  # Klaravex2.0/
if str(_KLARAVEX2_ROOT) not in sys.path:
    sys.path.insert(0, str(_KLARAVEX2_ROOT))

from klara.rarv.runtime import configure_logging, get_settings  # noqa: E402
from klara.rarv.tasks.rarv_heartbeat import BATCH_SIZE_DEFAULT, _heartbeat  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="RARV heartbeat standalone runner")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE_DEFAULT,
        help=f"Max submissions to process per run (default: {BATCH_SIZE_DEFAULT})",
    )
    args = parser.parse_args()

    configure_logging(debug=get_settings().app_debug)

    try:
        summary = asyncio.run(_heartbeat(batch_size=args.batch_size))
    except Exception as exc:
        print(f"rarv_heartbeat.fatal: {exc}", file=sys.stderr, flush=True)
        return 1

    ok = summary.get("ok", False)
    print(
        f"rarv_heartbeat.done: "
        f"reclaimed={summary.get('reclaimed', 0)} "
        f"claimed={summary.get('claimed', 0)} "
        f"written={summary.get('written', 0)} "
        f"rejected={summary.get('rejected', 0)} "
        f"failed={summary.get('failed', 0)} "
        f"ok={ok}",
        flush=True,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
