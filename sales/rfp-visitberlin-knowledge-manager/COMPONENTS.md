# COMPONENTS

This bundle is a proposal package, not a runtime codebase. Each top-level directory is a deliverable component with a defined audience, public surface (the file(s) handed to the client or referenced in other artifacts), and dependencies on sibling components. This document describes those components and how they fit together.

---

## Top-level layout

| Component         | Audience                          | Public surface                  | Depends on                          |
| ----------------- | --------------------------------- | ------------------------------- | ----------------------------------- |
| `_source/`        | Internal (reference only)         | `visitberlin-concept-v0.1.md`   | None — frozen input                 |
| `proposal/`       | visitBerlin procurement + DPO     | `proposal.md`                   | `_source/`, `architecture/`, `compliance/` |
| `architecture/`   | visitBerlin IT + Klaravex eng     | `architecture.md`, `data-flow.md`, `adr/*.md` | `_source/`              |
| `compliance/`     | visitBerlin DPO, legal, security  | `dpia.md`, `gdpr-dossier.md`, `nis2.md`, `bsi-c5.md`, `data-residency.md` | `architecture/`, `_source/`         |
| `mockup/`         | visitBerlin product + stakeholders| `index.html`                    | `architecture/` (mental model)      |
| `pitch-deck/`     | Project team walkthrough          | `deck.html`                     | All of the above (summarizes them)  |
| `.loki/`          | Internal automation               | None (excluded from delivery)   | None                                |
| `.agents/`, `.aider-desk/` | Internal tooling skills  | None (excluded from delivery)   | None                                |
| `README.md`, `USAGE.md`, `BUILD-STATUS.md` | Bundle navigation | Root markdown files            | Index of all of the above           |

---

## `_source/` — Frozen client input

**Purpose.** Verbatim copy of the client-provided concept draft. Treated as read-only ground truth; every other artifact must trace back to this document.

**Key files.**

- `visitberlin-concept-v0.1.md` — the original visitBerlin Knowledge Manager v0.1 concept draft.

**Public interface.** None. Referenced by file path from `proposal/proposal.md`, the ADR set, and the compliance dossiers when a specific concept clause is being addressed.

**Dependencies.** None. This directory must not change once the proposal is in flight; downstream artifacts assume it is stable.

---

## `proposal/` — Formal written response

**Purpose.** The single document visitBerlin procurement reads first. Maps each concept-draft requirement to a Klaravex commitment, scope boundary, timeline, and pricing posture.

**Key files.**

- `proposal.md` — full English proposal, structured for German-language adaptation.

**Public interface.** `proposal/proposal.md` is the canonical narrative. It cites `_source/visitberlin-concept-v0.1.md` for requirement provenance, links to `architecture/architecture.md` for "how", and links to `compliance/` for "lawfully".

**Dependencies.**

- `_source/` for requirement traceability.
- `architecture/` for any technical claim — never restate architecture details inline; link.
- `compliance/` for GDPR, NIS2, BSI C5, residency, and DPIA references.

---

## `architecture/` — Technical depth

**Purpose.** Demonstrates Klaravex has already designed the system end-to-end. Splits into a narrative architecture overview, a data-flow document with sequence-level detail, and an ADR set capturing the nine load-bearing decisions.

**Key files.**

- `architecture.md` — three-layer system overview (ingestion, retrieval/reasoning, experience/governance), component map, directory map, technology choices.
- `data-flow.md` — upload/ingestion, bot retrieval, lifecycle/review sequence diagrams.
- `adr/adr-0001-azure-germany-region.md` — region selection and sovereignty rationale.
- `adr/adr-0002-permission-filter-at-retrieval.md` — enforce ACLs at Azure AI Search query time, not after generation.
- `adr/adr-0003-no-copy-tourism-data-hub.md` — Tourism Data Hub as read-only adapter, session-scoped cache only.
- `adr/adr-0004-audit-log-two-tier.md` — action log 7 years, read log 90 days; resolves the GDPR retention contradiction.
- `adr/adr-0005-azure-openai-not-openai.md` — Azure OpenAI in Sweden-Central/France-Central; no direct OpenAI.
- `adr/adr-0006-entra-id-for-roles.md` — role assignment via Entra ID security groups; no parallel role table.
- `adr/adr-0007-mailbox-opt-in-only.md` — mailbox ingestion disabled by default, per-mailbox opt-in with DPO gate.
- `adr/adr-0008-hybrid-retrieval.md` — parallel BM25/vector/graph-hop fused via RRF and cross-encoder rerank.
- `adr/adr-0009-bicep-over-terraform.md` — Bicep for Azure-only single-cloud IaC.

**Public interface.** `architecture.md` is the entry point; ADRs are linked from it and from the proposal. `data-flow.md` is the deep dive for technical reviewers.

**Dependencies.**

- `_source/` for requirement grounding.
- ADRs depend on each other where decisions interlock (e.g., ADR-0002 assumes the Entra ID model of ADR-0006).

---

## `compliance/` — Risk, lawfulness, governance

**Purpose.** Pre-assembled answers to every DPO, legal, and security question the procurement process will raise. Reduces the proposal's back-and-forth window.

**Key files.**

