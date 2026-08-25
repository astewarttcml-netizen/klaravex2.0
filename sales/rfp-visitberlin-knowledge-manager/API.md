# API — visitBerlin Knowledge Manager

Companion to `architecture/architecture.md` and `architecture/data-flow.md`.

This package contains no source code. The proposal describes a system to be built; the interfaces below are the public surface of that proposed system as committed in the architecture documents. All HTTP paths are versioned under `/api/v1` and served by the Knowledge Manager Web API behind Azure Front Door + WAF.

## 1. Conventions

- **Transport.** HTTPS only. TLS 1.2+.
- **Auth.** OAuth2 / OIDC against the visitBerlin Microsoft Entra ID tenant. Bearer access token in `Authorization` header, or HttpOnly session cookie for the SPA (SameSite=Lax, 8h idle, 24h absolute).
- **Identifiers.** `content_id` is UUIDv7. All timestamps are ISO 8601 UTC.
- **Errors.** RFC 7807 `application/problem+json` with `type`, `title`, `status`, `detail`, `correlation_id`.
- **Correlation.** Every request carries an `X-Correlation-Id`; the same id appears in the action log row for the request.
- **Permissions.** Enforced at the search-layer `filter` clause, not after retrieval (ADR-0002). 403 responses are themselves auditable events.

## 2. REST endpoints

### 2.1 Content

#### POST /api/v1/content

Upload a new content item. Used by the SPA upload zone and by the in-platform notes form.

| Field | Type | Notes |
| --- | --- | --- |
| Body | `multipart/form-data` | `file` part (binary), `metadata` part (JSON: title, responsible_unit, language, optional confidentiality_hint) |
| Max size | 100 MB | Enforced at the gateway |
| Required role | `KM-Author` | Or any higher role |
| Returns | `202 Accepted` | `{ content_id, status: "scanning" }` |

Side effects: writes original to the landing blob container, enqueues virus scan (Defender for Storage), writes `content.uploaded` to the action log. The downstream AI processing chain is asynchronous; status is observable via `GET /api/v1/content/{content_id}`.

Errors: `413` oversize, `415` unsupported MIME, `400` missing metadata, `403` not in `KM-Author` group.

#### GET /api/v1/content/{content_id}

Read the canonical content record. Filtered by the caller's permission context; returns `404` indistinguishably from `403` for items the caller is not permitted to read.

Returns the canonical record shape from `architecture.md` §3.1:

```
ContentItem {
  id: UUID,
  source: { type, source_id, ingested_at, last_seen_at },
  original_blob: { container, path, sha256, size, content_type },
  extracted_text: string,
  metadata: { title, author, date_created, date_modified, responsible_unit, language },
  ai_metadata: { tags[], category, summary, language_detected, confidence_scores },
  lifecycle: { validity_until, status, content_owner_id, approver_id },
  permissions: { confidentiality_level, abac_attributes },
  version_history: [],
  audit_ref: string
}
```

`status` ∈ `{ scanning, processing, pending_approval, current, review_due, outdated, archived, quarantined }`.

#### PATCH /api/v1/content/{content_id}

Update mutable fields. Authors may patch `metadata.title`, `metadata.responsible_unit`; Content Owners may patch lifecycle fields within their `<area>`; Approvers may set `permissions.confidentiality_level` and transition `pending_approval → current`. Returns `200` with updated record, or `409` on stale `If-Match` ETag.

#### POST /api/v1/content/{content_id}:archive

Soft-delete; transitions status to `archived`. Requires Content Owner of the item or Administrator. Audit event `content.archived`.

### 2.2 Bot

#### POST /api/v1/bot/answer

Answer a natural-language query with cited sources. Used by both the Teams personal app and the Web sidebar.

Request:

```
{
  "query": "string",
  "session": { "session_id": "string", "locale": "de-DE" | "en-US" }
}
```

Response:

```
{
  "answer": "string",
  "citations": [
    { "content_id": "UUID", "snippet": "string", "view_url": "string", "status": "current" | "review_due" }
  ],
  "fallback": false,
  "review_due_caveat": false,
  "latency_ms": 1234,
  "correlation_id": "string"
}
```

Behaviour (Flow B):

- Permission context resolved from Entra ID (cached) before any retrieval.
- Hybrid retrieval: BM25 + vector kNN + Tourism Data Hub graph hop in parallel, RRF-fused, cross-encoder reranked, top-8 chunks handed to Azure OpenAI.
- Post-generation permission check re-verifies every cited source ID; forbidden citations trigger regeneration or refusal.
- `Review due` matches return with caveat; `Outdated`/`Archived`-only matches return a refusal.
- Azure OpenAI outage → `fallback: true` with top-3 reranked sources and their pre-computed long summaries.
- Latency budget: retrieval ≤ 2 s, rerank ≤ 500 ms, AOAI ≤ 5 s, post-check ≤ 200 ms; p95 end-to-end ≤ 8 s.

