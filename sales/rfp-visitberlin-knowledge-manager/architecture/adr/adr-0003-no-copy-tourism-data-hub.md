# ADR-0003 — Tourism Data Hub: read-only adapter with session-scoped cache only

**Status:** Accepted
**Date:** 2026-06-27

## Context

Concept §3.1 and §7 state that the Tourism Data Hub holds POI data, BWC partner data, and personal contact data of stakeholders / cooperation partners from the CRM. The hub is to be queried by the Knowledge Manager, but the Knowledge Manager is **not** to store copies. The hub remains the system of record.

The naïve implementation — copy hub data into the Knowledge Manager periodically — would create a shadow dataset that drifts from the hub, falls outside the hub's data-governance regime, and undermines the "single source of truth" principle in §1.3.

Concept §7 also requires audit-proof logging of access and changes. If the hub is queried during bot answers, the resulting answer text contains hub PII, which would then live in the audit log indefinitely — a shadow copy via a different route. This contradiction is addressed in ADR-0004.

## Decision

The Tourism Data Hub is integrated through a thin read-only adapter that:

1. Issues Cypher (or Gremlin — selection at integration time depending on the hub's actual product) queries on demand at retrieval time.
2. Uses a service account with read-only permissions, scoped by the hub's own permission model.
3. Holds returned records **only** in the API process memory for the duration of the user's request.
4. **Never** writes hub records to PostgreSQL, Blob Storage, or Azure AI Search.

The adapter is invoked during the retrieval engine's parallel hop (`architecture.md` §3.3) when intent classification identifies the query as needing structured POI / partner / contact data.

The action log records that a hop occurred (which queries, on whose behalf, returning how many records), without recording the returned data itself. The read-log retention (90 days) is the maximum window in which hub data appears in any persisted store under our control (it is in the answer text written to the read log).

## Consequences

**Positive**
- The Knowledge Manager genuinely is not a copy of the hub. The hub remains authoritative.
- No drift, no staleness, no parallel governance.
- The 90-day read-log cap is the only data-retention window for hub PII in our control, which is justifiable under GDPR data-minimisation.

**Negative**
- Hub availability becomes a runtime dependency of the bot. Mitigated by: bot continues to answer from Knowledge Manager content with a user-visible "hub data unavailable" notice during outages.
- Per-query latency includes a network round-trip to the hub. Mitigated by parallel retrieval (the hop runs concurrently with BM25 and vector search).

**Neutral**
- The session-scoped cache means a user asking the same question twice in one session does not double-charge the hub; cross-session caching is deliberately disabled.
