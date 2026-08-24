"""Pytest collection config for the rustdesk_controller package.

Excludes manual integration scripts from test collection. These are
standalone CLI tools that run `asyncio.run(main())` at module top level and
read argv (e.g. peer id + session password); they are NOT pytest modules and
would crash during collection with an IndexError when the module executes.
"""

from __future__ import annotations

collect_ignore = [
    # Fast-mouse probe — manual live-shim script; connects to a real relay,
    # requires argv[1]=peer_id and argv[2]=password. Never collect.
    "fast_mouse_test.py",
]
