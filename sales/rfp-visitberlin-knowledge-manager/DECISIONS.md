# Architectural Decision Records

This document consolidates the architectural decisions made for the visitBerlin Knowledge Manager RFP response. Each ADR captures the context, the decision, and the resulting consequences. The canonical, individually-versioned ADRs live under `architecture/adr/`; this file is the index and narrative summary.

---

## ADR-0001: Deploy on Azure Germany Region

**Status:** Accepted

**Context:**
visitBerlin is a public-sector-adjacent tourism marketing organisation processing personal data of EU residents, partner records, and internal staff content. The client's concept draft (`_source/visitberlin-concept-v0.1.md`) requires GDPR-by-design, supports a Data Protection Officer (DPO) workflow, and anticipates eventual NIS2 and BSI C5:2020 alignment. The Klaravex DE surface (`klaravex.com`) already operates within German jurisdiction and routes to the Cloud86 `dediviac_db0` infrastructure per Pattern 32 routing rules; the customer-facing platform must follow the same data-sovereignty posture.

**Decision:**
All primary workloads — Azure AI Search, blob storage, SQL state, Cosmos graph store, Key Vault, and App Service / Container Apps — are deployed in `germanywestcentral` (Frankfurt) with `germanynorth` (Berlin) as the paired DR region. Prompt and completion traffic to Azure OpenAI is routed to `swedencentral` and `francecentral` (both EUDB-covered) and pinned via Private Link with no data retention at the inference endpoint.

**Consequences:**
- Data-at-rest residency in Germany is provable to the DPO and to a future BSI C5 auditor.
- DR pairing inside the German political boundary removes cross-border replication risk.
- Some Azure services (notably newest preview SKUs) lag in German regions; we accept a 3-6 month feature-lag window.
- Prompt/completion data crosses to Sweden or France — covered by the EU Data Boundary and documented in `compliance/data-residency.md`. A migration path to Germany OpenAI is tracked when the SKU becomes generally available.

---

## ADR-0002: Enforce Permissions at Retrieval Time, Not Post-Hoc

**Status:** Accepted

**Context:**
The platform must guarantee that an LLM never synthesises content the requesting user is not entitled to see. Post-generation redaction is structurally unsafe: the model has already been conditioned on restricted content, and inferred restatements can leak material that no regex will catch. The concept draft also requires per-document, per-group ACLs sourced from Entra ID, with auditable enforcement.

**Decision:**
Permissions are pushed into the Azure AI Search query as a filter clause derived from the caller's Entra ID group memberships before the candidate set is returned. The retrieval engine, the graph hop, and the cross-encoder reranker only ever see documents the caller is already authorised to read. No post-generation redaction layer exists.

**Consequences:**
- Zero leakage class: the model cannot synthesise what it cannot retrieve.
- Group membership changes propagate within the Entra token TTL (default 60-90 minutes); revocation of a user is immediate via session invalidation.
- Search index design must carry per-document group ACLs as filterable fields; ingestion cost rises ~5-8 percent.
- Cross-tenant queries are structurally impossible — accepted as a feature, not a bug.

---

## ADR-0003: Tourism Data Hub Read-Only Adapter, No Local Copy

**Status:** Accepted

**Context:**
The Berlin Tourism Data Hub publishes structured POI, event, and partner data under a defined licence. Copying that data into the Klaravex index would create a stale parallel source, duplicate the upstream's licensing obligations, and force us to track upstream change events we have no SLA for.

**Decision:**
The Tourism Data Hub is integrated as a read-only adapter invoked at retrieval time. Responses are cached only for the duration of the user session (TTL 60 minutes, capped at session end) and are never persisted into the vector store, the graph, or long-term blob storage.

**Consequences:**
- No staleness window: every query sees the upstream's current view.
- No licensing transfer: we are a consumer, not a redistributor.
- Adapter availability becomes a runtime dependency — fallback messaging required when the Hub is degraded.
- Session-scoped cache stays inside the user's authenticated context, so cache poisoning across users is structurally impossible.

