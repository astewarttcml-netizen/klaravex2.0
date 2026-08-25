# Data residency
### visitBerlin Knowledge Manager — by Klaravex GmbH

**Companion to:** `dpia.md`, `gdpr-dossier.md`, `nis2.md`, `bsi-c5.md`
**Date:** 2026-06-27

---

## 1. Headline

All customer data at rest is in Germany. The only customer data leaving Germany in normal operation is the prompt-and-completion traffic to Azure OpenAI, which is processed in Sweden-Central (primary) or France-Central (failover) — both inside the EEA, both inside the Microsoft EU Data Boundary. No US service is in the data path.

---

## 2. Per-category residency table

| Category | Stored where | Processed where | Justification |
| --- | --- | --- | --- |
| Document originals | Azure Blob Storage, Germany-West-Central; geo-replicated GRS to Germany-North | Germany-West-Central | Sovereignty + DR |
| Document text extractions | Azure PostgreSQL Flex, Germany-West-Central; geo-replica in Germany-North | Germany-West-Central | Sovereignty + DR |
| Embeddings | Azure AI Search, Germany-West-Central; rebuildable from PostgreSQL on DR failover | Germany-West-Central | Sovereignty |
| AI tags, summaries | PostgreSQL, Germany-West-Central | Germany-West-Central for storage; Sweden-Central / France-Central for LLM inference that produced them | Inference outside Germany justified in §3 below |
| User profile (Entra ID source + overlay) | Entra ID (Microsoft EU Data Boundary) + PostgreSQL Germany-West-Central | Germany-West-Central | Sovereignty + EUDB |
| Action log (7 yr) | PostgreSQL Germany-West-Central; archived monthly to Blob Storage with object-lock | Germany-West-Central | Sovereignty |
| Read log (90 days) | PostgreSQL Germany-West-Central | Germany-West-Central | Sovereignty |
| Bot prompt and completion (in-flight) | Not persisted by Azure OpenAI per service terms; transit only | Sweden-Central or France-Central | See §3 |
| Tourism Data Hub PII | Stays at the hub (not copied — ADR-0003) | Queried at the hub's location | No-copy posture |
| M365 source content (SharePoint, Teams, opt-in mailbox) | Microsoft 365 (EU Data Boundary) | Microsoft 365 EU Data Boundary | Customer tenant residency |
| Telemetry (metrics, logs, traces) | Azure Monitor Germany-West-Central Log Analytics workspace | Germany-West-Central | Sovereignty |
| Secrets, keys | Azure Key Vault Germany-West-Central | Germany-West-Central | Sovereignty |
| IaC source, CI/CD artefacts | GitHub Enterprise (Microsoft EU Data Boundary configuration) | EU | EUDB |

---

## 3. Why Azure OpenAI is in Sweden-Central / France-Central, not Germany

Microsoft's Azure OpenAI Service is not, as of 2026, available in Azure Germany regions. The nearest EEA regions offering the required models are:

| Region | Models available (2026, indicative) | RTT from Germany-West-Central (p95, Azure backbone, internal vNet peering) |
| --- | --- | --- |
| France-Central | GPT-4o, GPT-5 class, text-embedding-3-large | ~15–20 ms |
| West-Europe (Netherlands) | Reduced model catalogue | ~15 ms |
| Switzerland-North | Reduced model catalogue | ~10 ms |
| Sweden-Central | GPT-4o, GPT-5 class, text-embedding-3-large | ~30–40 ms |

RTT figures are p95 observed across Klaravex internal Bicep test deployments (Q1 2026), measured over Azure vNet peering on the Microsoft backbone, not the public Internet. They are indicative; exact figures fluctuate by hour and by Microsoft backbone routing changes.

