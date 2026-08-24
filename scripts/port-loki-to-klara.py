#!/usr/bin/env python3
"""Port Loki backend code into Klaravex2.0 as the Klara AI package.

Mechanical, reversible, and conservative:
  - COPY (never move) sources into Klaravex2.0/klara/
  - Rewrite Python package imports:  loki_handlers -> klara.handlers
  - Rebrand USER-FACING strings:     Loki -> Klara AI (voice/copy/console labels)
  - PRESERVE infra identifiers (env vars, DB schema/table names, docker paths)
    so the running system keeps working; those are aliased, not renamed.

Ports (Track 1):
  1. handlers   — infra/loki_handlers              -> klara/handlers/
  2. agents     — itexperts-berlin/loki-agents/app  -> klara/agents/
  3. rarv       — infra/tasks/rarv_* + journal + note_submission -> klara/rarv/
  4. watchdog   — infra/watchdog + scripts/watchdog + beat-watchdog -> klara/watchdog/
  5. rustdesk   — infra/rustdesk_controller         -> klara/rustdesk/
  6. voice      — infra/voice-pipeline + vapi-prompts + vapi_assistants -> klara/voice/
  7. vault-mcp  — infra/docker-services/loki-vault-mcp -> klara/vault-mcp/
  8. flows      — infra/loki-flows + n8n-workflows + cron -> klara/flows/ + klara/n8n-workflows/ + klara/cron/
  9. beat       — app/api/beat_trigger.py + infra/api/beat_trigger.py -> klara/beat/

Run from anywhere. Idempotent (re-copies fresh each run).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

KLARAVEX = Path("/home/anthony/klaravex")
KLARA_ROOT = Path("/home/anthony/Klaravex2.0/klara")

# --- Source roots -----------------------------------------------------------
HANDLERS_SRC = KLARAVEX / "infra/loki_handlers"
AGENTS_SRC = Path("/home/anthony/itexperts-berlin/loki-agents/app")

# --- Dirs we never copy -----------------------------------------------------
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules",
             ".pytest_cache", ".mypy_cache", ".ruff_cache", "package-lock.json",
             "target",  # target = Rust build artifacts
             "dist",    # dist = packaged build output (AppImage, exe, etc.)
             "binaries"}  # binaries = pre-built bundled binaries

# --- Import renames (package structure) -------------------------------------
IMPORT_RENAMES = [
    (re.compile(r"\bloki_handlers\b"), "klara.handlers"),
    (re.compile(r"\binfra\.loki_handlers\b"), "klara.handlers"),
    (re.compile(r"\binfra\.tasks\b"), "klara.rarv.tasks"),
    (re.compile(r"\binfra\.agents\.journal\b"), "klara.rarv.journal"),
    (re.compile(r"\binfra\.models\b"), "klara.rarv"),
    (re.compile(r"\binfra\.watchdog\b"), "klara.watchdog"),
    (re.compile(r"\binfra\.rustdesk_controller\b"), "klara.rustdesk"),
    (re.compile(r"\binfra\.voice_pipeline\b"), "klara.voice"),
    (re.compile(r"\binfra\.docker_services\.loki_vault_mcp\b"), "klara.vault_mcp"),
    (re.compile(r"\binfra\.loki_flows\b"), "klara.flows"),
    (re.compile(r"\binfra\.n8n_workflows\b"), "klara.n8n_workflows"),
    (re.compile(r"\binfra\.cron\b"), "klara.cron"),
    (re.compile(r"\bapp\.api\.beat_trigger\b"), "klara.beat.beat_trigger"),
    # app.* -> klara.rarv.* (RARV runtime shim)
    (re.compile(r"\bapp\.database\b"), "klara.rarv.runtime"),
    (re.compile(r"\bapp\.config\b"), "klara.rarv.runtime"),
    (re.compile(r"\bapp\.agents\.base\b"), "klara.rarv.runtime"),
    (re.compile(r"\bapp\.core\.permissions\b"), "klara.rarv.runtime"),
    (re.compile(r"\bapp\.services\.notes\b"), "klara.rarv.runtime.notes_service"),
    (re.compile(r"\bapp\.services\b"), "klara.rarv.runtime"),
    (re.compile(r"\bapp\.tasks\.celery_app\b"), "klara.rarv.runtime"),
    (re.compile(r"\bapp\.tasks\.celery_klaravex\b"), "klara.rarv.runtime"),
    (re.compile(r"\bapp\.tasks\.rarv_heartbeat\b"), "klara.rarv.tasks.rarv_heartbeat"),
    (re.compile(r"\bapp\.tasks\.rarv_rebuild\b"), "klara.rarv.tasks.rarv_rebuild"),
    (re.compile(r"\bapp\.core\.logging\b"), "klara.rarv.runtime"),
    (re.compile(r"\bapp\.agents\.journal\b"), "klara.rarv.journal"),
    (re.compile(r"\bapp\.models\.note_submission\b"), "klara.rarv.note_submission"),
    (re.compile(r"\bapp\.models\b(?!\.note_submission)"), "klara.rarv"),
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
PRESERVE_SUBSTRINGS = ("LOKI_INTERNAL_SECRET", "LOKI_SECRET",
                       "X-Loki-Internal-Secret", "x-loki-internal-secret")

# --- File extensions that get text transforms (brand renames) ---------------
# .py files additionally get import renames.
TEXT_EXTS = {".py", ".md", ".yaml", ".yml", ".json", ".sh", ".service",
             ".txt", ".sql", ".conf", ".toml", ".cfg", ".ini", ".js", ".ts",
             ".env", ".gitignore", ".dockerfile"}


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def _apply_brand_renames(text: str) -> str:
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


def transform_python(text: str) -> str:
    for pat, repl in IMPORT_RENAMES:
        text = pat.sub(repl, text)
    return _apply_brand_renames(text)


def transform_text(text: str) -> str:
    return _apply_brand_renames(text)


def copy_tree(src: Path, dst: Path) -> tuple[int, int]:
    """Copy src->dst, transforming text files. Returns (files, transformed)."""
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
        elif item.suffix in TEXT_EXTS or item.name in TEXT_EXTS:
            original = item.read_text(encoding="utf-8", errors="replace")
            new = transform_text(original)
            target.write_text(new, encoding="utf-8")
            files += 1
            if new != original:
                transformed += 1
        else:
            shutil.copy2(item, target)
            files += 1
    return files, transformed


def copy_file(src: Path, dst: Path) -> tuple[int, int]:
    """Copy a single file src->dst with transform. Returns (1, transformed)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".py":
        original = src.read_text(encoding="utf-8", errors="replace")
        new = transform_python(original)
        dst.write_text(new, encoding="utf-8")
        return 1, 1 if new != original else 0
    elif src.suffix in TEXT_EXTS or src.name in TEXT_EXTS:
        original = src.read_text(encoding="utf-8", errors="replace")
        new = transform_text(original)
        dst.write_text(new, encoding="utf-8")
        return 1, 1 if new != original else 0
    else:
        shutil.copy2(src, dst)
        return 1, 0