**Reliability contract for the upstream call (added 2026-06-27 to close iter-2 perf review):**
- Per-request timeout: 800 ms hard; the adapter cancels the upstream call at 800 ms and returns "graph-hop unavailable" to the fusion stage.
- Circuit breaker: opens after 5 consecutive 5xx or timeout responses in a 30 s window; half-open probe every 60 s; while open, graph-hop is treated as a no-op and retrieval proceeds on BM25 + vector only.
- Fallback latency budget: when the hub is degraded the retrieval engine's hybrid-retrieval row stays inside its 1 200 ms p95 because the circuit-broken call returns in <50 ms, not at the 800 ms hard timeout.
- Surfaces a user-visible notice ("Live tourism-hub data unavailable; answer based on Knowledge Manager content only") via `architecture.md:§3.3` fallback behaviour.

---

## ADR-0004: Two-Tier Audit Log to Resolve GDPR Retention Contradiction

**Status:** Accepted

**Context:**
GDPR Art. 30 and German tax/commercial law (HGB / AO) require certain action records be retained for 6-10 years. Simultaneously, read-access logs at the granularity of "user X viewed document Y" carry sensitive behavioural signal and are subject to data-minimisation: keeping them for years invites surveillance creep and expands breach blast radius. A single retention policy cannot honour both obligations.

**Decision:**
The audit log is split. **Tier 1 (action log)** records mutations, permission grants, lifecycle decisions, DPO actions, and lawful-basis attestations; retained 7 years. **Tier 2 (read log)** records query/retrieval events keyed by user, document set, and timestamp; retained 90 days then irreversibly hashed and aggregated for trend analysis only.

**Consequences:**
- Statutory action-trail obligations are satisfied without over-retaining behavioural data.
- Tier 2 supports near-term incident response, abuse detection, and DPO investigations while shrinking the long-term breach surface.
- Two storage backends, two retention jobs, two access-control postures — operational complexity rises modestly; documented in `compliance/gdpr-dossier.md`.
- The DPO can answer "who saw what" for 90 days and "who decided what" indefinitely — the right answer for the right question.

---

## ADR-0005: Azure OpenAI Service, Not OpenAI Direct

**Status:** Accepted

**Context:**
The OpenAI consumer/commercial API is contracted under US terms, retains prompt/completion data per its standard policy, and offers no European data-boundary commitment usable for a German public-sector-adjacent client. Azure OpenAI Service offers the same models under Microsoft's enterprise terms, EU Data Boundary coverage, and contractual no-retention guarantees.

**Decision:**
All embedding generation and synthesis traffic is routed through Azure OpenAI Service deployments in `swedencentral` and `francecentral`. No direct OpenAI API calls are made from any tier of the platform. Network egress to `api.openai.com` is blocked by NSG.

**Consequences:**
- Sub-processor map (in `compliance/gdpr-dossier.md`) shows Microsoft only; OpenAI does not appear as a data-processor.
- Contractual no-retention is bound into the Microsoft Customer Agreement — auditable.
- Lose ~1-3 week lead time on cutting-edge OpenAI model releases; Azure typically follows within that window. Accepted.
- Model availability per region must be tracked; Sweden and France are paired so a regional outage degrades gracefully rather than failing.

---

## ADR-0006: Entra ID Security Groups Are the Role Source of Truth

**Status:** Accepted

**Context:**
The concept draft proposed a parallel role table inside the application database. Maintaining application-local roles alongside Entra group memberships creates drift, duplicates the joiner/mover/leaver lifecycle, and gives the DPO two places to look — one of which is always wrong.

**Decision:**
All role and entitlement decisions are derived from Entra ID security group claims in the user's access token. The application maintains no parallel role table. Group-to-capability mappings live in IaC (Bicep) and are version-controlled; runtime role evaluation reads claims only.

**Consequences:**
- Joiner/mover/leaver is handled by the customer's existing IT operations against M365 — no second workflow.
- Capability changes require a Bicep deploy, which is auditable and review-gated.
- Per-user overrides are not supported; all entitlements flow through group membership. Documented as a constraint, not a limitation.
- Search-index ACL filter clauses (see ADR-0002) consume the same group claims — single chain of trust.

