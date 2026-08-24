# Growth API (Layer C)

FastAPI control plane for Klaravex Growth OS: health, stream triggers, run ledger, scorecard, gate verdicts.

**Independent of Celery beat and Loki.** Schedulers live in `schedulers/` (systemd timers).

## Run locally

```bash
cd /home/anthony/Klaravex2.0
python3 -m venv .venv && source .venv/bin/activate
pip install -r growth/requirements.txt
cp growth/.env.example growth/.env
# edit GROWTH_INTERNAL_SECRET
set -a && source growth/.env && set +a
uvicorn growth.api.main:app --host 127.0.0.1 --port "${PORT:-4200}"
```

```bash
curl -s http://127.0.0.1:4200/healthz
curl -s -X POST -H "X-Growth-Secret: $GROWTH_INTERNAL_SECRET" \
  http://127.0.0.1:4200/v1/streams/leads/run
```

Stub behavior: ~~run endpoint returns `202` and logs `TODO execute charter`~~ charter executor queues a Claude session (see `growth/executor/`). Set `GROWTH_EXECUTOR_DRY_RUN=true` to test without spawning Claude.

## Charter executor

When `POST /v1/streams/{name}/run` is called:

1. Growth API records `accepted` in the run ledger.
2. A background thread launches `claude -p` with the stream charter prompt.
3. Status moves to `running` → `completed` or `failed`.
4. Session output lands in `revenue-agents/outbox/<stream>/` per the charter.
5. Executor logs: `growth/data/executor/<run_id>.log`

Poll run status: `GET /v1/runs/{run_id}` (auth required).

Env (see `.env.example`): `GROWTH_EXECUTOR_ENABLED`, `GROWTH_EXECUTOR_DRY_RUN`, `GROWTH_CLAUDE_BIN`, `GROWTH_KLARAVEX_ROOT`, `GROWTH_EXECUTOR_TIMEOUT_S`, `GROWTH_EXECUTOR_BYPASS_PERMISSIONS`.

## POC mode

Set `GROWTH_POC_MODE=true` to run against fictional fixtures in `data/poc/` instead of Apollo and live scrapers:

- **leads:** copies `data/poc/leads/` into `data/research/<run_id>/` per run
- **other streams:** injects `data/poc/streams/<stream>/context.md` into the charter prompt
- **adapters:** return `poc_sandbox` (no live Smartlead/WordPress/Taplio/Clay calls)

Verify: `curl -s http://127.0.0.1:4210/healthz` should show `"poc_mode": true`.

## Layout

- `api/main.py` — FastAPI app
- `api/streams.py` — stream allowlist
- `schedulers/` — systemd unit templates + install script
- `adapters/` — external tool stubs (Phase 5)
- `data/runs.jsonl` — optional persistence (created at runtime if enabled)