def port_dir(name: str, src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"  SKIP {name}: source not found ({src})")
        return
    files, trans = copy_tree(src, dst)
    print(f"  {name}: {files} files copied, {trans} transformed -> {dst}")


def port_file(name: str, src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"  SKIP {name}: source not found ({src})")
        return
    _, trans = copy_file(src, dst)
    print(f"  {name}: 1 file copied, {trans} transformed -> {dst}")


def main() -> None:
    KLARA_ROOT.mkdir(parents=True, exist_ok=True)

    # Package markers.
    (KLARA_ROOT / "__init__.py").write_text(
        '"""Klara AI backend — ported from Loki (2026-08-24)."""\n', encoding="utf-8"
    )

    print("=== Track 1: Port all Loki functions 1:1 ===\n")

    # 1. Handlers (existing)
    print("[handlers + agents]")
    port_dir("handlers", HANDLERS_SRC, KLARA_ROOT / "handlers")
    port_dir("agents", AGENTS_SRC, KLARA_ROOT / "agents")
    for pkg_init in [KLARA_ROOT / "handlers" / "__init__.py",
                     KLARA_ROOT / "agents" / "__init__.py"]:
        if not pkg_init.exists():
            pkg_init.write_text("", encoding="utf-8")

    # 2. RARV pipeline (1.1)
    print("\n[1.1 RARV pipeline]")
    rarv_dst = KLARA_ROOT / "rarv"
    rarv_tasks_dst = rarv_dst / "tasks"
    if rarv_tasks_dst.exists():
        shutil.rmtree(rarv_tasks_dst)
    rarv_tasks_dst.mkdir(parents=True, exist_ok=True)
    # Only copy RARV-specific files + celery app files from infra/tasks/
    rarv_task_files = [
        "rarv_heartbeat.py", "rarv_heartbeat_klaravex.py",
        "rarv_rebuild.py", "rarv_rebuild_klaravex.py",
        "rarv_lint.py",
        "celery_app.py", "celery_klaravex.py",
    ]
    rarv_t_files = 0
    rarv_t_trans = 0
    for fname in rarv_task_files:
        src = KLARAVEX / "infra/tasks" / fname
        if src.exists():
            f, t = copy_file(src, rarv_tasks_dst / fname)
            rarv_t_files += f
            rarv_t_trans += t
    print(f"  rarv/tasks: {rarv_t_files} files copied, {rarv_t_trans} transformed -> {rarv_tasks_dst}")
    port_dir("rarv/journal", KLARAVEX / "infra/agents/journal", rarv_dst / "journal")
    port_file("rarv/note_submission", KLARAVEX / "infra/models/note_submission.py",
              rarv_dst / "note_submission.py")
    for pkg_init in [rarv_dst / "__init__.py", rarv_dst / "tasks" / "__init__.py",
                     rarv_dst / "journal" / "__init__.py"]:
        if not pkg_init.exists():
            pkg_init.write_text("", encoding="utf-8")

    # 3. Watchdog (1.2)
    print("\n[1.2 Watchdog]")
    wd_dst = KLARA_ROOT / "watchdog"
    port_dir("watchdog/infra", KLARAVEX / "infra/watchdog", wd_dst / "infra")
    port_dir("watchdog/scripts", KLARAVEX / "scripts/watchdog", wd_dst / "scripts")
    port_file("watchdog/beat-watchdog.sh",
              KLARAVEX / "infra/scripts/klaravex-beat-watchdog.sh",
              wd_dst / "klaravex-beat-watchdog.sh")
    port_file("watchdog/beat-watchdog.service",
              KLARAVEX / "infra/scripts/klaravex-beat-watchdog.service",
              wd_dst / "klaravex-beat-watchdog.service")
    for pkg_init in [wd_dst / "__init__.py", wd_dst / "infra" / "__init__.py",
                     wd_dst / "scripts" / "__init__.py"]:
        if not pkg_init.exists():
            pkg_init.write_text("", encoding="utf-8")

    # 4. RustDesk recording sink (1.3)
    print("\n[1.3 RustDesk controller]")
    port_dir("rustdesk", KLARAVEX / "infra/rustdesk_controller", KLARA_ROOT / "rustdesk")
    for pkg_init in [KLARA_ROOT / "rustdesk" / "__init__.py"]:
        if not pkg_init.exists():
            pkg_init.write_text("", encoding="utf-8")

    # 5. Voice infrastructure (1.4)
    print("\n[1.4 Voice infrastructure]")
    voice_dst = KLARA_ROOT / "voice"
    port_dir("voice/pipeline", KLARAVEX / "infra/voice-pipeline", voice_dst / "pipeline")
    port_dir("voice/prompts", KLARAVEX / "infra/vapi-prompts", voice_dst / "prompts")
    port_file("voice/vapi_assistants.json",
              KLARAVEX / "infra/vapi_assistants.json",
              voice_dst / "vapi_assistants.json")
    for pkg_init in [voice_dst / "__init__.py", voice_dst / "pipeline" / "__init__.py"]:
        if not pkg_init.exists():
            pkg_init.write_text("", encoding="utf-8")

    # 6. Vault MCP (1.5)
    print("\n[1.5 Vault MCP]")
    port_dir("vault-mcp", KLARAVEX / "infra/docker-services/loki-vault-mcp",
             KLARA_ROOT / "vault-mcp")
    for pkg_init in [KLARA_ROOT / "vault-mcp" / "__init__.py"]:
        if not pkg_init.exists():
            pkg_init.write_text("", encoding="utf-8")

    # 7. Flows + resolution regression (1.6)
    print("\n[1.6 Flows + resolution regression]")
    port_dir("flows", KLARAVEX / "infra/loki-flows", KLARA_ROOT / "flows")
    port_dir("n8n-workflows", KLARAVEX / "infra/n8n-workflows", KLARA_ROOT / "n8n-workflows")
    cron_dst = KLARA_ROOT / "cron"
    cron_dst.mkdir(parents=True, exist_ok=True)
    port_file("cron/loki_resolution_regression",
              KLARAVEX / "infra/cron/loki_resolution_regression.py",
              cron_dst / "loki_resolution_regression.py")
    for pkg_init in [KLARA_ROOT / "flows" / "__init__.py",
                     KLARA_ROOT / "n8n-workflows" / "__init__.py",
                     cron_dst / "__init__.py"]:
        if not pkg_init.exists():
            pkg_init.write_text("", encoding="utf-8")

    # 8. Beat trigger (1.7)
    print("\n[1.7 Beat trigger]")
    beat_dst = KLARA_ROOT / "beat"
    beat_dst.mkdir(parents=True, exist_ok=True)
    port_file("beat/beat_trigger (app)", KLARAVEX / "app/api/beat_trigger.py",
              beat_dst / "beat_trigger.py")
    port_file("beat/beat_trigger (infra)", KLARAVEX / "infra/api/beat_trigger.py",
              beat_dst / "beat_trigger_infra.py")
    for pkg_init in [beat_dst / "__init__.py"]:
        if not pkg_init.exists():
            pkg_init.write_text("", encoding="utf-8")

    print("\n=== Port complete ===")


if __name__ == "__main__":
    main()