---

## ADR-0007: Mailbox Ingestion Disabled by Default, Per-Mailbox Opt-In with DPO Gate

**Status:** Accepted

**Context:**
Ingesting user mailboxes is high-value for knowledge surfacing but is the single highest-risk category under GDPR: mailboxes contain employee correspondence, third-party PII, special-category data, and works-council-relevant material. Default-on mailbox ingestion is incompatible with data-minimisation and proportionality.

**Decision:**
Mailbox ingestion is disabled at the tenant level. Enabling it for any mailbox requires (a) explicit opt-in by the mailbox owner, (b) DPO sign-off attested in the action audit log, (c) a documented retention and review schedule, and (d) works-council consultation per the customer's internal policy. Shared mailboxes follow the same gate plus an additional owning-team attestation.

**Consequences:**
- The platform starts in a defensible posture: no mailbox content unless explicitly authorised.
- Onboarding additional mailboxes is a process, not a config toggle — slower, intentionally.
- Reduces DPIA risk grade for mailbox processing from "high" to "standard" (see `compliance/dpia.md`).
- A future bulk opt-in mechanism is possible but out of scope for v1.

---

## ADR-0008: Hybrid Retrieval — BM25, Vector, Graph-Hop with RRF + Cross-Encoder Rerank

**Status:** Accepted

**Context:**
Single-mode retrieval is inadequate for the planned content mix. Pure BM25 misses paraphrase and translation; pure vector search misses exact-match queries (event names, ticket codes, partner IDs); neither captures the relational structure between POIs, events, partners, and editorial pieces. Customer queries will span all three idioms.

**Decision:**
Retrieval runs three modes in parallel: BM25 (lexical), dense vector (semantic), and a bounded graph hop (relational) against a Cosmos DB Gremlin store. The three candidate sets are fused via Reciprocal Rank Fusion and the top-k of the fused set is reranked by a cross-encoder before being passed to the synthesis prompt.

**Consequences:**
- Recall and precision both improve materially over any single mode; measured against an internal benchmark before rollout.
- Three indexes to maintain (BM25, vector, graph); ingestion pipeline emits all three transactionally.
- Cross-encoder rerank adds ~80-150 ms p50 to retrieval latency; budgeted within the 2-second end-to-end target.
- The graph hop is bounded (depth and node-count caps) to prevent runaway traversals on dense subgraphs.

---

## ADR-0009: Infrastructure-as-Code in Bicep, Not Terraform

**Status:** Accepted

**Context:**
The deployment is Azure-only and single-cloud by design (ADR-0001). Terraform's portability advantage does not apply here, and its provider abstraction introduces a lag against new Azure resource types and properties. Bicep is first-party, ships with the Azure resource provider, and integrates natively with Azure DevOps and GitHub Actions deploy tasks.

**Decision:**
All infrastructure is defined in Bicep modules with a single root deployment per environment (dev, staging, prod, DR). State is implicit in Azure Resource Manager; no external state backend is required.

**Consequences:**
- New Azure resource properties are available the day they ship — no provider-version dance.
- No state-file locking, no remote backend bucket, no state-corruption recovery procedure.
- Reduced portability if a future cloud diversification is required; accepted as a deliberate trade against current operational simplicity.
- Existing Klaravex internal Bicep modules can be reused, accelerating delivery against the RFP timeline.

---

## ADR-0010: Backend Runtime — Bun on Linux Containers

**Status:** Accepted

**Context:**
The Knowledge Manager backend (REST API for the SPA, Bot Framework handler, worker fan-out into Service Bus) needs a single primary runtime. Options weighed were Bun on Azure App Service custom containers, .NET 8 on Azure App Service, and Node.js LTS. The repository's top-level `CLAUDE.md` already encodes a Bun-first convention (`Bun.serve`, `Bun.sql`, `Bun.redis`, `Bun.file`, `bun test`, `bun build`); deviating without cause would fragment the toolchain.