Side effects: writes `bot.answered` (or `bot.fallback`) to the action log; writes `{ user, query_text, answer_text }` to the read log (90-day TTL).

### 2.3 Subscriptions and notifications

#### GET /api/v1/me/subscriptions

List the caller's topic subscriptions and per-topic frequency preference (`Instant` | `SeveralPerDay` | `Daily` | `Weekly`).

#### PUT /api/v1/me/subscriptions

Replace the caller's subscription set. Subject to the per-user rate-limit: any bulk operation projected to generate more than 50 notifications to a single user is collapsed to a single digest regardless of `Instant` preference (proposal §6.8).

#### GET /api/v1/me/notifications

Paged feed of in-platform notifications for the caller. `?since=` cursor pagination.

### 2.4 Lifecycle

#### POST /api/v1/content/{content_id}:confirm-validity

Content Owner action during `Review due`. Extends `validity_until` by the content-type default. Audit event `lifecycle.action` with sub-type `confirmed`.

#### POST /api/v1/content/{content_id}:submit-new-version

Content Owner action during `Review due`. Appends a new version to `version_history`; previous version remains accessible via the Versions tab. Audit event `lifecycle.action` with sub-type `new_version`.

### 2.5 Admin

All endpoints under `/api/v1/admin/*` require membership in `KM-Administrator`.

| Method + Path | Purpose |
| --- | --- |
| `GET /api/v1/admin/sources` | List configured ingestion sources (SharePoint sites, Teams channels, mailboxes, data-hub connection) |
| `POST /api/v1/admin/sources` | Add a source. Mailbox sources require an attached DPO sign-off reference (ADR-0007) |
| `DELETE /api/v1/admin/sources/{id}` | Remove a source. Already-ingested content is retained; no further updates flow |
| `GET /api/v1/admin/lifecycle-policy` | Read per-content-type validity defaults and 14/30/60-day escalation thresholds |
| `PUT /api/v1/admin/lifecycle-policy` | Replace lifecycle policy. Takes effect on the next nightly run |
| `GET /api/v1/admin/audit?tab=action\|read` | Paged audit log viewer. Action log spans 7 years; read log spans 90 days |
| `GET /api/v1/admin/health` | System health: queue depths, fallback rate, post-check rejection rate, hallucination-sample results |

## 3. Webhook receivers (inbound)

The ingestion engine exposes Azure Function endpoints that receive Microsoft Graph change notifications. These are not user-facing and are not part of the public API contract; they validate Graph's `clientState` token and reject anything else.

| Receiver | Source |
| --- | --- |
| `/webhooks/graph/sharepoint` | Microsoft Graph subscription on a configured SharePoint site |
| `/webhooks/graph/teams` | Graph subscription on a Teams channel |
| `/webhooks/graph/mailbox` | Graph subscription on an opted-in shared/functional mailbox |
| `/webhooks/defender/scan` | Azure Defender for Storage scan-outcome callback |

## 4. Adapter contracts (internal)

### 4.1 DataHubAdapter

Read-only adapter against the Tourism Data Hub. No data is copied into Knowledge Manager storage; results are returned to the request thread and dropped (ADR-0003).

```
DataHubAdapter
  lookup_pois(filters: PoiFilters) -> PoiList
  lookup_bwc_partners(filters: PartnerFilters) -> PartnerList
  lookup_stakeholder_contacts(filters: ContactFilters) -> ContactList
```

Transport: read-only Cypher (or Gremlin) over private peering / VPN with a service account scoped to read. Every invocation writes an action-log row recording who queried, which lookup, returning how many records — but never the records themselves.

### 4.2 Ingestion source adapters

Each adapter normalises a source to the canonical `ContentItem` record.

| Adapter | Input | Notes |
| --- | --- | --- |
| `ManualUploadAdapter` | multipart from `/api/v1/content` | Path: virus scan → extraction → AI chain |
| `SharePointAdapter` | Graph delta + change notifications | One subscription per configured site; throttling-aware backoff |
| `TeamsAdapter` | Graph subscriptions on channel messages and files | Personal chats excluded by policy |
| `MailboxAdapter` | Graph subscriptions on an opt-in mailbox | Default disabled. Drafts, calendar, contacts excluded. BCC stripped pre-AI |
| `DataHubAdapter` | Cypher/Gremlin (see 4.1) | No copy; queried on demand |

