# Klaravex Growth OS PRD

**Status:** Locked decisions (Anthony 2026-08-22) · Implementation home opened  
**Owner:** Klaravex Product / Revenue Ops  
**Audience:** Engineering, CRO/Gatekeeper operators, exec escalations  
**Related:** `revenue-agents/README.md` (legacy Layer A; see Implementation home)

> **Implementation home (2026-08-22)**
>
> Build and cut over Growth OS in **`/home/anthony/Klaravex2.0`** (strangler-fig: Layers A+C, timers, runbooks). Layer D remains **`/home/anthony/klaravex-os`**. This live `klaravex` tree stays production until per-stream cutover; do not treat it as the Growth OS implementation target.

> **Naming collision — do not merge**
>
> | Path | Product | Role |
> |------|---------|------|
> | `/home/anthony/klaravex-os` | **KLARAVEX-OS** | Internal operator console (Next.js `:4100`). Token-gated. Funnel, social, finances, agents, pipelines → Klaravex API / n8n. **Not** a client portal. **This** is Growth OS Layer D. |
> | `/home/anthony/klaravex/klaravex-os` | **Founders OS** | Client portal (different product). **Do not** merge, rename into, or confuse with KLARAVEX-OS. |

---

## 1. Objective & business value

Deliver an **all-in-one Growth OS** for the non-engineering revenue lifecycle: lead generation, socials, SEO/blog, knowledge base, backlinks, ads, freelance bids, gated publish prep, and accountability scorecards.

**Business value**

- Revenue streams keep running when Celery beat or Loki crash — Growth OS must not share their failure domain.
- Anthony is **escalation-only** for routine growth work; Gatekeeper/CRO approve on his behalf.
- Single control plane for run ledger, triggers, scorecard, and kill switch — operators see one system of record for “did growth run?”
- Operators run growth from **KLARAVEX-OS** (Layer D) without opening Loki admin.

---

## 2. Scope

### In scope

| Stream / capability | Notes |
|---------------------|--------|
| Leads | Prospect shortlists + outreach drafts |
| Socials | Business + consumer post drafts |
| SEO / blog | Alternating-surface article drafts |
| KB | Mon/Wed/Fri article drafts |
| Backlinks | Playbook execution prep |
| Ads | Weekly performance review + proposals |
| Freelance | Daily proposal/bid template improvement |
| Gatekeeper / CRO approvals | Rubric adjudication; routine growth approval |
| Scorecard | Growth accountability (separate from Loki) |
| Operator cockpit | KLARAVEX-OS (`/home/anthony/klaravex-os`) — growth UI wired to C |
| Optional adapters | Clay, Taplio, Smartlead (Phase 5) |

### Out of scope

- Loki handlers and completion-council paths
- Voice / support runtime
- Product deploys and app infra changes
- **P5 Anthony-only gates:** credentials, money movement, legal commitments
- Founders OS client portal (`klaravex/klaravex-os`) — unrelated product surface

---

## 3. Layered architecture (A + B + C + D)

**A, B, C, and D are layers, not alternatives.** All four coexist; ownership is strict.

| Layer | Location / stack | Owns |
|-------|------------------|------|
| **A** | `revenue-agents/` | Charters, outbox, **gatekeeper SoT for agent behavior** and approval rubric |
| **C** | Growth API (FastAPI) + systemd/cron | Control plane: run ledger, stream triggers, scorecard, kill switch |
| **B** | n8n | Ops glue only — **calls Growth API**; must **not** own approval rubric or business rules |
| **D** | KLARAVEX-OS (`/home/anthony/klaravex-os`, Next.js `:4100`) | Operator cockpit: scorecard, stream status, manual triggers, funnel/social/finance views, exec/CRO escalation inbox, pipeline buttons |

**Hard rules**

- If n8n is down **and** Celery beat / Loki are down, **C + cron/timers still run every stream**. n8n is never required for cadence execution.
- If **KLARAVEX-OS (D)** is down, **C + cron still run**. D is never required for scheduled cadence.
- D **must** call **Growth API (C)** for growth stream run / scorecard / gate. During cutover it may still call Klaravex API / n8n for legacy pipelines.
- D must **not** own charter rubrics (A) and must **not** be required for scheduled runs (C).

---

## 4. ASCII topology

