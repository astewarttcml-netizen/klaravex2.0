# Revenue Agents (Layer A) — Klaravex2.0

## System of record

**This tree is SoT for Growth OS agent behavior after cutover.**

| Concern | Location |
|---------|----------|
| Charters | `Klaravex2.0/revenue-agents/charters/` |
| Outbox | `Klaravex2.0/revenue-agents/outbox/<stream>/` |
| Scheduler | **Growth API (Layer C) + systemd timers / cron** — not Celery beat, not Loki |
| Operator UI | `/home/anthony/klaravex-os` (Layer D) calling Growth API |

Legacy copies under `/home/anthony/klaravex/revenue-agents/` remain until each stream cuts over. Do not treat klaravex outbox as SoT for streams already migrated.

Charter set: `socials`, `leads`, `ads`, `seo-blog`, `kb`, `backlinks`,
`freelance`, `forums`, `gatekeeper`.

## Layout

```
revenue-agents/
├── README.md
├── charters/          # SoT — edit here
└── outbox/
    ├── socials/ leads/ ads/ seo-blog/ kb/ backlinks/ freelance/ forums/
```
## Execution model

1. Timer or operator → `POST /v1/streams/{name}/run` on Growth API (auth: `X-Growth-Secret`).
2. Growth API records the run (ledger). Executor (later) launches a Claude session that reads this README + the stream charter.
3. Outputs land in **this** outbox as `YYYY-MM-DD-<slug>.md`.
4. Gatekeeper charter adjudicates ungated drafts; Growth API can record verdicts via `/v1/gate/{draft_id}/verdict`.

**No Celery beat.** Cadence must survive Loki/Celery failure (see root `MIGRATION.md` beat-kill test).

## Outbox / gate flow

Unchanged policy from klaravex revenue-agents: stream agents draft only; gatekeeper appends `## GATE VERDICT`; Anthony is escalation-only. Publishing bridge remains a separate concern — wire paths to this outbox at cutover.

## Logging

Prefer Growth API run ledger + charter-local notes. Persist durable findings via note_submissions / vault per Klaravex memory policy — never log secrets.
