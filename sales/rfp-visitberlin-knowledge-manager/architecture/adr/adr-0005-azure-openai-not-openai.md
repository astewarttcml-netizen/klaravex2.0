# ADR-0005 — Azure OpenAI in EEA region; no direct OpenAI

**Status:** Accepted
**Date:** 2026-06-27

## Context

The system requires a frontier-grade LLM for tagging, summarisation, and bot answer synthesis, plus an embedding model for retrieval. The DPO will reject any architecture that calls OpenAI's US-region API directly or routes through a US sub-processor.

Options:

1. **OpenAI direct (api.openai.com).** Disqualified — US-region, US sub-processor.
2. **Azure OpenAI in a US region.** Disqualified — Azure but US-region.
3. **Azure OpenAI in an EEA region.** Available regions as of 2026 with current models: Sweden-Central, France-Central, Switzerland-North, West-Europe. None are inside Germany.
4. **Self-hosted open-weights model in Germany-West-Central.** Operationally heavier; today's open-weights frontier (Llama 4, Mistral Large 3, Qwen 3) is acceptable for tagging/summarisation but lags Azure OpenAI for hallucination rate on the bot's answer-synthesis task.
5. **Hybrid: Azure OpenAI for bot answers; self-hosted for batch tagging/summarisation.** Reduces external API surface for the highest-volume operations.

## Decision

- **Primary path:** Azure OpenAI in **France-Central** (preferred for latency from Germany-West-Central, ~15–20 ms vs ~30–40 ms for Sweden-Central per `compliance/data-residency.md:30`) with **Sweden-Central** as failover. The latency edge matters because the synthesis call is on the user-critical path; on a streaming-first chain, every saved millisecond on the first-token round-trip reduces p50 by approximately the same amount.
- **Model-availability caveat:** Sweden-Central historically receives new model SKUs first within the EEA Azure OpenAI footprint. If a required model (e.g. a successor to GPT-5) is GA in Sweden but not yet in France, the adapter is reconfigured to Sweden as primary with France as failover until France catches up. This trade-off is encoded in the adapter's region-policy config, not hard-coded.
- **Embedding model:** `text-embedding-3-large` (or successor) on Azure OpenAI.
- **Synthesis model:** GPT-4o or GPT-5 class (whichever is GA in the chosen Azure OpenAI region at deployment).
- **No direct OpenAI.** All LLM/embedding traffic terminates inside Azure under the Azure OpenAI service terms and the Microsoft EU Data Boundary commitment.
- **Migration path to Azure Germany:** Architecture isolates LLM access behind a single adapter interface. When Azure OpenAI becomes available in Germany-West-Central or Germany-North, switching is a configuration change plus index re-embedding (planned).

Hybrid (option 5) is a phase-2 optimisation to be evaluated based on cost and bot-quality metrics from pilot. We do not commit to it at v1.

## Consequences

**Positive**
- Strong sovereignty narrative within the EEA. Microsoft EU Data Boundary applies. No US data processing.
- Operational simplicity: one model provider, Microsoft's commercial relationship.
- Frontier model quality available without an open-weights operations burden during pilot.

**Negative**
- LLM traffic crosses Germany-WC ↔ France-Central network. Latency added ~15–20 ms steady-state (Sweden-Central failover adds ~30–40 ms). Documented in `compliance/data-residency.md`.
- Microsoft EU Data Boundary has known carve-outs (limited engineering support data crossing borders for diagnostic purposes). These are documented in the DPIA in `compliance/dpia.md`.
- If Microsoft alters its EU Data Boundary commitments, this ADR is re-opened.

**Neutral**
- The adapter pattern means the choice can be revisited without architectural change.