```
You (Anthony = escalation / P5 only)
        │
        ▼
CRO / Gatekeeper  ──(routine growth verdicts)──┐
        │                                        │
        ▼                                        ▼
   ┌─────────────────────────────────────────────────┐
   │  C  Growth API (FastAPI)                        │
   │  run ledger · triggers · scorecard · kill switch│
   └──────┬──────────────┬──────────────┬────────────┘
          │              │              │
    ┌─────┘              │              └──────────┐
    ▼                    ▼                         ▼
A  revenue-agents/   B  n8n (optional)    D  klaravex-os (:4100)
charters + outbox    glue → POST C only   operator UI → C (growth)
    │                                         │
    │                                    (legacy cutover: Klaravex API / n8n)
    ▼
outbox (drafts + GATE VERDICT)
    │
    ▼
publish bridge  →  adapters (WP, social, Clay/Taplio/Smartlead…)
```

Cadence independence: **C + cron** fire regardless of B (n8n), D (OS UI), Celery beat, or Loki.

---

## 5. Directory layout (proposed)

```
/home/anthony/klaravex/
  revenue-agents/          # A (existing)
  growth/                  # C service (new)
    api/
    schedulers/            # systemd unit templates or cron wrappers
    adapters/
  klaravex-os/             # Founders OS client portal — NOT Layer D
  docs/prd-growth-os.md    # this PRD

/home/anthony/klaravex-os/ # D — KLARAVEX-OS operator console (sibling repo)
                           # Keep separate deploy; contract via C API
```

**Recommendation (now):** keep D as a **sibling repo** (`/home/anthony/klaravex-os`) with its own deploy. Growth contract = C API only.  
**Optional later:** vendor under `klaravex/apps/klaravex-os` — only if monorepo deploy friction outweighs sibling isolation; do not confuse with `klaravex/klaravex-os` (Founders OS).

---

## 6. Growth API v1 surface

