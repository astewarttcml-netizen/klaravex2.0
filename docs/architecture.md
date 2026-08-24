# Growth OS architecture (Klaravex2.0)

## Layers A / B / C / D

```
                    ┌─────────────────────────────────────┐
                    │  D  klaravex-os (:4100)             │
                    │  Operator cockpit (sibling repo)    │
                    └─────────────────┬───────────────────┘
                                      │ HTTPS + X-Growth-Secret
                                      ▼
┌──────────────┐    optional    ┌─────────────────────────┐
│ B  n8n       │───────────────▶│  C  Growth API (:4200)  │
│ glue only    │                │  ledger / scorecard /   │
└──────────────┘                │  gate verdict / trigger │
                                └───────────┬─────────────┘
                                            │
                     systemd timers / cron  │  read charters
                                            ▼
                                ┌─────────────────────────┐
                                │  A  revenue-agents/     │
                                │  charters + local outbox│
                                └─────────────────────────┘
```

| Layer | Owns | Must not own |
|-------|------|--------------|
| **A** | Charters, outbox files, gate rubric SoT | Schedulers, HTTP API |
| **B** | Ops glue calling C | Approval rubric, cadence SoT |
| **C** | Run ledger, triggers, scorecard, kill switch | Charter text, publish credentials |
| **D** | Operator UX | Required path for scheduled runs |

## Topology notes

- **Failure isolation:** If Celery beat or Loki die, **C + timers still execute**. If D or n8n die, cadence still runs.
- **Secrets:** Service-to-service auth is a shared secret header, not OAuth (stub era).
- **Outbox SoT after cutover:** `/home/anthony/Klaravex2.0/revenue-agents/outbox/<stream>/`.

## Secret: `GROWTH_INTERNAL_SECRET`

| Item | Rule |
|------|------|
| Purpose | Authenticate callers of Growth API (D, n8n, timers, curl) |
| Header | `X-Growth-Secret: <value>` |
| Storage | `growth/.env` (gitignored); never commit; prefer 1Password inject for production |
| Rotation | Update `.env` + all callers (D env, n8n credential, timer `EnvironmentFile`) atomically |
| Public | `/healthz` may remain unauthenticated for probes |

Related env (see `growth/.env.example`):

- `GROWTH_ENABLED` — kill switch (`true`/`false`)
- `PORT` — default `4200`
- `REVENUE_AGENTS_ROOT` — absolute path to Layer A (default: repo `revenue-agents/`)

## Stream allowlist (C ↔ A)

Must match charter basenames: `leads`, `socials`, `seo-blog`, `kb`, `backlinks`, `ads`, `freelance`, `gatekeeper`.