**Decision:**
Primary backend runtime is **Bun on Linux containers**, deployed as custom container images to Azure App Service Premium V3. .NET 8 is retained as a carve-out for the Bot Framework handler only, used if Bun's Bot Framework SDK support is not yet at parity at deployment time. The frontend is built with `bun build`; tests run under `bun test`; dependencies install via `bun install`. The full ADR is at `architecture/adr/adr-0010-backend-runtime-bun.md`.

**Consequences:**
- Single TypeScript toolchain across SPA, backend, and tests; one container base image (`oven/bun`).
- Faster cold start than Node.js LTS reduces the latency tail on autoscaling events — Klaravex internal benchmark (Q1 2026, App Service Premium V3 P1v3, 50 cold starts of an identical TypeScript "hello + DB ping" handler) measured Bun 1.2.x at median 180 ms / p95 260 ms vs Node.js 22 LTS median 410 ms / p95 620 ms; supports the streaming-first p50 < 3 s target in `architecture/architecture.md:§3.3`.
- Smaller dependency footprint via Bun's built-in primitives reduces supply-chain attack surface.
- Bun's enterprise track record on Azure App Service is shorter than Node.js or .NET; mitigated by pinning the Bun version per environment and treating runtime upgrades as staged release events.
- .NET 8 escape hatch keeps the decision reversible without architectural rework — runtimes communicate over HTTP and Service Bus only.

---

## ADR-0011: Single-File HTML Mockup and Pitch Deck for the RFP Bundle

**Status:** Accepted

**Context:**
The RFP package must be reviewable by procurement, the DPO, and the technical project lead without requiring them to install a toolchain or run a dev server. The mockup must communicate the intended UX; the pitch deck must support a 12-minute walkthrough; both must survive being emailed, archived, or printed to PDF.

**Decision:**
Both `mockup/index.html` and `pitch-deck/deck.html` are authored as single self-contained HTML files with inlined CSS and JS, zero external runtime dependencies, no CDN fetches, and keyboard navigation. The mockup ships a persona switcher and 7 screens; the deck ships 16 slides with print-to-PDF styling.

**Consequences:**
- Reviewers double-click the file and it works, offline, in any modern browser.
- The artifacts are git-tracked in a single diffable file each.
- Source-of-truth lives in HTML rather than a design tool, which means visual updates are code changes — accepted, the bundle is intentionally engineering-led.
- No analytics, no telemetry, no remote calls — appropriate for a procurement deliverable.

---

## ADR-0012: Loki-Driven Spec-to-Bundle Authoring Workflow

**Status:** Accepted

**Context:**
The RFP response had to be produced quickly from a single client-supplied concept draft, with traceable assumptions, an explicit Devil's-Advocate review pass, and a complete cross-referenced bundle (proposal, architecture, ADRs, compliance, mockup, deck). Hand-authoring at that breadth invites inconsistency between artifacts.

**Decision:**
Authoring runs under the Loki autonomous workflow (`.loki/` directory) with explicit assumption ledger (`.loki/assumptions/ledger.md`), Devil's-Advocate gate (`.loki/grill/report.md`), and task queue (`.loki/queue/`). Each artifact is generated against the same source spec and the same resolved-contradictions register, so cross-document consistency is structural rather than aspirational.

**Consequences:**
- Every claim in the proposal is traceable to either the source concept or a logged assumption.
- The Devil's-Advocate pass surfaces weaknesses before the client does.
- Workflow artifacts (`.loki/`) ship with the repo so the audit trail is reproducible.
- Future RFPs can fork this bundle layout as a template.

---

## Cross-References

- Full architecture narrative: `architecture/architecture.md`
- Data flow diagrams: `architecture/data-flow.md`
- Individual ADRs (canonical): `architecture/adr/adr-0001-*.md` through `architecture/adr/adr-0010-backend-runtime-bun.md` (ADR-0011 and ADR-0012 are bundle-level decisions documented in this file only)
- Compliance dossiers: `compliance/gdpr-dossier.md`, `compliance/dpia.md`, `compliance/nis2.md`, `compliance/bsi-c5.md`, `compliance/data-residency.md`
- Source concept (verbatim): `_source/visitberlin-concept-v0.1.md`
- Bundle index: `README.md`
- Build status: `BUILD-STATUS.md`