Internal control plane. Auth: **`GROWTH_INTERNAL_SECRET`** (dedicated secret; do **not** rename or reuse Loki secrets).

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/healthz` | Liveness |
| `POST` | `/v1/streams/{name}/run` | Trigger a named stream run |
| `GET` | `/v1/runs` | Run ledger / history |
| `GET` | `/v1/scorecard` | Growth accountability scorecard |
| `POST` | `/v1/gate/{draft_id}/verdict` | Record / apply gate verdict (CRO path into C; rubric remains in A) |

Stream `name` values align with Layer A: `socials`, `leads`, `ads`, `seo-blog`, `kb`, `backlinks`, `freelance`, `gatekeeper`.

### 6.1 UI routes to add/wire in KLARAVEX-OS (Layer D)

Wire in `/home/anthony/klaravex-os` (not Founders OS). Auth remains token-gated OS session + `GROWTH_INTERNAL_SECRET` on C calls.

| OS route | C API | Purpose |
|----------|-------|---------|
| `/growth` or `/growth/scorecard` | `GET /v1/scorecard` | Growth accountability scorecard |
| `/growth/runs` | `GET /v1/runs` | Run ledger |
| `/growth/streams` | `POST /v1/streams/{name}/run` | Stream status + Run buttons |
| `/growth/approvals` (or extend agents) | C gate verdicts (`POST /v1/gate/...`) | CRO / gatekeeper queue |

**Nav:** add Growth entry under Operate in `lib/nav.ts` (`NAV_OPERATE`), e.g. `{ href: '/growth', label: 'Growth', ... }` alongside Funnel / Social / Finances.

D still owns existing funnel/social/finance/agents/pipeline views; growth streams call **C**. Legacy Klaravex API / n8n calls allowed only during cutover.

---

## 7. Timers

**Mechanism:** systemd timers **or** cron wrappers that `POST` C endpoints.  
**Explicit:** **no Celery beat** for Growth OS streams.

| Stream | Cadence (aligned with `revenue-agents/README.md`) |
|--------|-----------------------------------------------------|
| `socials` | Daily |
| `leads` | Daily |
| `ads` | Weekly |
| `seo-blog` | Daily |
| `kb` | Mon / Wed / Fri |
| `backlinks` | Weekly |
| `freelance` | Daily |
| `gatekeeper` | Daily, **after** upstream stream runs complete |

Schedulers live under `growth/schedulers/` (unit templates or thin cron scripts calling C).

---

## 8. Approval model

- **Gatekeeper / CRO** approve routine growth drafts on Anthony’s behalf (rubric SoT = Layer A charters; C records verdicts / ledger).
- **Anthony** = escalation + **P5 only** (credentials, money, legal).
- Growth approval is **separate** from the Loki completion council.
- Operator inbox for escalations / gate queue lives in **D** (`/growth/approvals`); verdicts write to **C**; rubrics stay in **A**.
- Optional future: **Approval Adjudicator** for product / Loki paths only — not required for Growth OS v1.

---

## 9. Beat cutover checklist

- [ ] Inventory Celery beat entries that touch revenue (social, SEO, freelance, prospecting, related publish prep).
- [ ] Prove each stream green on C + cron/timers (ledger + outbox evidence).
- [ ] Disable corresponding beat entries **one stream at a time** after that stream’s C path is proven.
- [ ] Keep Loki / Celery beat for **non-revenue** workloads if still required.
- [ ] **Verification:** stop revenue beat entries → confirm next Growth cadence still fires via C + timers.
- [ ] **Verification:** stop KLARAVEX-OS (D) and/or n8n (B) → confirm next Growth cadence still fires via C + timers.

---

## 10. Phased delivery

| Phase | Deliverable |
|-------|-------------|
| **1** | Harden Layer A + document ownership (charters, outbox, gatekeeper SoT) |
| **2** | Scaffold Layer C (Growth API) + cron/systemd timers |
| **3** | Cut over streams off Celery beat **one-by-one** |
| **4a** | **KLARAVEX-OS cockpit (D):** wire `/growth*` routes + Operate nav → C (scorecard, runs, stream Run, approvals) |
| **4b** | n8n thin client (glue → C only; no business rules in n8n) |
| **5** | Optional Clay / Taplio / Smartlead adapters |

Prefer **4a before or alongside 4b** — operator cockpit first; n8n remains optional glue.

---

## 11. Success criteria

- **Beat-kill test passes:** with revenue Celery beat stopped (and n8n optionally stopped), next scheduled Growth cadences still fire via C + timers.
- **OS-kill test passes:** killing KLARAVEX-OS UI does **not** stop cron/timer runs via C.
- Operator can **trigger and view** growth (scorecard, runs, stream Run, gate queue) from KLARAVEX-OS **without** opening Loki admin.
- Anthony **routine growth approval ≈ 0**; escalations / P5 only.
- Growth **scorecard** is distinct from Loki / product accountability scorecards.
- Gatekeeper rubric and agent behavior SoT remain in `revenue-agents/` (A), not in n8n or KLARAVEX-OS.
- Dual-run window ends with no duplicate publishes after cutover.

---

## 12. Risks & rollback

| Risk | Mitigation / rollback |
|------|------------------------|
| n8n treated as SoT (approval rubric / rules) | Hard ownership: rules stay in A; n8n only calls C. If misused, disable n8n workflows; C+cron continue. |
| KLARAVEX-OS confused with Founders OS | Explicit naming box; separate paths; D = sibling `/home/anthony/klaravex-os` only. |
| D treated as required for cadence | Hard rule: D optional for schedule; C+cron own cadence. Kill OS UI in drills. |
| Dual-running beat + cron duplicates drafts/publishes | Cut over one stream at a time; ledger dedupe by stream+date; disable beat only after green. |
| Need emergency stop | Kill switches: `GROWTH_ENABLED` and `EXEC_APPROVAL` (or equivalent) flags — stop triggers / publish without touching Loki. |
| C API or timer failure | Rollback: re-enable prior beat entry for that stream only; file incident; do not move rules into n8n or D. |

---

## 13. Decisions locked (Anthony 2026-08-22)

1. Architecture is **A + B + C + D** (layers, not pick-one). Product includes A+B+C **and** KLARAVEX-OS.
2. Revenue lifecycle is **fully separated from Loki**.
3. Growth **must not stop** when Celery beat / Loki crash; **nor** when n8n or KLARAVEX-OS UI are down.
4. Exec team (Gatekeeper / CRO) **approve on Anthony’s behalf** for routine growth.
5. Intent: **all-in-one growth platform** for the non-engineering revenue lifecycle.
6. **KLARAVEX-OS** (`/home/anthony/klaravex-os`) = Layer D operator cockpit; **Founders OS** (`klaravex/klaravex-os`) is a different product — do not merge.
7. D contracts via **C API**; keep sibling deploy for now.