We choose **France-Central as primary** because its round-trip from Germany-West-Central (~15–20 ms) is roughly half that of Sweden-Central (~30–40 ms), and synthesis sits on the user-critical path where every millisecond saved on time-to-first-token reduces p50 directly. **Sweden-Central is the failover** and may also serve as a temporary primary when a required model SKU is GA in Sweden but not yet in France (Sweden-Central historically receives new Azure OpenAI SKUs first within the EEA footprint; ADR-0005). Both are inside the EEA. Both are inside Microsoft's EU Data Boundary. Both connect to Germany-West-Central over the Microsoft backbone, not the public Internet.

This is a known asymmetry in the Azure-Germany sovereignty story. We surface it openly rather than hide it.

---

## 4. Microsoft EU Data Boundary

The Microsoft EU Data Boundary (EUDB) is Microsoft's public commitment to store and process customer data for European customers within the EU/EEA, covering Azure, Microsoft 365, Dynamics 365, and Power Platform. Key limitations to be aware of:

- **Customer data and pseudonymous personal data:** stored and processed in EUDB.
- **Telemetry and operational data:** processed in EUDB.
- **Limited exceptions:** small categories of professional services data, certain legal/compliance investigations, and limited engineering-support diagnostic data may cross borders. Microsoft documents these publicly.

The Klaravex position:

- For the visitBerlin Knowledge Manager, customer data and operational metadata stay in EUDB.
- For the limited exceptions, the Microsoft Online Services DPA applies with Standard Contractual Clauses (2021/914) as the supplementary measure for any actual cross-border flow.
- Klaravex notifies the visitBerlin DPO of any actual support-diagnostic cross-border flow it becomes aware of within 24 h.

---

## 5. Migration path when Azure OpenAI lands in Germany regions

Klaravex's adapter pattern isolates LLM provider behind a single interface (`architecture.md` §3.2 step 5; ADR-0005). When Microsoft adds Azure OpenAI to a Germany region with the required model catalogue:

1. **Validation phase (1 week):** deploy adapter pointing at the Germany endpoint in staging; run regression suite; compare bot answer quality on a fixed set of pilot queries.
2. **Switch-over (1 day):** configuration change, no code change. Embedding workload switched first; the existing 3072-dim index does not require re-embedding (text-embedding-3-large is consistent across regions).
3. **Synthesis cutover (1 day):** bot synthesis traffic flipped to the Germany endpoint; Sweden-Central / France-Central retained as failover for a transition period.
4. **Decommission (1 week later):** transition complete; failover policy updated.

End state: 100% of customer data, including prompt/completion traffic, stays in Germany.

---

## 6. Data classification residency rules (summary)

| Confidentiality level | Storage region | Inference region | Notes |
| --- | --- | --- | --- |
| Public | Germany | EEA (current Sweden-Central / France-Central) | No additional constraints |
| Internal | Germany | EEA | No additional constraints |
| Confidential | Germany | EEA | Permission filter at retrieval restricts who can query |
| Strictly confidential | Germany | EEA | Same; plus mandatory MFA and PIM-elevated access for owner/approver actions |

The same residency rules apply across all classifications. The differentiator on Strictly confidential is procedural and access-control, not residency.

---

## 7. Customer-managed keys (optional, on request)

If visitBerlin requires customer-managed keys (CMK):

- Blob Storage and PostgreSQL Flex support CMK via Azure Key Vault.
- Key Vault in Germany-West-Central with geo-replication to Germany-North.
- visitBerlin holds the key material; Klaravex operates against the key under documented access policy.
- Rotation policy: annual default; customer-configurable.

CMK is **not** the default — the operational cost of customer-side key management is real, and Microsoft-managed keys with Azure HSM backing are themselves strong. CMK is offered for customers with a regulatory or internal-policy requirement for it.

---

## 8. References

- Microsoft EU Data Boundary, public documentation (Microsoft Trust Center).
- Azure OpenAI Service regional availability matrix.
- Microsoft Online Services DPA + Standard Contractual Clauses (2021/914).
- `gdpr-dossier.md` §4 (international transfers section).
- `architecture.md` §2 and §9.

---

*End of data-residency document.*
