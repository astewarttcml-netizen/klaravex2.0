# ADR-0011 — Azure Subscription Topology Ingestion and Ownership Tagging

**Status:** Accepted
**Date:** 2026-07-20
**Context for:** Knowledge Manager for visitBerlin

## Context

The visitBerlin KM ingests content from five declared sources (manual upload, SharePoint, Teams, mailbox opt-in, Tourism Data Hub read-only). None of these surfaces the Azure infrastructure itself as a queryable body of knowledge. As visitBerlin's Azure footprint grows, operations staff and procurement reviewers need to answer questions like "who owns this resource?", "what changed last week?", and "which services are connected to the knowledge ingestion pipeline?" — without leaving the KM or filing a support ticket with the platform team.

A secondary operational need is ownership traceability: when a resource is touched (deployed, reconfigured, scaled), the change must be attributable to a specific Entra identity, timestamped, and surfaced in the audit chain described in ADR-0004.

Azure Resource Graph provides a single REST-queryable layer over all resources in a subscription — returning type, name, location, tags, resource group, and relationship edges — without copying the underlying data out of Azure.

## Decision

Add a sixth ingestion source: **AzureSubscriptionAdapter**.

### Adapter mechanics

```
Service Principal (Reader + Tag Contributor — subscription scope)
    │
    ▼
Azure Resource Graph API  (ResourceGraphClient.resources)
    → Returns every resource: type, name, location, tags, rg, relationships
    │
    ▼
AzureSubscriptionAdapter  (new module: src/ingestion/adapters/azure_subscription.ts)
    → Each resource normalised to ContentItem { content_id, source, body, metadata }
    → Relationship edges written to Cosmos DB Gremlin as topology layer
    → Tag upsert: writes km-owner, km-last-touched-by, km-last-touched-at, km-ingested-by
    │
    ▼
Same downstream pipeline as all other adapters
    → extract → chunk → embed → index into Azure AI Search
    → Queryable by the bot and surfaced in the topology UI screen
```

### Mandatory ownership tags

Every resource in scope receives four tags, written back via the ARM API at ingestion time and enforced forward by Azure Policy:

| Tag key | Value source | Enforcement |
|---|---|---|
| `km-owner` | Entra UPN resolved from the resource's role assignments (Owner or Contributor role, first match) | Policy: `deny` if missing after 48 h |
| `km-last-touched-by` | UPN from the most recent Activity Log write event for this resource | Written by the Event Hub trigger (see below) |
| `km-last-touched-at` | ISO 8601 timestamp from the same Activity Log event | Written by the Event Hub trigger |
| `km-ingested-by` | Literal `klaravex-km-adapter` | Written by AzureSubscriptionAdapter at first ingest |

Missing `km-owner` triggers a Defender for Cloud compliance finding. Non-compliant resources appear in the topology UI with a red ownership badge.

### Forward-change audit chain

```
Azure Activity Log (all resource writes in the subscription)
    → Azure Event Hub  (stream, retention 7 days)
    → Azure Function trigger  (event-driven, Germany-West-Central)
    → KM action_log INSERT: { actor_upn, resource_id, operation, timestamp, subscription_id }
    → ARM PATCH: updates km-last-touched-by + km-last-touched-at on the resource
```

This closes the traceability loop: any resource mutation is captured within seconds, the KM action log record satisfies the 7-year retention requirement in ADR-0004 (action log tier), and the tag on the resource is always current for any agent or operator who inspects it.

### Topology UI screen (screen 8)

A new screen in the KM UI presents the subscription as a force-directed graph:

- **Nodes:** each Azure resource, colour-coded by type (compute / storage / network / identity / AI)
- **Clusters:** resource groups as containing boundaries
- **Edges:** relationship types (vNet peering, managed identity binding, Service Bus link, App Service ↔ Key Vault reference)
- **Node side panel (on click):** owner UPN, last-touched-by, last-touched-at, linked KM content items, open lifecycle flags, compliance badge
- **Filter bar:** by resource type, resource group, owner, compliance state

## Alternatives considered

- **Azure Network Watcher topology only.** Covers only network resources; misses storage, AI, identity. Rejected.
- **Manual tagging via portal.** Does not scale; breaks on resource redeployment; no audit trail. Rejected.
- **Third-party CMDB (ServiceNow, Lansweeper).** Introduces a data processor outside the Germany region boundary established in ADR-0001 unless a German-hosted instance is provisioned. Adds cost and operational complexity. Rejected for this phase; may be revisited at >500 resource scale.
- **Read-only Resource Graph without tag write-back.** Provides topology view but no ownership enforcement and no forward-change traceability. Insufficient for ADR-0004 compliance. Rejected.

## Consequences

**Positive**
- Operations staff can answer resource-ownership questions from within the KM bot without accessing the Azure portal.
- Every future resource mutation is automatically attributed to an Entra identity and surfaced in the existing audit log.
- Azure Policy enforcement ensures tagging discipline is maintained by all deployers, not just the KM adapter.
- Topology screen provides a build-vs-runtime diff signal: what Bicep declared vs what actually exists.

**Negative**
- Service Principal requires `Tag Contributor` at subscription scope — broader than the read-only access granted to other adapters. Must be reviewed and justified in the security architecture sign-off with visitBerlin IT.
- Event Hub adds a small streaming cost (~€5–15/month at visitBerlin's expected mutation rate).
- ARM tag write-back introduces a write dependency: if the adapter's Service Principal token is revoked, tags go stale. Mitigated by a daily freshness check that flags resources with `km-ingested-by` older than 25 hours.

**Neutral**
- Ingestion cadence: full Resource Graph sweep every 6 hours (configurable). Event Hub trigger is real-time for forward changes.
- Existing `content_id` keying scheme: `azure-subscription:{subscription_id}:resource:{resource_id}` — unique, stable, idempotent re-ingest safe.
- Relationship edges in Cosmos DB Gremlin follow the same schema as ADR-0008 hybrid retrieval; no schema change required.