## 5. AI processing chain (Service Bus events)

Each step is an idempotent worker keyed by `content_id`. Re-delivered messages are no-ops if the worker's output already exists in PostgreSQL.

| Topic | Producer | Consumer | Payload |
| --- | --- | --- | --- |
| `scan.clean` / `scan.infected` | Defender for Storage | Extraction worker / dead-letter | `{ content_id, blob_ref, outcome }` |
| `extract` | Scan handler | Extraction worker | `{ content_id }` |
| `sanitise` | Extraction worker | Sanitisation worker | `{ content_id }` |
| `language-detect` | Sanitisation worker | Language worker | `{ content_id }` |
| `chunk` | Language worker | Chunker | `{ content_id, language }` |
| `embed` | Chunker | Embedding worker (calls Azure OpenAI) | `{ content_id, chunk_ids[] }` |
| `tag` | Embedding worker | Tagging worker (calls Azure OpenAI) | `{ content_id }` |
| `summarise` | Tagging worker | Summary worker | `{ content_id }` |
| `dedupe` | Summary worker | Duplicate detector | `{ content_id, mean_embedding }` |
| `injection-flag` | Dedupe | Injection classifier | `{ content_id }` |
| `approve` | Injection classifier | Approver queue | `{ content_id, flags[] }` |
| `push-fan-out` | Approver action | Push matcher | `{ content_id }` |

Retry policy: exponential backoff, three attempts, then dead-letter queue surfaced in the Admin Console.

## 6. Permission decision

Evaluated server-side at retrieval time and rendered as an Azure AI Search `filter` clause. Never exposed as a callable API; documented here because every retrieval response depends on it.

```
permitted(item, user) =
  user.clearance_max_level >= item.confidentiality_level
  AND (
    item.confidentiality_level in {public, internal}
    OR user.member_of_groups intersects item.responsible_unit_group
    OR user.member_of_groups intersects item.additional_access_groups
  )
```

Inputs come from Entra ID via the session-scoped cache. `confidentiality_level` ∈ `{ public, internal, confidential, strictly_confidential }`.

## 7. Push delivery channels

Outbound, not callable by clients. The push matcher selects one channel per match per recipient:

| Channel | Transport | Notes |
| --- | --- | --- |
| Email digest | Microsoft Graph `sendMail` from the KM service mailbox | HTML + plain-text alternative; unsubscribe and frequency-edit links |
| Teams adaptive card | Graph proactive messaging | Per-user opt-in; honours quiet hours |
| In-platform notification | SPA notification centre | Available via `GET /api/v1/me/notifications` |

Bulk operations projected to exceed 50 notifications to a single user are collapsed to a single digest regardless of `Instant` preference (proposal §6.8). Items in `Review due`, `Outdated`, or `Archived` are never pushed.

## 8. Lifecycle worker (scheduled)

Not a request/response interface; runs nightly under Azure Service Bus + a scheduled trigger. Logic (from `architecture.md` §3.4):

```
nightly_lifecycle_scan():
  Current items with validity_until < today          -> Review due  + notify owner
  Review due aged >= 14d, not yet reminded           -> reminder    + mark reminded
  Review due aged >= 30d, not yet escalated          -> escalate    + mark escalated
  Review due aged >= 60d                             -> Outdated    + flag admin
```

Thresholds are per-content-type and configurable via `PUT /api/v1/admin/lifecycle-policy`.

## 9. Audit interfaces

Two append-only tables behind `GET /api/v1/admin/audit`.

| Tier | Retention | Fields recorded |
| --- | --- | --- |
| Action log | 7 years, immutable, monthly archive to object-locked blob | actor, action, content_id, permission_filter_hash, cited_source_ids, latency, outcome — but never query text, answer text, or document content |
| Read log | 90 days, daily TTL job | actor, timestamp, query_text, answer_text, cited_source_ids |

This split is the mechanism that resolves the concept's no-copy data-hub principle against operational auditability (ADR-0004, proposal §6.3).

## 10. Non-goals

The following are explicitly not part of the public API:

- Direct role assignment. Roles live in Entra ID; the SPA links out to the appropriate Entra portal but never writes group memberships.
- Direct write-back to SharePoint, Teams, or mailboxes. Ingestion is one-way.
- Bulk export of the Tourism Data Hub. Hub data is fetched per request and not persisted.
- Generic embedding access or model inference. Azure OpenAI is reached only through the retrieval engine, never as a passthrough.
