#!/usr/bin/env python3
"""Port Loki backend code into Klaravex2.0 as the Klara AI package.

Mechanical, reversible, and conservative:
  - COPY (never move) sources into Klaravex2.0/klara/
  - Rewrite Python package imports:  loki_handlers -> klara.handlers
  - Rebrand USER-FACING strings:     Loki -> Klara AI (voice/copy/console labels)
  - PRESERVE infra identifiers (env vars, DB schema/table names, docker paths)
    so the running system keeps working; those are aliased, not renamed.

Run from anywhere. Idempotent (re-copies fresh each run).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

HANDLERS_SRC = Path("/home/anthony/klaravex/infra/loki_handlers")
AGENTS_SRC = Path("/home/anthony/itexperts-berlin/loki-agents/app")
KLARA_ROOT = Path("/home/anthony/Klaravex2.0/klara")
HANDLERS_DST = KLARA_ROOT / "handlers"
AGENTS_DST = KLARA_ROOT / "agents"

# Dirs we never copy.
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache"}

# --- Import renames (package structure) -------------------------------------
IMPORT_RENAMES = [
    (re.compile(r"\bloki_handlers\b"), "klara.handlers"),
    (re.compile(r"\binfra\.loki_handlers\b"), "klara.handlers"),
]

# --- User-facing brand renames (strings only, case-preserving) ---------------
# Applied to string literals / comments. We deliberately do NOT touch:
#   LOKI_INTERNAL_SECRET, LOKI_SECRET (env var names)
#   DB schema/table/column names containing loki
#   docker container/volume/image names
BRAND_RENAMES = [
    (re.compile(r"\bLoki\b"), "Klara AI"),
    (re.compile(r"\bLOKI\b"), "KLARA AI"),
]

# Tokens that must NOT be brand-renamed even if they match (infra identifiers).
PRESERVE_SUBSTRINGS = ("LOKI_INTERNAL_SECRET", "LOKI_SECRET")


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def transform_python(text: str) -> str:
    for pat, repl in IMPORT_RENAMES:
        text = pat.sub(repl, text)
    # Brand renames, but protect infra identifiers first.
    protected: dict[str, str] = {}
    for i, tok in enumerate(PRESERVE_SUBSTRINGS):
        placeholder = f"__PRESERVE_LOKI_{i}__"
        if tok in text:
            protected[placeholder] = tok
            text = text.replace(tok, placeholder)
    for pat, repl in BRAND_RENAMES:
        text = pat.sub(repl, text)
    for placeholder, tok in protected.items():
        text = text.replace(placeholder, tok)
    return text


def copy_tree(src: Path, dst: Path) -> tuple[int, int]:
    """Copy src->dst, transforming .py files. Returns (files, transformed)."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    files = 0
    transformed = 0
    for item in src.rglob("*"):
        if should_skip(item):
            continue
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.suffix == ".py":
            original = item.read_text(encoding="utf-8", errors="replace")
            new = transform_python(original)
            target.write_text(new, encoding="utf-8")
            files += 1
            if new != original:
                transformed += 1
        else:
            shutil.copy2(item, target)
            files += 1
    return files, transformed


def main() -> None:
    KLARA_ROOT.mkdir(parents=True, exist_ok=True)

    # Package markers.
    (KLARA_ROOT / "__init__.py").write_text(
        '"""Klara AI backend — ported from Loki (2026-08-24)."""\n', encoding="utf-8"
    )

    h_files, h_trans = copy_tree(HANDLERS_SRC, HANDLERS_DST)
    a_files, a_trans = copy_tree(AGENTS_SRC, AGENTS_DST)

    # Ensure subpackage __init__ files exist where sources had them.
    for pkg_init in [HANDLERS_DST / "__init__.py", AGENTS_DST / "__init__.py"]:
        if not pkg_init.exists():
            pkg_init.write_text("", encoding="utf-8")

    print(f"handlers: {h_files} files copied, {h_trans} transformed -> {HANDLERS_DST}")
    print(f"agents:   {a_files} files copied, {a_trans} transformed -> {AGENTS_DST}")


if __name__ == "__main__":
    main()
