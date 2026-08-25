# ADR-0002 — Permission filter applied at retrieval, not post-hoc

**Status:** Accepted
**Date:** 2026-06-27

## Context

Production RAG systems commonly leak confidential content through two failure modes:

1. **Post-hoc redaction.** The retrieval layer returns all matching documents, the LLM sees them all, and a downstream filter strips the answer. The LLM has already conditioned on the forbidden content; paraphrase, partial echo, and inference leakage are routine.
2. **Citation-time-only enforcement.** Same shape: the LLM saw forbidden content; only the final citation list is filtered.

The concept §3.5 says: *"the bot respects the permissions of the requesting person and returns only content they are authorized to access."* The DPO's interpretation of this sentence is the stricter reading: the user is permitted to access only what the system was permitted to consider on their behalf.

## Decision

The permission filter is applied as a `filter` clause on the Azure AI Search query, evaluated server-side, before any candidate set is returned to the API process. Forbidden content is never returned from the search index and is never embedded into the LLM context.

The filter is constructed per request from the user's Entra ID group membership (role axis) and ABAC attributes (confidentiality axis × responsible-unit). It is hashed and recorded in the action log so an audit can reconstruct what scope each answer was generated against.

A second, defence-in-depth post-generation check verifies that every cited source ID in the LLM's answer is permitted for the user. Failure of this check is itself an audit event indicating a permission-context bug.

## Consequences

**Positive**
- Strict interpretation of concept §3.5 is satisfied technically, not just contractually.
- DPO trust: the architecture is explainable in one sentence ("we don't show forbidden content to the LLM").
- Audit reconstructability: the action log captures the permission-filter hash, so a regulator can verify the scope under which any answer was produced.

**Negative**
- Slightly worse recall in some queries: if the user's clearance is low, the candidate set is small and the bot may not find an answer where a clearance-bypassing system would. We accept this; for a state-owned company it is the correct tradeoff.
- Permission context must be resolved before every retrieval call. Cached in Redis per session (with TTL ≤ 15 min) to limit Entra ID round-trips.

**Neutral**
- The post-generation check is cheap (string match against permitted IDs) and remains in place as defence in depth, not as the primary control.
