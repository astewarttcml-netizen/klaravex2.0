# ADR-0004 — Two-tier audit log: action log 7 years, read log 90 days

**Status:** Accepted
**Date:** 2026-06-27

## Context

Concept §7 contains a contradiction the v0.1 draft does not name: §7 commits to no copies of the Tourism Data Hub's PII; §5.3 requires audit-proof logging of access and changes. When the bot answers a question by drawing on hub data, the resulting answer text contains hub PII, and the audit log thereby becomes a shadow PII copy with indefinite retention, outside the hub's governance.

The contradiction is unresolvable if "audit log" is a single store with a single retention. It is resolvable if we separate the operational telemetry needed for compliance (who did what, against which content IDs) from the conversational text needed for support and abuse investigation (the query and the answer).

Proposal §6.3 commits to a two-tier log. This ADR records the technical decision.

## Decision

Two stores, with different retentions:

| Store | Records | Retention | Storage |
| --- | --- | --- | --- |
| **Action log** | who, what, when, content_id, permission_filter_hash, source IDs cited (by ID only), latency, outcome flags | 7 years | PostgreSQL append-only partitioned table, archived monthly to Blob Storage with object-lock (immutable) |
| **Read log** | query text, answer text, user, timestamp | 90 days, automatic TTL | PostgreSQL with daily TTL job |

The action log satisfies §5.3 audit-proof logging. It does not contain hub PII (no document text, no answer text). It is sufficient for a DPO or regulator to reconstruct *that* a bot answer was generated, *which sources* were used, and *under which permission scope*.

The read log carries the operational data needed for support tickets, abuse investigation, and hallucination sampling. Its 90-day window is the maximum window in which any hub PII can appear in a Knowledge Manager-controlled store.

The retention windows are configurable in the Admin Console; the defaults are the recommendation.

## Consequences

**Positive**
- Concept §7 (no copy) and §5.3 (audit logging) are no longer in tension.
- DPIA argument is simple: hub PII may transit through the read log for ≤90 days; this is the shortest retention compatible with operating the service.
- Action log retention (7 years) aligns with the BSI C5 evidence retention expectation and the works council co-determination on employee data oversight.

**Negative**
- Two stores to maintain. Mitigated by both being PostgreSQL tables (no new infrastructure).
- A support incident older than 90 days cannot be reconstructed from the read log. Acceptable: action-log entries plus the underlying source content (still in the system) allow reconstruction of *what the bot was asked* by indirect means.

**Neutral**
- The TTL job runs nightly and is itself logged in the action log (deletion is an auditable event).
