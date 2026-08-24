"""Copy POC fixture research into a per-run artifact directory."""

from __future__ import annotations

import json
import logging
import shutil
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from growth.poc import leads_fixture_dir, stream_fixture_path

logger = logging.getLogger("growth.poc")


def materialize_leads_research(*, run_id: str, output_dir: Path) -> dict[str, Any] | None:
    """
    Stage fictional leads research fixtures for a charter run.

    Skips Apollo and the legacy 11-scraper worker when GROWTH_POC_MODE=true.
    """
    source = leads_fixture_dir()
    if not source.is_dir():
        logger.error("POC leads fixtures missing: %s", source)
        return None

    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(source, output_dir)

    summary_path = output_dir / "summary.json"
    summary: dict[str, Any] = {}
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["run_id"] = run_id
    summary["poc_mode"] = True
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    shortlist_path = output_dir / "shortlist.json"
    if shortlist_path.is_file():
        shortlist = json.loads(shortlist_path.read_text(encoding="utf-8"))
        meta = shortlist.setdefault("meta", {})
        meta["run_id"] = run_id
        meta["poc_mode"] = True
        meta["apollo_configured"] = False
        shortlist_path.write_text(json.dumps(shortlist, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    readme_path = output_dir / "README.md"
    enriched = summary.get("enriched_count", 0)
    skipped = summary.get("skipped_count", 0)
    prospect_count = len(summary.get("enriched", [])) + len(summary.get("skipped", []))
    readme_path.write_text(
        "\n".join(
            [
                "# Research pre-enrichment (POC fixtures)",
                "",
                f"- Run ID: `{run_id}`",
                f"- Mode: **POC** — fictional prospects only; no Apollo or live scrapers",
                f"- Prospects in fixture set: {prospect_count}",
                f"- Enriched (confidence >= {summary.get('min_confidence', 0.30)}): {enriched}",
                f"- Skipped: {skipped}",
                "",
                "Read each `*/bundle.summary.md` before drafting outreach.",
                "Do **not** send or publish to any `.example` domain.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    meta = {
        "artifact_dir": str(output_dir),
        "run_id": run_id,
        "poc_mode": True,
        "excluded_domain_count": 0,
        "enriched_count": summary.get("enriched_count", 0),
        "skipped_count": summary.get("skipped_count", 0),
        "min_confidence": summary.get("min_confidence", 0.30),
    }
    logger.info("POC leads fixtures materialized run_id=%s dir=%s", run_id, output_dir)
    return meta


def _today_slug() -> str:
    return date.today().isoformat()


def _write_leads_poc_outbox(*, run_id: str, revenue_agents_root: Path) -> list[Path]:
    """Minimal leads outbox drafts from POC research bundles."""
    outbox = revenue_agents_root / "outbox" / "leads"
    outbox.mkdir(parents=True, exist_ok=True)
    source = leads_fixture_dir()
    written: list[Path] = []
    for prospect_dir in sorted(source.iterdir()):
        if not prospect_dir.is_dir() or prospect_dir.name in {"README.md"}:
            continue
        summary_path = prospect_dir / "bundle.summary.md"
        if not summary_path.is_file():
            continue
        slug = prospect_dir.name.split("-")[0] if "-" in prospect_dir.name else prospect_dir.name
        path = outbox / f"{_today_slug()}-{slug}-poc.md"
        summary = summary_path.read_text(encoding="utf-8")
        path.write_text(
            "\n".join(
                [
                    f"# POC leads draft — {prospect_dir.name}",
                    "",
                    "## RESEARCH",
                    "",
                    summary.strip(),
                    "",
                    "## OUTREACH",
                    "",
                    "Hi — POC fixture outreach for managed security review. "
                    "Signal refs: [job-01] [tech-02]. #poc-fixture",
                    "",
                    f"run_id: `{run_id}`",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def materialize_poc_charter(
    *,
    stream: str,
    run_id: str,
    revenue_agents_root: Path,
) -> tuple[bool, str]:
    """
    Write POC outbox artifact(s) without a live Claude charter session.

    Used when GROWTH_POC_MODE + GROWTH_POC_FAST — completes streams in seconds
    for shadow testing and klaravex-os scorecard validation.
    """
    outbox = revenue_agents_root / "outbox" / stream
    outbox.mkdir(parents=True, exist_ok=True)

    if stream == "leads":
        files = _write_leads_poc_outbox(run_id=run_id, revenue_agents_root=revenue_agents_root)
        if not files:
            return False, "POC leads outbox: no fixture prospects found"
        names = ",".join(str(p.relative_to(revenue_agents_root)) for p in files)
        return True, f"DONE stream={stream} run_id={run_id} files={names}"

    fixture = stream_fixture_path(stream)
    context = fixture.read_text(encoding="utf-8").strip() if fixture else f"POC placeholder for {stream}."
    path = outbox / f"{_today_slug()}-poc-{stream}.md"
    path.write_text(
        "\n".join(
            [
                f"# POC charter — {stream}",
                "",
                context,
                "",
                f"- run_id: `{run_id}`",
                f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
                "- #poc-fixture",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rel = path.relative_to(revenue_agents_root)
    return True, f"DONE stream={stream} run_id={run_id} files={rel}"


def poc_fast_enabled() -> bool:
    if not os.getenv("GROWTH_POC_MODE", "false").lower() in {"1", "true", "yes", "on"}:
        return False
    return os.getenv("GROWTH_POC_FAST", "true").lower() in {"1", "true", "yes", "on"}
