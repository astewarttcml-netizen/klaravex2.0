"""Launch and track Claude charter sessions for Growth OS streams."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from growth.executor.prompts import build_charter_prompt
from growth.poc import POC_FIXTURES_DIR, is_poc_mode, stream_fixture_path
from growth.poc.materialize import materialize_poc_charter, poc_fast_enabled

logger = logging.getLogger("growth.executor")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GROWTH_ROOT = _REPO_ROOT / "growth"
EXECUTOR_LOG_DIR = Path(
    os.getenv("GROWTH_EXECUTOR_LOG_DIR", str(_GROWTH_ROOT / "data" / "executor"))
).resolve()

EXECUTOR_ENABLED = os.getenv("GROWTH_EXECUTOR_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
EXECUTOR_DRY_RUN = os.getenv("GROWTH_EXECUTOR_DRY_RUN", "false").lower() in {"1", "true", "yes", "on"}
CLAUDE_BIN = os.getenv("GROWTH_CLAUDE_BIN", "claude")
KLARAVEX_ROOT = Path(os.getenv("GROWTH_KLARAVEX_ROOT", "/home/anthony/klaravex")).resolve()
EXECUTOR_TIMEOUT_S = int(os.getenv("GROWTH_EXECUTOR_TIMEOUT_S", "7200"))
EXECUTOR_MODEL = os.getenv("GROWTH_EXECUTOR_MODEL", "").strip()
BYPASS_PERMISSIONS = os.getenv("GROWTH_EXECUTOR_BYPASS_PERMISSIONS", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EXECUTOR_TOOLS = os.getenv(
    "GROWTH_EXECUTOR_TOOLS",
    "Read,Write,Edit,Glob,Grep,Bash",
).strip()
TWO_PHASE = os.getenv("GROWTH_EXECUTOR_TWO_PHASE", "true").lower() in {"1", "true", "yes", "on"}
LEADS_PROGRAMMATIC_DRAFT = os.getenv("GROWTH_LEADS_PROGRAMMATIC_DRAFT", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
GATED_STREAMS = ("socials", "seo-blog", "kb", "leads", "backlinks", "forums")

_DONE_RE = re.compile(r"^DONE stream=\S+ run_id=\S+ files=", re.MULTILINE)
_DONE_PLACEHOLDER_MARKERS = ("<comma-separated",)
_LEADS_RESEARCH_SECTION_RE = re.compile(r"^## RESEARCH\s*[—–-]\s*prospect-\d+-", re.M)
_LEADS_OUTREACH_SECTION_RE = re.compile(r"^## OUTREACH\s*[—–-]\s*prospect-\d+-", re.M)
_LEADS_SECTION_SLUG_RE = re.compile(
    r"^## (?:RESEARCH|OUTREACH)\s*[—–-]\s*prospect-\d+-(\S+)\s*$",
    re.M | re.I,
)


def ensure_outbox_dirs(revenue_agents_root: Path, stream: str) -> Path:
    outbox = revenue_agents_root / "outbox" / stream
    outbox.mkdir(parents=True, exist_ok=True)
    return outbox


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extra_add_dirs(revenue_agents_root: Path) -> list[Path]:
    dirs = [
        revenue_agents_root,
        revenue_agents_root / "charters",
        revenue_agents_root / "outbox",
        KLARAVEX_ROOT,
    ]
    marketing = KLARAVEX_ROOT / "marketing"
    if marketing.is_dir():
        dirs.append(marketing)
    vault = Path("/home/anthony/.claude/knowledge/klaravex-vault")
    if vault.is_dir():
        dirs.append(vault)
    seen: set[Path] = set()
    unique: list[Path] = []
    for d in dirs:
        resolved = d.resolve()
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def build_claude_command(
    *,
    stream: str,
    run_id: str,
    revenue_agents_root: Path,
    research_artifact_dir: Path | None = None,
    research_meta: dict | None = None,
    prompt_phase: str = "full",
) -> list[str]:
    prompt = build_charter_prompt(
        stream=stream,
        run_id=run_id,
        revenue_agents_root=revenue_agents_root,
        klaravex_root=KLARAVEX_ROOT,
        research_artifact_dir=research_artifact_dir,
        research_meta=research_meta,
        prompt_phase=prompt_phase,
    )
    cmd: list[str] = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--output-format",
        "text",
    ]
    if EXECUTOR_MODEL:
        cmd.extend(["--model", EXECUTOR_MODEL])
    if BYPASS_PERMISSIONS:
        cmd.append("--dangerously-skip-permissions")
    if EXECUTOR_TOOLS:
        cmd.extend(["--tools", EXECUTOR_TOOLS])
    for d in _extra_add_dirs(revenue_agents_root):
        cmd.extend(["--add-dir", str(d)])
    if research_artifact_dir and research_artifact_dir.is_dir():
        cmd.extend(["--add-dir", str(research_artifact_dir.resolve())])
    if is_poc_mode() and POC_FIXTURES_DIR.is_dir():
        cmd.extend(["--add-dir", str(POC_FIXTURES_DIR)])
        fixture = stream_fixture_path(stream)
        if fixture is not None:
            cmd.extend(["--add-dir", str(fixture.parent.resolve())])
    return cmd


def run_charter_subprocess(
    *,
    stream: str,
    run_id: str,
    revenue_agents_root: Path,
    log_path: Path,
    research_artifact_dir: Path | None = None,
    research_meta: dict | None = None,
    prompt_phase: str = "full",
) -> tuple[int, str, str]:
    ensure_outbox_dirs(revenue_agents_root, stream)
    cmd = build_claude_command(
        stream=stream,
        run_id=run_id,
        revenue_agents_root=revenue_agents_root,
        research_artifact_dir=research_artifact_dir,
        research_meta=research_meta,
        prompt_phase=prompt_phase,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("starting charter run stream=%s run_id=%s log=%s", stream, run_id, log_path)
    with log_path.open("w", encoding="utf-8") as log_fh:
        log_fh.write(f"# charter run stream={stream} run_id={run_id}\n")
        log_fh.write(f"# started_at={_utcnow()}\n")
        log_fh.write(f"# cmd={' '.join(cmd[:4])} ...\n\n")
        log_fh.flush()
        proc = subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=EXECUTOR_TIMEOUT_S,
            check=False,
        )
        log_fh.write(proc.stdout or "")
        log_fh.write(f"\n\n# exit_code={proc.returncode}\n# finished_at={_utcnow()}\n")
    return proc.returncode, proc.stdout or "", str(log_path)


def _is_real_done_line(line: str) -> bool:
    if not _DONE_RE.match(line):
        return False
    lower = line.lower()
    return not any(marker in lower for marker in _DONE_PLACEHOLDER_MARKERS)


def _non_empty_lines(stdout: str) -> list[str]:
    return [line.strip() for line in stdout.splitlines() if line.strip()]


def _parse_done_summary(stdout: str, *, stream: str, run_id: str) -> tuple[str | None, str | None]:
    """
    Parse the machine-readable DONE handshake line.

    Returns (summary, error_detail). When error_detail is set, summary is None.
    """
    lines = _non_empty_lines(stdout)
    real_done = [line for line in lines if _is_real_done_line(line)]
    if not real_done:
        return None, None
    summary = real_done[-1]
    if f"stream={stream}" not in summary or f"run_id={run_id}" not in summary:
        return None, "DONE line run_id/stream mismatch"
    if lines[-1] != summary:
        return None, "DONE line is not the final non-empty line of Claude output"
    return summary, None


def _misplaced_leads_files(started_epoch: float) -> list[Path]:
    """Detect charter drafts written outside revenue-agents/outbox/leads/."""
    outreach_dir = _GROWTH_ROOT / "outreach"
    if not outreach_dir.is_dir():
        return []
    found: list[Path] = []
    for path in outreach_dir.rglob("*.md"):
        if path.name.startswith("."):
            continue
        # Skip archived executor run folders under growth/outreach/
        if "32db5c01" in path.parts:
            continue
        try:
            if path.stat().st_mtime >= started_epoch - 1:
                found.append(path)
        except OSError:
            continue
    return sorted(found)


def _wrong_path_hint(stream: str, started_epoch: float, revenue_agents_root: Path) -> str:
    if stream != "leads":
        return ""
    misplaced = _misplaced_leads_files(started_epoch)
    if not misplaced:
        return ""
    names = ", ".join(p.name for p in misplaced[:6])
    extra = f" (+{len(misplaced) - 6} more)" if len(misplaced) > 6 else ""
    expected = revenue_agents_root / "outbox" / "leads"
    return (
        f"; misplaced writes under growth/outreach/: {names}{extra}"
        f" (expected single charter file in {expected}/)"
    )


def _shortlist_slugs(research_artifact_dir: Path | None) -> set[str]:
    if research_artifact_dir is None or not research_artifact_dir.is_dir():
        return set()
    summary_path = research_artifact_dir / "summary.json"
    if summary_path.is_file():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            return {
                str(entry["slug"]).strip()
                for entry in data.get("enriched", [])
                if isinstance(entry, dict) and entry.get("slug")
            }
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    shortlist_path = research_artifact_dir / "shortlist.json"
    if not shortlist_path.is_file():
        return set()
    try:
        data = json.loads(shortlist_path.read_text(encoding="utf-8"))
        prospects = data.get("prospects") if isinstance(data, dict) else data
        if not isinstance(prospects, list):
            return set()
        slugs: set[str] = set()
        for prospect in prospects:
            if not isinstance(prospect, dict):
                continue
            slug = prospect.get("slug")
            if slug:
                slugs.add(str(slug).strip())
                continue
            domain = str(prospect.get("domain") or "").strip().lower()
            company = str(prospect.get("company_name") or prospect.get("company") or "").strip().lower()
            if domain and company:
                slug = re.sub(r"[^a-z0-9]+", "-", f"{company}-{domain}").strip("-")
                if slug:
                    slugs.add(slug)
        return slugs
    except (OSError, json.JSONDecodeError, TypeError):
        return set()


def _outbox_leads_slugs(body: str) -> set[str]:
    return {match.strip() for match in _LEADS_SECTION_SLUG_RE.findall(body)}


def _leads_outbox_schema_ok(body: str) -> bool:
    return bool(_LEADS_RESEARCH_SECTION_RE.search(body) and _LEADS_OUTREACH_SECTION_RE.search(body))


def _leads_outbox_paths_for_done(artifacts: list[Path]) -> list[str]:
    paths: list[str] = []
    for path in artifacts:
        try:
            rel = path.resolve().relative_to(_REPO_ROOT.resolve())
            paths.append(str(rel))
        except ValueError:
            paths.append(str(path.resolve()))
    return paths


def _synthesize_done_line(*, stream: str, run_id: str, artifacts: list[Path]) -> str:
    files = ",".join(_leads_outbox_paths_for_done(artifacts))
    return f"DONE stream={stream} run_id={run_id} files={files}"


def _programmatic_leads_outbox(
    *,
    run_id: str,
    revenue_agents_root: Path,
    research_artifact_dir: Path,
) -> Path | None:
    from zoneinfo import ZoneInfo

    from growth.outreach.leads_assembler import assemble_from_research

    tz_name = os.getenv("GROWTH_TIMEZONE", "America/New_York")
    try:
        today = datetime.now(ZoneInfo(tz_name)).date().isoformat()
    except Exception:
        today = datetime.now(timezone.utc).date().isoformat()
    out_path = (
        revenue_agents_root
        / "outbox"
        / "leads"
        / f"{today}-us-law-accounting-medical-shortlist.md"
    )
    result = assemble_from_research(
        research_dir=research_artifact_dir,
        output_path=out_path,
        run_id=run_id,
    )
    if int(result.get("drafted_count") or 0) < 1:
        logger.warning("programmatic leads draft wrote 0 outreach sections run_id=%s", run_id)
        return None
    logger.info(
        "programmatic leads draft run_id=%s drafted=%s path=%s",
        run_id,
        result.get("drafted_count"),
        out_path,
    )
    return out_path


def _check_leads_artifacts(
    artifacts: list[Path],
    research_artifact_dir: Path | None,
) -> tuple[bool, str]:
    if not artifacts:
        return False, "no new outbox artifacts"
    allowed_slugs = _shortlist_slugs(research_artifact_dir)
    for path in artifacts:
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False, f"unreadable outbox file {path.name}"
        if not _leads_outbox_schema_ok(body):
            return False, f"missing charter ## RESEARCH/## OUTREACH prospect sections in {path.name}"
        try:
            from growth.gatekeeper.adjudicate import evaluate

            verdict = evaluate(body, "leads")
            if verdict["status"] != "APPROVED":
                fails = "; ".join(verdict["failures"] or [str({k: v[0] for k, v in verdict["checks"].items()})])
                return False, f"leads draft would be REJECTED by gatekeeper: {fails}"
        except Exception as exc:  # noqa: BLE001
            return False, f"leads gate preflight failed: {exc}"
        if allowed_slugs:
            unknown = sorted(_outbox_leads_slugs(body) - allowed_slugs)
            if unknown:
                return False, f"prospect slugs not in research shortlist: {unknown}"
    return True, ""


def _newly_gated_files(revenue_agents_root: Path, started_epoch: float) -> list[Path]:
    found: list[Path] = []
    for stream in GATED_STREAMS:
        outbox = revenue_agents_root / "outbox" / stream
        if not outbox.is_dir():
            continue
        for path in outbox.rglob("*.md"):
            if path.name.startswith("."):
                continue
            try:
                if path.stat().st_mtime < started_epoch - 1:
                    continue
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "## GATE VERDICT" in body:
                found.append(path)
    return sorted(found)


def _outbox_files_since(revenue_agents_root: Path, stream: str, since_epoch: float) -> list[Path]:
    outbox = revenue_agents_root / "outbox" / stream
    if not outbox.is_dir():
        return []
    found: list[Path] = []
    for path in outbox.rglob("*.md"):
        if path.name.startswith("."):
            continue
        try:
            if path.stat().st_mtime >= since_epoch:
                found.append(path)
        except OSError:
            continue
    return sorted(found)


def _validate_charter_result(
    *,
    stream: str,
    run_id: str,
    code: int,
    stdout: str,
    revenue_agents_root: Path,
    started_epoch: float,
    research_artifact_dir: Path | None = None,
) -> tuple[bool, str]:
    path_hint = _wrong_path_hint(stream, started_epoch, revenue_agents_root)
    summary, done_err = _parse_done_summary(stdout, stream=stream, run_id=run_id)
    if code != 0:
        return False, (summary or f"claude exit code {code}") + path_hint
    if done_err:
        return False, f"charter session exited 0: {done_err}{path_hint}"
    if not summary:
        return False, f"charter session exited 0 but missing DONE summary line{path_hint}"
    if "files=none" in summary.lower() and stream != "gatekeeper":
        artifacts = _outbox_files_since(revenue_agents_root, stream, started_epoch)
        if not artifacts:
            return False, f"{summary} (no new outbox artifacts)"
    if stream == "leads" and "files=none" not in summary.lower():
        artifacts = _outbox_files_since(revenue_agents_root, stream, started_epoch)
        ok, err = _check_leads_artifacts(artifacts, research_artifact_dir)
        if not ok:
            return False, f"{summary} ({err})"
    return True, summary


def _run_programmatic_gatekeeper(revenue_agents_root: Path) -> list[dict]:
    from growth.gatekeeper.adjudicate import adjudicate_outbox

    return adjudicate_outbox(revenue_agents_root)


def execute_charter_run(
    *,
    run_id: str,
    stream: str,
    revenue_agents_root: Path,
    on_update: Callable[[str, dict[str, Any]], None],
    research_run_id: str | None = None,
) -> None:
    log_path = EXECUTOR_LOG_DIR / f"{run_id}.log"
    research_artifact_dir: Path | None = None
    research_meta: dict | None = None

    if stream == "leads":
        try:
            from growth.research.pre_enrich import (
                load_leads_research_meta,
                run_leads_pre_enrichment,
            )

            if research_run_id:
                research_meta = load_leads_research_meta(research_run_id)
                if research_meta and research_meta.get("artifact_dir"):
                    research_artifact_dir = Path(research_meta["artifact_dir"])
                    logger.info(
                        "reusing research bundle research_run_id=%s for charter run_id=%s",
                        research_run_id,
                        run_id,
                    )
                else:
                    research_meta = {"error": f"research bundle not found: {research_run_id}"}
            else:
                research_meta = run_leads_pre_enrichment(
                    run_id=run_id,
                    revenue_agents_root=revenue_agents_root,
                )
                if research_meta and research_meta.get("artifact_dir"):
                    research_artifact_dir = Path(research_meta["artifact_dir"])
        except Exception as exc:  # noqa: BLE001 — non-fatal; charter can still run
            logger.exception("research pre-enrichment failed run_id=%s", run_id)
            research_meta = {"error": str(exc)}

    on_update(
        run_id,
        {
            "status": "running",
            "started_at": _utcnow(),
            "executor_log": str(log_path),
            **(
                {
                    "research_artifact_dir": research_meta.get("artifact_dir"),
                    "research_enriched_count": research_meta.get("enriched_count"),
                    "research_skipped_count": research_meta.get("skipped_count"),
                    "poc_mode": research_meta.get("poc_mode", is_poc_mode()),
                    **(
                        {"research_run_id": research_run_id, "research_reused": True}
                        if research_run_id
                        else {}
                    ),
                }
                if research_meta and research_meta.get("artifact_dir")
                else {"poc_mode": is_poc_mode()} if is_poc_mode() else {}
            ),
        },
    )

    if not EXECUTOR_ENABLED:
        on_update(
            run_id,
            {
                "status": "failed",
                "finished_at": _utcnow(),
                "detail": "GROWTH_EXECUTOR_ENABLED=false",
            },
        )
        return

    if EXECUTOR_DRY_RUN:
        cmd = build_claude_command(
            stream=stream,
            run_id=run_id,
            revenue_agents_root=revenue_agents_root,
            research_artifact_dir=research_artifact_dir,
            research_meta=research_meta,
        )
        on_update(
            run_id,
            {
                "status": "completed",
                "finished_at": _utcnow(),
                "detail": f"dry_run cmd={' '.join(cmd[:6])} ...",
                "executor_log": str(log_path),
            },
        )
        logger.info("dry_run charter stream=%s run_id=%s", stream, run_id)
        return

    if poc_fast_enabled():
        ok, detail = materialize_poc_charter(
            stream=stream,
            run_id=run_id,
            revenue_agents_root=revenue_agents_root,
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# POC fast charter stream={stream} run_id={run_id}\n{detail}\n",
            encoding="utf-8",
        )
        on_update(
            run_id,
            {
                "status": "completed" if ok else "failed",
                "finished_at": _utcnow(),
                "detail": detail if ok else f"POC fast failed: {detail}",
                "executor_log": str(log_path),
                "poc_fast": True,
            },
        )
        logger.info("poc_fast charter stream=%s run_id=%s ok=%s", stream, run_id, ok)
        return

    if (
        stream == "leads"
        and LEADS_PROGRAMMATIC_DRAFT
        and research_artifact_dir is not None
        and int((research_meta or {}).get("enriched_count") or 0) > 0
    ):
        try:
            drafted_path = _programmatic_leads_outbox(
                run_id=run_id,
                revenue_agents_root=revenue_agents_root,
                research_artifact_dir=research_artifact_dir,
            )
        except Exception as exc:  # noqa: BLE001 — fall through to Claude
            logger.exception("programmatic leads draft failed run_id=%s: %s", run_id, exc)
            drafted_path = None
        if drafted_path is not None:
            artifacts = [drafted_path]
            ok, err = _check_leads_artifacts(artifacts, research_artifact_dir)
            summary_line = _synthesize_done_line(stream=stream, run_id=run_id, artifacts=artifacts)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as log_fh:
                log_fh.write(
                    f"\n# programmatic leads draft from research\n{summary_line}\n"
                    f"# schema_ok={ok} err={err}\n"
                )
            if ok:
                on_update(
                    run_id,
                    {
                        "status": "completed",
                        "finished_at": _utcnow(),
                        "detail": summary_line + " (programmatic research draft)",
                        "executor_log": str(log_path),
                        "synthesized_done": True,
                        "programmatic_leads_draft": True,
                    },
                )
                logger.info("charter completed stream=%s run_id=%s programmatic draft", stream, run_id)
                return

    try:
        started_epoch = datetime.now(timezone.utc).timestamp()
        prompt_phase = "write" if stream in {"leads", "gatekeeper"} and TWO_PHASE else "full"
        code, stdout, log_file = run_charter_subprocess(
            stream=stream,
            run_id=run_id,
            revenue_agents_root=revenue_agents_root,
            log_path=log_path,
            research_artifact_dir=research_artifact_dir,
            research_meta=research_meta,
            prompt_phase=prompt_phase,
        )
    except subprocess.TimeoutExpired:
        on_update(
            run_id,
            {
                "status": "failed",
                "finished_at": _utcnow(),
                "detail": f"timeout after {EXECUTOR_TIMEOUT_S}s",
                "executor_log": str(log_path),
            },
        )
        logger.error("charter timeout stream=%s run_id=%s", stream, run_id)
        return
    except FileNotFoundError:
        on_update(
            run_id,
            {
                "status": "failed",
                "finished_at": _utcnow(),
                "detail": f"claude binary not found: {CLAUDE_BIN}",
            },
        )
        logger.error("claude binary missing: %s", CLAUDE_BIN)
        return
    except Exception as exc:  # noqa: BLE001 — surface executor failures in ledger
        on_update(
            run_id,
            {
                "status": "failed",
                "finished_at": _utcnow(),
                "detail": f"executor error: {exc}",
                "executor_log": str(log_path),
            },
        )
        logger.exception("charter executor failed stream=%s run_id=%s", stream, run_id)
        return

    synthesized_done = False
    gatekeeper_fallback = False
    if stream == "gatekeeper" and code == 0:
        pre_gated = _newly_gated_files(revenue_agents_root, started_epoch)
        if not pre_gated:
            fallback_results = _run_programmatic_gatekeeper(revenue_agents_root)
            gated = [r for r in fallback_results if r.get("status") in {"approved", "rejected"}]
            if gated:
                gatekeeper_fallback = True
                with Path(log_file).open("a", encoding="utf-8") as log_fh:
                    log_fh.write(
                        f"\n# executor gatekeeper fallback adjudicated {len(gated)} file(s)\n"
                        f"{json.dumps(fallback_results, indent=2)[:4000]}\n"
                    )
                logger.info(
                    "gatekeeper fallback adjudicated %d files run_id=%s",
                    len(gated),
                    run_id,
                )

    if TWO_PHASE and code == 0 and (
        stream in {"leads", "gatekeeper"} or f"DONE stream={stream}" not in stdout
    ):
        artifacts: list[Path] = []
        if stream == "leads":
            artifacts = _outbox_files_since(revenue_agents_root, stream, started_epoch)
            leads_ok, _ = _check_leads_artifacts(artifacts, research_artifact_dir)
            if not leads_ok:
                artifacts = []
        elif stream == "gatekeeper":
            artifacts = _newly_gated_files(revenue_agents_root, started_epoch)
        else:
            # Any stream: session wrote outbox files but skipped the DONE
            # handshake (recurring failure mode) — synthesize it.
            artifacts = _outbox_files_since(revenue_agents_root, stream, started_epoch)
        if artifacts:
            summary_line = _synthesize_done_line(stream=stream, run_id=run_id, artifacts=artifacts)
            stdout = stdout.rstrip() + "\n" + summary_line + "\n"
            synthesized_done = True
            with Path(log_file).open("a", encoding="utf-8") as log_fh:
                log_fh.write(f"\n# executor phase-2 synthesized DONE\n{summary_line}\n")

    ok, detail = _validate_charter_result(
        stream=stream,
        run_id=run_id,
        code=code,
        stdout=stdout,
        revenue_agents_root=revenue_agents_root,
        started_epoch=started_epoch,
        research_artifact_dir=research_artifact_dir,
    )
    if ok:
        on_update(
            run_id,
            {
                "status": "completed",
                "finished_at": _utcnow(),
                "detail": detail
                + (" (executor synthesized DONE)" if synthesized_done else "")
                + (" (programmatic gatekeeper fallback)" if gatekeeper_fallback else ""),
                "executor_log": log_file,
                **({"synthesized_done": True} if synthesized_done else {}),
                **({"gatekeeper_fallback": True} if gatekeeper_fallback else {}),
            },
        )
        logger.info("charter completed stream=%s run_id=%s", stream, run_id)
        if stream == "gatekeeper":
            from growth.outreach.dispatch_bridge import maybe_dispatch_after_gatekeeper

            dispatch_out = maybe_dispatch_after_gatekeeper(revenue_agents_root)
            if dispatch_out is not None:
                on_update(
                    run_id,
                    {
                        "dispatch_bridge": dispatch_out.get("summary"),
                        "detail": detail
                        + (" (executor synthesized DONE)" if synthesized_done else "")
                        + (" (programmatic gatekeeper fallback)" if gatekeeper_fallback else "")
                        + (
                            f" (dispatch ok={dispatch_out.get('summary', {}).get('ok', 0)})"
                            if dispatch_out.get("summary")
                            else ""
                        ),
                    },
                )
        return

    on_update(
        run_id,
        {
            "status": "failed",
            "finished_at": _utcnow(),
            "detail": detail,
            "executor_log": log_file,
        },
    )
    logger.error("charter failed stream=%s run_id=%s detail=%s", stream, run_id, detail)


def schedule_charter_run(
    *,
    run_id: str,
    stream: str,
    revenue_agents_root: Path,
    on_update: Callable[[str, dict[str, Any]], None],
    research_run_id: str | None = None,
) -> None:
    thread = threading.Thread(
        target=execute_charter_run,
        kwargs={
            "run_id": run_id,
            "stream": stream,
            "revenue_agents_root": revenue_agents_root,
            "on_update": on_update,
            "research_run_id": research_run_id,
        },
        name=f"growth-charter-{stream}-{run_id[:8]}",
        daemon=True,
    )
    thread.start()
