# Klara AI backend

Ported from the Loki backend on 2026-08-24 (Loki → Klara AI rebrand).

## Layout

| Package | Source (legacy) | Contents |
|---------|-----------------|----------|
| `klara/handlers/` | `klaravex/infra/loki_handlers/` | Webhook / intake / voice / billing handlers (~244 files) |
| `klara/agents/` | `itexperts-berlin/loki-agents/app/` | EU support-agent service (`main.py`, `celery_tasks.py`, `config.py`) |

## What the port changed

- **Imports:** `loki_handlers` / `infra.loki_handlers` → `klara.handlers`
- **Brand strings:** `Loki` → `Klara AI` (voice scripts, console labels, copy)
- **Preserved (aliased, NOT renamed):** infra identifiers so the running system
  keeps working — `LOKI_INTERNAL_SECRET` / `LOKI_SECRET` env vars, DB
  schema/table names (e.g. `loki_invoices`), docker container/volume/image names.

Regenerate any time with:

```bash
python3 /home/anthony/Klaravex2.0/scripts/port-loki-to-klara.py
```

The script re-copies fresh from the legacy sources (idempotent). Once Klara is
the live system, legacy sources become read-only forensics.

## Deploy notes

- `klara/agents` keeps its original `app/`-rooted absolute imports
  (`from app.services...`). Deploy it the same way `loki-agents` was: with the
  `agents/` dir as the import root (its Docker context already does this).
  A future cleanup can rewrite these to `klara.agents.*` — tracked separately.
- `klara/handlers` is self-contained under the `klara.handlers` package.

## Status

- [x] Phase B scaffold + port (compiles clean)
- [ ] Phase C: build + deploy as `klara-agents-eu`, cut over from `loki_eu_*`
- [ ] Phase D: klaravex-os Layer D → Klara endpoints + nav labels
