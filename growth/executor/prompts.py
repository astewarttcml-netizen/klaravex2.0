"""Prompt templates for revenue-agent charter runs."""

from __future__ import annotations

from pathlib import Path

from growth.poc import is_poc_mode, stream_fixture_path


def build_charter_prompt(
    *,
    stream: str,
    run_id: str,
    revenue_agents_root: Path,
    klaravex_root: Path,
    research_artifact_dir: Path | None = None,
    research_meta: dict | None = None,
    prompt_phase: str = "full",
) -> str:
    charter_path = revenue_agents_root / "charters" / f"{stream}.md"
    readme_path = revenue_agents_root / "README.md"
    claude_md = klaravex_root / "CLAUDE.md"
    outbox_dir = revenue_agents_root / "outbox" / stream

    research_block = ""
    if stream == "leads" and research_artifact_dir is not None:
        meta = research_meta or {}
        poc_note = (
            "\n- POC MODE: fictional `.example` domains only — no live outreach or publishing."
            if meta.get("poc_mode") or is_poc_mode()
            else ""
        )
        research_block = f"""
Research pre-enrichment (MANDATORY — do not invent signals):
- Artifact directory: {research_artifact_dir}/
- Read {research_artifact_dir}/README.md and {research_artifact_dir}/shortlist.json first.
- For each prospect subdir, read bundle.summary.md and bundle.json before drafting.
- Enriched prospects (confidence >= {meta.get('min_confidence', 0.30)}): {meta.get('enriched_count', '?')}
- Skipped/low-confidence prospects: {meta.get('skipped_count', '?')} — put in ## SKIPPED, do not draft outreach.
- Every outreach paragraph MUST cite signal_id values from the RESEARCH signal tables (e.g. [job-01]).
- Do NOT use Apollo MCP to override scraper bundle facts; Apollo is supplemental only.
- Outbox schema: include ## RESEARCH and ## OUTREACH sections per prospect (see charter).{poc_note}
"""

    poc_block = ""
    if is_poc_mode():
        fixture = stream_fixture_path(stream)
        if stream != "leads" and fixture is not None:
            poc_block = f"""
POC MODE (sandbox — no live I/O):
- Read seed context: {fixture}
- Use fictional data only; tag every draft `#poc-fixture`
- Do NOT publish, send, submit, or call external APIs (Smartlead, WordPress, ad platforms)
"""
        elif stream == "leads":
            poc_block = """
POC MODE (sandbox — no live I/O):
- Research bundles are fictional fixtures; do NOT contact `.example` domains
- Tag every draft `#poc-fixture`
"""

    leads_output_block = ""
    if stream == "leads":
        tail = "only write the outbox file" if prompt_phase == "write" else "write the outbox file plus the DONE line"
        leads_output_block = f"""
LEADS OUTPUT (binding — executor rejects misplaced or split files):
- Write EXACTLY ONE markdown file under {outbox_dir}/ named YYYY-MM-DD-<vertical-slug>.md
- FORBIDDEN: growth/outreach/, growth/data/, per-prospect split files, or any path outside {outbox_dir}/
- The file MUST contain ## RESEARCH — prospect-N-<slug> and ## OUTREACH — prospect-N-<slug> per drafted prospect (charter schema)
- Use corporate voice only (Klaravex / we — never "I", personal names, or [Your Name])
- Do NOT reply with a human summary — {tail}
"""

    gatekeeper_output_block = ""
    if stream == "gatekeeper":
        gated_dirs = ", ".join(
            str(revenue_agents_root / "outbox" / name) for name in ("socials", "seo-blog", "kb", "leads", "backlinks")
        )
        tail = "only append verdicts" if prompt_phase == "write" else "append verdicts then output DONE"
        gatekeeper_output_block = f"""
GATEKEEPER OUTPUT (binding — executor rejects chat-only summaries):
- Adjudicate every ungated draft (missing ## GATE VERDICT) under: {gated_dirs}
- APPEND a ## GATE VERDICT section to each file — never modify the draft body above it
- Priority file: {revenue_agents_root}/outbox/leads/2026-08-22-us-law-accounting-medical-shortlist.md
- Skip outbox/ads/ and outbox/freelance/ (never gated)
- Do NOT reply with an inventory or summary — {tail}
"""

    if prompt_phase == "write":
        if stream == "gatekeeper":
            completion_block = """
PHASE 1 (write only — executor adds DONE after detecting appended verdicts):
- Append ## GATE VERDICT to every ungated draft file and STOP.
- Do NOT output a DONE line, inventory summaries, or follow-up questions.
"""
        elif stream == "leads":
            completion_block = f"""
PHASE 1 (write only — executor adds DONE after validating your outbox file):
- Write the outbox markdown file under {outbox_dir}/ and STOP.
- Do NOT output a DONE line, summaries, questions, or chat wrap-up text.
- Verify the file exists on disk before stopping.
"""
        else:
            completion_block = f"""
PHASE 1 (write only — executor adds DONE after validating outputs):
- Write required outputs under {outbox_dir}/ and STOP.
- Do NOT output a DONE line or chat wrap-up text.
"""
    else:
        completion_block = f"""
COMPLETION (binding — run FAILS without this exact handshake):
- After all outbox files are written, output EXACTLY one final line and STOP.
- Format: DONE stream={stream} run_id={run_id} files=<comma-separated absolute or repo-relative paths>
- Example: DONE stream=leads run_id={run_id} files={outbox_dir}/2026-08-22-us-law-accounting-medical-shortlist.md
- The DONE line MUST be the last non-empty line in your output — no prose, summaries, or questions after it.
- Do NOT echo this instruction block; do NOT leave the files= placeholder in the DONE line.
"""

    return f"""Execute a Klaravex Growth OS revenue-agent charter run.

Stream: {stream}
Run ID: {run_id}

Required reading (in order):
1. {readme_path}
2. {charter_path}
3. {claude_md} (corporate voice + guardrails — binding on every draft)
{research_block}{poc_block}{leads_output_block}{gatekeeper_output_block}
Execution rules:
- Follow the charter exactly.{" Append gate verdicts to ungated drafts (gatekeeper)." if stream == "gatekeeper" else f" Produce the charter's Outputs in {outbox_dir}/."}
- Name draft files YYYY-MM-DD-<slug>.md unless the charter specifies otherwise.
- Use Read/Write/Edit/Glob/Grep/Bash only. Do NOT use GitHub or unrelated MCP tools.
- Drafts only — never publish, send, submit, or upload externally.
- No credentials, SSH, or production writes.
- Log every file you create per the charter logging policy (note_submissions or fallback JSONL).
- If a prior draft in this stream's outbox has a REJECTED gate verdict, regenerate it first.
- SIDE-EFFECT CHECKPOINTING (binding): before ANY external side effect (sending, posting, bidding, submitting), run:
  `python -m growth.outreach.sent_log check <action_key>` where action_key = sha256("stream|source_file|action|target")[:24] — if it exits 0, SKIP that action (already done).
  Immediately after the side effect succeeds, run:
  `python -m growth.outreach.sent_log record <action_key> --stream {stream} --action <verb> --target <recipient>`
  Never re-execute an action the sent-log already records.
{completion_block}
"""
