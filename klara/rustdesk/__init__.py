"""Klaravex AI Remote Session — headless RustDesk controller (G34).

This package is the operator side of the AI Remote Session product. It speaks
the RustDesk protocol as the controlling peer: connects to a customer session,
receives the framebuffer, hands frames to Claude computer-use, and emits
mouse / keyboard events back over the protocol.

Component map (matches docs/architecture/ai-remote-session.md):

    protocol.py   — RustDesk client transport (frame ingest + input emit)
    vision.py     — Claude Opus computer-use action predictor
    consent.py    — consent capture + immutable audit log
    recording.py  — JSONL event + frame capture to object storage (§5)
    killswitch.py — 3-path session-kill enforcement (§1)
    session.py    — per-session state machine, latency budget, confirm gate
    voice_tools.py — FastAPI router exposing the 4 Klara tools (§4)

The scaffold is intentionally protocol-layer-stubbed so the higher-level
session loop, consent / recording / killswitch contracts, and voice tool
shapes are wired and testable while the librustdesk FFI binding lands in
a subsequent iteration (G34.1).

DO NOT import this package at FastAPI startup without the `RUSTDESK_CONTROLLER_ENABLED`
environment flag — it is feature-gated so partial scaffolding never breaks
production webhook routes.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "controller",
    "protocol",
    "vision",
    "consent",
    "recording",
    "killswitch",
    "session",
    "voice_tools",
    "rdshim_ipc",
    "factory",
    "mock_customer_shim",
    "__version__",
]
