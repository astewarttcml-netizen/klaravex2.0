"""Klaravex Growth API stub (Layer C) — FastAPI control plane."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

# Load growth/.env before growth submodules read GROWTH_* flags.
_GROWTH_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_GROWTH_ROOT / ".env", override=True)

from growth.api.streams import ALLOWED_STREAMS, is_allowed_stream
from growth.adapters.registry import ADAPTERS, invoke, probe_all
from growth.executor import schedule_charter_run
from growth.poc import POC_FIXTURES_DIR, is_poc_mode

VERSION = "2.0.0-alpha"
logger = logging.getLogger("growth.api")
logging.basicConfig(level=logging.INFO)

_REPO_ROOT = _GROWTH_ROOT.parent

SECRET = os.getenv("GROWTH_INTERNAL_SECRET", "")
GROWTH_ENABLED = os.getenv("GROWTH_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
REVENUE_AGENTS_ROOT = Path(
    os.getenv("REVENUE_AGENTS_ROOT", str(_REPO_ROOT / "revenue-agents"))
).resolve()
PERSIST_RUNS = os.getenv("GROWTH_PERSIST_RUNS", "true").lower() in {"1", "true", "yes", "on"}
RUNS_PATH = _GROWTH_ROOT / "data" / "runs.jsonl"

app = FastAPI(title="Klaravex Growth API", version=VERSION)

# In-memory ledger (also optionally mirrored to JSONL)
_runs: list[dict[str, Any]] = []
_gate_verdicts: list[dict[str, Any]] = []


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    if not PERSIST_RUNS:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _hydrate_runs_from_disk() -> None:
    """Restore in-memory ledger from runs.jsonl after API restart."""
    if not RUNS_PATH.is_file():
        return
    merged: dict[str, dict[str, Any]] = {}
    gate_count = 0
    try:
        for line in RUNS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "gate_verdict":
                _gate_verdicts.append(rec)
                gate_count += 1
                continue
            rid = rec.get("id")
            if not rid:
                continue
            prev = merged.get(rid)
            if prev is None:
                merged[rid] = rec
            else:
                prev.update(rec)
        _runs.extend(sorted(merged.values(), key=lambda x: x.get("started_at", "")))
        logger.info("hydrated %d runs and %d gate verdicts from %s", len(_runs), gate_count, RUNS_PATH)
    except OSError as exc:
        logger.warning("could not hydrate runs ledger: %s", exc)


_hydrate_runs_from_disk()


def _find_run(run_id: str) -> dict[str, Any] | None:
    for run in _runs:
        if run.get("id") == run_id:
            return run
    return None


def _update_run_record(run_id: str, fields: dict[str, Any]) -> None:
    run = _find_run(run_id)
    if run is None:
        return
    run.update(fields)
    snapshot = dict(run)
    snapshot["kind"] = snapshot.get("kind", "stream_run")
    _append_jsonl(RUNS_PATH, snapshot)


def require_secret(x_growth_secret: str | None = Header(default=None, alias="X-Growth-Secret")) -> None:
    if not SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROWTH_INTERNAL_SECRET not configured",
        )
    if not x_growth_secret or x_growth_secret != SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid secret")


RunStatus = Literal["accepted", "running", "completed", "failed"]


class RunRecord(BaseModel):
    id: str
    stream: str
    started_at: str
    status: RunStatus = "accepted"
    detail: str | None = None
    finished_at: str | None = None
    executor_log: str | None = None


class StreamRunBody(BaseModel):
    research_run_id: str | None = None


class GateVerdictBody(BaseModel):
    verdict: Literal["APPROVED", "REJECTED"]
    stream: str | None = None
    reason: str | None = None
    notes: str | None = None


class SessionCookieBody(BaseModel):
    cookie: str = Field(min_length=20, max_length=16384)
    source: str = Field(default="connections", max_length=64)


class UpworkClientBody(BaseModel):
    client_id: str = Field(min_length=8, max_length=256)
    client_secret: str = Field(min_length=8, max_length=512)


class UpworkOAuthCallbackBody(BaseModel):
    code: str = Field(min_length=8, max_length=512)
    state: str = Field(min_length=8, max_length=256)


class UpworkSearchBody(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=8)
    min_budget_usd: float = 0


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "growth_enabled": GROWTH_ENABLED,
        "poc_mode": is_poc_mode(),
        "poc_fixtures_dir": str(POC_FIXTURES_DIR) if is_poc_mode() else None,
        "version": VERSION,
    }


@app.post(
    "/v1/streams/{name}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_secret)],
)
def run_stream(name: str, body: StreamRunBody | None = Body(default=None)) -> RunRecord:
    if not is_allowed_stream(name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown stream; allowed={sorted(ALLOWED_STREAMS)}",
        )
    if not GROWTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROWTH_ENABLED=false",
        )

    research_run_id = body.research_run_id if body else None
    if research_run_id and name != "leads":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="research_run_id is only supported for the leads stream",
        )

    run_id = str(uuid.uuid4())
    record = {
        "id": run_id,
        "stream": name,
        "started_at": _utcnow(),
        "status": "accepted",
        "detail": "charter execution queued",
        "kind": "stream_run",
        "revenue_agents_root": str(REVENUE_AGENTS_ROOT),
    }
    if research_run_id:
        record["research_run_id"] = research_run_id
        record["detail"] = f"charter execution queued (reuse research {research_run_id})"
    _runs.append(record)
    _append_jsonl(RUNS_PATH, record)
    schedule_charter_run(
        run_id=run_id,
        stream=name,
        revenue_agents_root=REVENUE_AGENTS_ROOT,
        on_update=_update_run_record,
        research_run_id=research_run_id,
    )
    logger.info("charter queued stream=%s run_id=%s root=%s", name, run_id, REVENUE_AGENTS_ROOT)
    return RunRecord(
        id=record["id"],
        stream=name,
        started_at=record["started_at"],
        status="accepted",
        detail=record["detail"],
    )


@app.get("/v1/runs/{run_id}", dependencies=[Depends(require_secret)])
def get_run(run_id: str) -> dict[str, Any]:
    run = _find_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run


@app.get("/v1/runs", dependencies=[Depends(require_secret)])
def list_runs() -> dict[str, Any]:
    return {"runs": list(_runs), "count": len(_runs)}


@app.get("/v1/adapters", dependencies=[Depends(require_secret)])
def list_adapters() -> dict[str, Any]:
    adapters = probe_all()
    poc = sum(1 for a in adapters if a.get("status") == "poc_sandbox")
    ready = sum(1 for a in adapters if a.get("status") == "ready")
    stub = sum(1 for a in adapters if a.get("status") == "stub")
    return {
        "adapters": adapters,
        "count": len(adapters),
        "poc_sandbox": poc,
        "ready": ready,
        "stub": stub,
        "poc_mode": is_poc_mode(),
    }


@app.post(
    "/v1/adapters/{name}/invoke",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_secret)],
)
def invoke_adapter(name: str, body: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    """Probe or live-invoke an adapter (optional JSON body for enqueue/publish payloads)."""
    if not GROWTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROWTH_ENABLED=false",
        )
    try:
        result = invoke(name, payload=body)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown adapter; allowed={[a[0] for a in ADAPTERS]}",
        ) from None
    record = {
        "id": str(uuid.uuid4()),
        "kind": "adapter_invoke",
        "stream": name,
        "started_at": _utcnow(),
        "status": "completed",
        "detail": f"adapter:{name} status={result.get('status')}",
        "adapter_result": result,
    }
    _runs.append(record)
    _append_jsonl(RUNS_PATH, record)
    return result


@app.get("/v1/sessions", dependencies=[Depends(require_secret)])
def list_sessions() -> dict[str, Any]:
    """Vault metadata + live probes for Upwork / Guru / PeoplePerHour. Never returns cookies."""
    from growth.sessions.probe import probe
    from growth.sessions.vault import PLATFORMS

    return {"sessions": [probe(name) for name in PLATFORMS], "count": len(PLATFORMS)}


@app.get("/v1/sessions/{name}", dependencies=[Depends(require_secret)])
def get_session(name: str) -> dict[str, Any]:
    from growth.sessions.probe import probe
    from growth.sessions.vault import PLATFORMS

    if name not in PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown session platform; allowed={list(PLATFORMS)}",
        )
    return probe(name)


@app.put("/v1/sessions/{name}", dependencies=[Depends(require_secret)])
def put_session(name: str, body: SessionCookieBody) -> dict[str, Any]:
    from growth.sessions.probe import probe
    from growth.sessions.vault import PLATFORMS, save_cookie

    if name not in PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown session platform; allowed={list(PLATFORMS)}",
        )
    try:
        save_cookie(name, body.cookie, source=body.source)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    return probe(name)


@app.delete("/v1/sessions/{name}", dependencies=[Depends(require_secret)])
def delete_session(name: str) -> dict[str, Any]:
    from growth.sessions.probe import probe
    from growth.sessions.vault import PLATFORMS, delete_cookie

    if name not in PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown session platform; allowed={list(PLATFORMS)}",
        )
    delete_cookie(name)
    return probe(name)


@app.get("/v1/upwork/status", dependencies=[Depends(require_secret)])
def upwork_status() -> dict[str, Any]:
    from growth.upwork.graphql import probe_status

    return probe_status()


@app.put("/v1/upwork/oauth/credentials", dependencies=[Depends(require_secret)])
def upwork_save_credentials(body: UpworkClientBody) -> dict[str, Any]:
    from growth.upwork.oauth import save_client

    try:
        return save_client(body.client_id, body.client_secret)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None


@app.get("/v1/upwork/oauth/start", dependencies=[Depends(require_secret)])
def upwork_oauth_start() -> dict[str, Any]:
    from growth.upwork.oauth import authorize_url

    try:
        return authorize_url()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None


@app.post("/v1/upwork/oauth/callback", dependencies=[Depends(require_secret)])
def upwork_oauth_callback(body: UpworkOAuthCallbackBody) -> dict[str, Any]:
    from growth.upwork.graphql import probe_status
    from growth.upwork.oauth import exchange_code

    try:
        exchange_code(body.code, body.state)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
    return probe_status()


@app.delete("/v1/upwork/oauth", dependencies=[Depends(require_secret)])
def upwork_oauth_delete() -> dict[str, Any]:
    from growth.upwork.graphql import probe_status
    from growth.upwork.oauth import delete_tokens

    delete_tokens()
    return probe_status()


@app.post("/v1/upwork/search", dependencies=[Depends(require_secret)])
def upwork_search(body: UpworkSearchBody) -> dict[str, Any]:
    from growth.upwork.graphql import search_jobs

    try:
        jobs = search_jobs(body.keywords, min_budget_usd=body.min_budget_usd)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
    return {"count": len(jobs), "jobs": jobs}


@app.post(
    "/v1/streams/run-all",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_secret)],
)
def run_all_streams() -> dict[str, Any]:
    """Trigger every allowed stream (POC / pre-cutover smoke test)."""
    if not GROWTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROWTH_ENABLED=false",
        )
    queued: list[RunRecord] = []
    for name in sorted(ALLOWED_STREAMS):
        queued.append(run_stream(name))
    return {"queued": len(queued), "runs": [r.model_dump() for r in queued]}


@app.get("/v1/scorecard", dependencies=[Depends(require_secret)])
def scorecard() -> dict[str, Any]:
    by_stream: dict[str, dict[str, int]] = {}
    for r in _runs:
        stream = r.get("stream", "unknown")
        st = r.get("status", "unknown")
        bucket = by_stream.setdefault(stream, {})
        bucket[st] = bucket.get(st, 0) + 1
    return {
        "version": VERSION,
        "total_runs": len(_runs),
        "by_stream": by_stream,
        "gate_verdicts": len(_gate_verdicts),
        "growth_enabled": GROWTH_ENABLED,
        "poc_mode": is_poc_mode(),
    }


@app.post(
    "/v1/gate/{draft_id}/verdict",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_secret)],
)
def gate_verdict(draft_id: str, body: GateVerdictBody) -> dict[str, Any]:
    """Record a gate verdict. Unknown draft_id is accepted and recorded (stub)."""
    if not GROWTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROWTH_ENABLED=false",
        )
    record = {
        "id": str(uuid.uuid4()),
        "kind": "gate_verdict",
        "draft_id": draft_id,
        "verdict": body.verdict,
        "stream": body.stream,
        "reason": body.reason,
        "notes": body.notes,
        "started_at": _utcnow(),
        "status": "accepted",
        "draft_known": False,  # stub: no draft index yet
    }
    _gate_verdicts.append(record)
    _runs.append(
        {
            "id": record["id"],
            "stream": body.stream or "gatekeeper",
            "started_at": record["started_at"],
            "status": "accepted",
            "detail": f"gate:{body.verdict}:{draft_id}",
            "kind": "gate_verdict",
        }
    )
    _append_jsonl(RUNS_PATH, record)
    logger.info("gate verdict draft_id=%s verdict=%s", draft_id, body.verdict)
    return record


@app.get("/v1/digests", dependencies=[Depends(require_secret)])
def list_digests() -> dict[str, Any]:
    """Latest Nadia/Marco accountability digests (read from outbox/digests)."""
    digests_dir = REVENUE_AGENTS_ROOT / "outbox" / "digests"
    items: list[dict[str, Any]] = []
    if digests_dir.is_dir():
        for path in sorted(digests_dir.glob("*.md"), reverse=True)[:20]:
            stem = path.stem  # YYYY-MM-DD-nadia
            parts = stem.rsplit("-", 1)
            head_id = parts[-1] if len(parts) == 2 else "unknown"
            day = parts[0] if len(parts) == 2 else stem
            items.append(
                {
                    "date": day,
                    "head_id": head_id,
                    "path": str(path),
                    "name": path.name,
                    "preview": path.read_text(encoding="utf-8", errors="replace")[:1200],
                }
            )
    return {"count": len(items), "digests": items}


@app.post(
    "/v1/digests/generate",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_secret)],
)
def generate_head_digests(day: str | None = None) -> dict[str, Any]:
    """Write today's (or given) digests for Nadia and Marco."""
    if not GROWTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROWTH_ENABLED=false",
        )
    from growth.digests.heads import generate_digests

    payload = generate_digests(
        day=day,
        write=True,
        revenue_agents_root=REVENUE_AGENTS_ROOT,
        runs_path=RUNS_PATH,
    )
    record = {
        "id": str(uuid.uuid4()),
        "kind": "digest_generate",
        "stream": "digests",
        "started_at": _utcnow(),
        "status": "completed",
        "detail": f"digests:{payload.get('date')}",
    }
    _runs.append(record)
    _append_jsonl(RUNS_PATH, record)
    return payload