- `dpia.md` — Data Protection Impact Assessment outline covering nine processing activities.
- `gdpr-dossier.md` — sub-processor map, lawful-basis register, data-subject rights mechanics.
- `nis2.md` — NIS2 posture; Klaravex in-scope as supplier, visitBerlin status flagged as planning-for-in-scope.
- `bsi-c5.md` — BSI C5:2020 control mapping across 17 domains with ISO 27001 cross-walk and Type 2 attestation roadmap.
- `data-residency.md` — at-rest in Germany; prompt/completion to Sweden-Central/France-Central under EUDB; migration path for Germany OpenAI.

**Public interface.** Each file is independently readable and addressable. The proposal cites them by filename for any compliance claim.

**Dependencies.**

- `architecture/` — every control assertion ties to a specific architectural decision (e.g., the residency document depends on ADR-0001 and ADR-0005).
- `_source/` — the DPIA processing-activity list is derived from the concept's described data flows.

---

## `mockup/` — Interactive UX preview

**Purpose.** Single-file, click-through SPA showing the seven primary Knowledge Manager screens with a persona switcher (admin, editor, reviewer, bot consumer). Lets non-technical stakeholders feel the product before any code ships.

**Key files.**

- `index.html` — self-contained HTML/CSS/JS; no build step, no external dependencies, opens directly in any browser.

**Public interface.** `mockup/index.html`. Designed to be sent as a file attachment or hosted statically.

**Dependencies.**

- `architecture/` — screens reflect the component model (ingestion queue, retrieval surface, audit views, review workflows). Mental dependency only; no file links.

---

## `pitch-deck/` — Walkthrough deck

**Purpose.** 16-slide summary deck for a 10-15 minute live walkthrough with the visitBerlin project team. Keyboard navigation and print-to-PDF supported so the same artifact serves both presentation and leave-behind.

**Key files.**

- `deck.html` — single-file slide deck.

**Public interface.** `pitch-deck/deck.html`. Print-to-PDF produces a distributable leave-behind.

**Dependencies.**

- `proposal/`, `architecture/`, `compliance/`, `mockup/` — the deck summarizes all four. When any of them change materially, the corresponding slide(s) need to be reviewed.

---

## Root navigation files

**Purpose.** Help a first-time reader land in the right component without opening every directory.

**Key files.**

- `README.md` — bundle map, positioning headline, deliverable index.
- `USAGE.md` — how to read the bundle in order; how to present it.
- `BUILD-STATUS.md` — current state of each deliverable component (which are final, which are in progress).

**Public interface.** All three are root-level and link into every component above.

**Dependencies.** Indexes the other components; updated whenever a component is added, renamed, or finalized.

---

## `.loki/` — Internal automation state

**Purpose.** Loki orchestration runtime state: PRD, task queue, council convergence, quality gates, signals, learning, metrics, skills index. Drives the autonomous build loop that produced the deliverables above.

**Key subdirectories.**

- `assumptions/` — assumption ledger entries (`a-*.json`) plus `ledger.md`.
- `council/` — convergence state for multi-provider deliberation.
- `events/`, `events.jsonl` — event stream and pending event spool.
- `learning/signals/` — captured learning signals per iteration.
- `logs/` — agent, audit, autonomy logs.
- `metrics/` — efficiency and result-cost metrics per iteration; trust events.
- `queue/` — pending, in-progress, completed, failed, dead-letter task queues.
- `quality/` — static analysis, security findings, test results, gate-failure counters.
- `skills/` — Loki skill index and per-skill documentation.
- `state/` — orchestrator state, claude-session, agent branch, checkpoints.
- `signals/`, `notifications/` — inter-process signaling.
- `app-runner/`, `dashboard/`, `pids/` — runtime processes.

**Public interface.** None outside the build environment. Excluded from any artifact delivered to visitBerlin.

**Dependencies.** Self-contained; reads `_source/` as input and writes deliverables into `proposal/`, `architecture/`, `compliance/`, `mockup/`, `pitch-deck/`.

---

## `.agents/skills/` and `.aider-desk/skills/` — Tooling skills

**Purpose.** Local skill definitions for the caveman/cavecrew tooling (review, compress, commit, stats, help). Mirrored across the two harness directories so both Claude-host and aider-desk see the same skill set.

**Key files.** Per skill, a `README.md` and `SKILL.md` pair: `cavecrew`, `caveman`, `caveman-commit`, `caveman-compress` (plus `SECURITY.md`), `caveman-help`, `caveman-review`, `caveman-stats`.

**Public interface.** None for the client. Surfaced only inside the local agent runtime.

**Dependencies.** None on the deliverable components; each skill is self-contained.

---

## `skills-lock.json` — Skill pin

**Purpose.** Pins the resolved skill set for this project so the next session reconstructs the same tooling surface.

**Public interface.** Read by the harness on session start.

**Dependencies.** References `.agents/skills/` and `.aider-desk/skills/`.

---

## Dependency graph (deliverable components only)

```
_source/  ──────────────► architecture/  ──────────────► compliance/
   │                          │                              │
   │                          ▼                              ▼
   └──────────────────────► proposal/  ◄──────────────────────┘
                              │
                              ▼
                          pitch-deck/
                              ▲
                          mockup/  (mental dependency on architecture/)
```

Read order for a new reviewer: `README.md` → `proposal/proposal.md` → `architecture/architecture.md` → `compliance/*` → `mockup/index.html` → `pitch-deck/deck.html`.
