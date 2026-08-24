# Phase D — klaravex-os console rebrand (Loki → Klara)

**Date:** 2026-08-24
**Status:** COMPLETE

## What changed

Rebranded the agent-fleet layer of klaravex-os from Loki to Klara AI.

**Code (16 files):**
- `lib/loki/` → `lib/klara/` (`catalog.ts`, `client.ts`, `pipeline-triggers.ts`)
- `lib/agents/loki-runtime.ts` → `klara-runtime.ts`, `loki-sync.ts` → `klara-sync.ts`
- `components/SyncLokiAgentsButton.tsx` → `SyncKlaraAgentsButton.tsx`
- `app/api/agents/sync-loki/` → `app/api/agents/sync-klara/`
- `scripts/sync-loki-agents.ts` → `sync-klara-agents.ts`; `package.json` script `agents:sync-klara`
- Tests renamed → `tests/klara-*.test.ts`
- Identifiers: `loki*`→`klara*`, `Loki*`→`Klara*`; id prefix `loki-`→`klara-`;
  dept `dept-loki`→`dept-klara`; labels "Loki Fleet"→"Klara Fleet", "Sync from Loki"→"Sync from Klara"
- **Bug fix:** `klaraIdToName` slice 5→6 (the `klara-` prefix is one char longer than `loki-`)

**Preserved (not renamed):** `KLARAVEX_API_URL` / `KLARAVEX_API_KEY` env names.

**Database (klaravex-os Postgres):**
- `agents`: 80 rows `loki-*` → `klara-*`, `instance` `loki`→`klara`
- `agent_runs`: 1 stale `loki-*` row → `klara-*`
- `departments`: `dept-loki` → `dept-klara` ("Klara Fleet"), agents repointed (FK-safe order)

## Verified

- `npx tsc --noEmit` clean
- `npx vitest run tests/klara-*.test.ts` → **11/11 pass**
- `npx next build` → success
- Dev server restarted; `/agents` renders **Klara Fleet**, **Sync from Klara**, `klara-*` ids; zero `loki` refs

## Note — backend target

klaravex-os reads `KLARAVEX_API_URL` (currently `http://localhost:8002`, the legacy
klaravex monolith). The Klara EU node is on `127.0.0.1:8004` (shadow). Repointing the
console at Klara is part of the **Phase C cutover**, not this rebrand.

## Rollback

Code backup: `/tmp/klaravex-os-rebrand-bak/`. DB: re-run the reverse UPDATEs
(`klara-`→`loki-`, `dept-klara`→`dept-loki`).
