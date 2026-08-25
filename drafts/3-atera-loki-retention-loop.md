# Atera → Loki Proactive Retention Loop
**Design spec — the AI-native MSP differentiator**

**Status:** Design/spec for review. **NOT an implementation.** Per project rules, the host session is orchestrator-only: actual build happens via a Loki subagent with note_submissions logging and explicit per-action approval for any Hetzner change. No production changes are made by this document.

**Goal:** Close the loop from monitoring alert → client communication automatically, so problems are detected and triaged before the client notices. This is the single biggest churn-killer for subscriptions and the capability competitors (Geek Squad, local techs) structurally cannot match.

---

## Why it matters commercially

Subscription margin lives or dies on **churn**. A client who never perceives value cancels. A client who gets "we spotted and fixed X before you noticed" messages *feels* the subscription working every month. Proactive monitoring converts an invisible service into a visible one — and justifies premium tiers. It also generates cases (and training data) without inbound demand.

---

## Architecture (high level)

```
   ┌────────────┐   event/webhook   ┌──────────────┐   classify    ┌─────────────┐
   │   Atera     │ ───────────────▶ │     Loki      │ ───────────▶ │  Decision    │
   │   RMM       │  disk full,       │  ingest +     │   category +  │  engine      │
   │  (endpoints)│  patch failed,    │  enrich w/     │   severity +  │              │
   └────────────┘  service down,     │  client ctx    │   tier        └──────┬──────┘
                   threshold breach   └──────────────┘                       │
                                                          ┌───────────────────┼───────────────────┐
                                                          ▼                   ▼                   ▼
                                                  GREEN (auto-OK)      YELLOW (draft)       RED (escalate)
                                                  notify + remediate   draft → human OK     page Anthony
                                                          │                   │                   │
                                                          └─────────┬─────────┴───────────────────┘
                                                                    ▼
                                                          Client comms (AI-labeled)
                                                                    ▼
                                                          note_submissions log
```

---

## Event → action mapping (tie to graduation tiers)

The same Green/Yellow/Red tiers from the graduation tracker govern what the loop may do autonomously:

| Event type | Tier | Loop behavior (Phase 1) | Loop behavior (Phase 2, post-graduation) |
|---|---|---|---|
| Disk space warning, cache bloat, routine patch available | Green | Draft notify + propose fix → **you approve** | Auto-notify + auto-remediate, logged |
| Patch failed, service restart needed, config drift | Yellow | Draft diagnosis + fix → **you approve before client sees it** | Auto-draft, human approves outbound (permanent) |
| Security alert, ransomware indicator, backup failure, auth anomaly | Red | **Page Anthony immediately** — no automation | **Still page Anthony** — never automated |

This means the loop launches **fully human-gated** (Phase 1) and only the Green branch ever becomes autonomous — consistent with disclosure and the graduation discipline.

---

## Phased rollout

**Phase A — Detection + manual triage (no client contact automated)**
- Atera alerting configured; events flow to Loki; Loki classifies and queues for you.
- You act and message clients manually. Pure internal triage assist. Zero risk.

**Phase B — Drafted outbound (human-approved)**
- Loki drafts the client notification ("we detected X, here's what we're doing"). You approve before send.
- All outbound AI-labeled. Disclosure stays Phase-1.

**Phase C — Green auto-remediation + auto-notify (post-graduation only)**
- Only Green event categories that have passed the graduation gate (≥30 cases, ≥95% accuracy, 0 harm) auto-remediate and auto-notify.
- The moment any branch goes autonomous → site flips to Phase-2 disclosure.

---

## Guardrails

- **Red is permanently human.** Security, backups, auth, payments — page Anthony, never automate, regardless of track record.
- **Outbound is human-approved until the category graduates.** No auto-messaging clients in Phase A/B.
- **Every loop action writes note_submissions** (the project's mandatory memory policy) — including the event, the classification, and the action taken.
- **No host-session SSH.** Wiring this on Hetzner (env vars, webhook endpoint, container changes) is done by a Loki subagent with per-action approval — not from this orchestrator session.
- **Idempotency + rate limiting.** A flapping endpoint must not generate a storm of client messages. Debounce and dedupe at the Loki ingest layer.

## Dependencies
- Atera webhook/API access + alert thresholds defined per client.
- Loki ingest endpoint (auth'd) + classification mapped to the graduation tiers.
- Client comms channel (email/portal) with AI labeling.
- note_submissions write path confirmed.

## Risks
| Risk | Impact | Mitigation |
|---|---|---|
| Alert storm → message spam | Client annoyance, churn | Debounce/dedupe; severity thresholds; daily digest for low-sev |
| False positive auto-remediation | Breaks a working system | Green-only, post-graduation, reversible actions only |
| Outbound before approval | Disclosure/trust breach | Human-gate until graduated; hard block on auto-send in Phase A/B |
| Hetzner change breaks shared Loki | Affects itexperts-berlin too (shared CX22) | Separate compose/env per project; per-action approval; snapshot before change |

## Retention value (the point)
Each proactive "caught before you noticed" touch is a visible proof-of-value that resets the churn clock. Target: ≥1 proactive value-touch per subscriber per month. That cadence is what makes the subscription feel indispensable.
