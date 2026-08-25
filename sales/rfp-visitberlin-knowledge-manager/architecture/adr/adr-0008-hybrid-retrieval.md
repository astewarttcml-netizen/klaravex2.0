# ADR-0008 — Hybrid retrieval: BM25 + vector + graph hop with cross-encoder reranker

**Status:** Accepted
**Date:** 2026-06-27

## Context

The bot must answer queries spanning three retrieval shapes:

1. **Keyword-tight queries.** "Show me the BWC partner terms 2026." BM25 wins; vector recall is noisier on short, exact-term queries.
2. **Concept queries.** "What was decided about sustainability reporting last quarter?" Vector search wins; the user's wording rarely matches the document wording exactly.
3. **Structured-data queries.** "Who is our contact at the Berlin Welcome Card partner in Charlottenburg?" Neither BM25 nor vector search will produce reliable answers; the data lives in the Tourism Data Hub graph, not in the Knowledge Manager corpus.

A single-mode retrieval (vector-only, common in v1 RAG demos) fails on (1) and (3). A two-mode (BM25 + vector) fails on (3).

## Decision

Three retrievers run in parallel for every bot query:

1. **BM25** keyword search against Azure AI Search, with the permission filter applied (ADR-0002).
2. **Vector kNN** against the same index (`text-embedding-3-large`, 3072-dim, HNSW), same permission filter.
3. **Graph hop** against the Tourism Data Hub via the read-only adapter (ADR-0003), triggered when intent classification on the query identifies a structured-data need (POI / BWC partner / stakeholder contact).

Results are merged with **Reciprocal Rank Fusion** (RRF) — a robust no-tuning-needed fusion that handles heterogeneous score scales.

A **cross-encoder reranker** then re-scores the top ~50 fused candidates against the original query and selects the top 8 for the LLM context.

The reranker uses Azure AI Search's built-in semantic ranker for v1 simplicity; a self-hosted cross-encoder is a phase-2 cost-optimisation evaluation.

## Consequences

**Positive**
- Robust across all three query shapes.
- RRF needs no tuning; the system works on day one and improves as the reranker is tuned.
- Graph hop is honestly read-only and stays in its lane (ADR-0003).

**Negative**
- Latency: three parallel retrievers + RRF + rerank adds budget. We size for p95 ≤ 2 s on the retrieval portion (proposal §6.9 latency target ≤ 8 s p95 end-to-end leaves room).
- Cost: three retrievers run per query (BM25 is free, vector is cheap, hub hop only fires when intent-classified — overall cost dominated by Azure OpenAI synthesis, not retrieval).
- Intent classification adds a small additional call; we collapse it into the same step as query expansion to share an LLM round-trip.

**Neutral**
- The reranker choice is reversible. v2 may move to a self-hosted cross-encoder (e.g. `bge-reranker-v2-m3`) for cost or for sovereignty reasons.
