"""Orchestrate leads pre-enrichment before charter execution."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from growth.poc import is_poc_mode
from growth.poc.materialize import materialize_leads_research
from growth.research.dedupe import collect_excluded_domains

logger = logging.getLogger("growth.research")

_GROWTH_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _GROWTH_ROOT.parent
KLARAVEX_ROOT = Path(os.getenv("GROWTH_KLARAVEX_ROOT", "/home/anthony/klaravex")).resolve()
KLARAVEX_PYTHON = Path(
    os.getenv(
        "GROWTH_KLARAVEX_PYTHON",
        str(_REPO_ROOT / ".venv" / "bin" / "python"),
    )
).resolve()
RESEARCH_ENABLED = os.getenv("GROWTH_RESEARCH_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
RESEARCH_MIN_CONFIDENCE = float(os.getenv("GROWTH_RESEARCH_MIN_CONFIDENCE", "0.30"))
RESEARCH_MAX_PROSPECTS = int(os.getenv("GROWTH_RESEARCH_MAX_PROSPECTS", "100"))
RESEARCH_CONCURRENCY = int(os.getenv("GROWTH_RESEARCH_CONCURRENCY", "8"))
RESEARCH_TIMEOUT_S = int(os.getenv("GROWTH_RESEARCH_TIMEOUT_S", "3600"))
ARTIFACT_DIR = Path(
    os.getenv("GROWTH_RESEARCH_ARTIFACT_DIR", str(_GROWTH_ROOT / "data" / "research"))
).resolve()
WORKER_SCRIPT = Path(__file__).resolve().parent / "klaravex_worker.py"


def run_leads_pre_enrichment(
    *,
    run_id: str,
    revenue_agents_root: Path,
) -> dict[str, Any] | None:
    """
    Run Apollo shortlist + 11-scraper research via legacy klaravex subprocess.

    Returns metadata dict with artifact_dir path, or None when disabled/failed.
    """
    if not RESEARCH_ENABLED:
        logger.info("research pre-enrichment disabled run_id=%s", run_id)
        return None

    output_dir = ARTIFACT_DIR / run_id
    if is_poc_mode():
        logger.info("POC mode: using fixture research run_id=%s", run_id)
        return materialize_leads_research(run_id=run_id, output_dir=output_dir)

    if not KLARAVEX_PYTHON.is_file():
        logger.error("klaravex python missing: %s", KLARAVEX_PYTHON)
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    excluded = sorted(collect_excluded_domains(revenue_agents_root))
    max_prospects = int(os.getenv("GROWTH_RESEARCH_MAX_PROSPECTS", "100"))
    min_confidence = float(os.getenv("GROWTH_RESEARCH_MIN_CONFIDENCE", "0.30"))
    concurrency = int(os.getenv("GROWTH_RESEARCH_CONCURRENCY", "8"))
    timeout_s = int(os.getenv("GROWTH_RESEARCH_TIMEOUT_S", "3600"))

    cmd = [
        str(KLARAVEX_PYTHON),
        str(WORKER_SCRIPT),
        "--run-id",
        run_id,
        "--output-dir",
        str(output_dir),
        "--klaravex-root",
        str(KLARAVEX_ROOT),
        "--max-prospects",
        str(max_prospects),
        "--min-confidence",
        str(min_confidence),
        "--concurrency",
        str(concurrency),
        "--excluded-domains",
        *excluded,
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(_REPO_ROOT), str(KLARAVEX_ROOT), env.get("PYTHONPATH", "")) if p
    )

    logger.info(
        "starting research pre-enrichment run_id=%s output=%s excluded=%d max=%s concurrency=%s",
        run_id,
        output_dir,
        len(excluded),
        max_prospects,
        concurrency,
    )

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("research pre-enrichment timeout run_id=%s", run_id)
        return None

    if proc.returncode != 0:
        logger.error(
            "research worker failed run_id=%s code=%s stderr=%s",
            run_id,
            proc.returncode,
            (proc.stderr or "")[:500],
        )
        err_path = output_dir / "worker.error.log"
        err_path.write_text(
            f"exit_code={proc.returncode}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}",
            encoding="utf-8",
        )
        return None

    summary_path = output_dir / "summary.json"
    summary: dict[str, Any] = {}
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {}

    meta = {
        "artifact_dir": str(output_dir),
        "run_id": run_id,
        "excluded_domain_count": len(excluded),
        "enriched_count": summary.get("enriched_count", 0),
        "skipped_count": summary.get("skipped_count", 0),
        "min_confidence": RESEARCH_MIN_CONFIDENCE,
    }
    logger.info("research pre-enrichment done run_id=%s meta=%s", run_id, meta)
    return meta


def load_leads_research_meta(research_run_id: str) -> dict[str, Any] | None:
    """Load an existing research artifact bundle (charter-only retry)."""
    output_dir = ARTIFACT_DIR / research_run_id
    if not output_dir.is_dir():
        logger.error("research bundle missing: %s", output_dir)
        return None
    summary_path = output_dir / "summary.json"
    if not summary_path.is_file():
        logger.error("research summary missing: %s", summary_path)
        return None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("research summary unreadable run_id=%s: %s", research_run_id, exc)
        return None
    return {
        "artifact_dir": str(output_dir),
        "run_id": research_run_id,
        "reused": True,
        "enriched_count": summary.get("enriched_count", 0),
        "skipped_count": summary.get("skipped_count", 0),
        "min_confidence": summary.get("min_confidence", RESEARCH_MIN_CONFIDENCE),
    }
