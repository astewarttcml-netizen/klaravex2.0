# GDPR Art. 28 sub-processor map and lawful-basis register
### visitBerlin Knowledge Manager — by Klaravex GmbH

**Companion to:** `dpia.md`, `nis2.md`, `bsi-c5.md`, `data-residency.md`
**Date:** 2026-06-27

---

## 1. Roles

| GDPR role | Entity | Notes |
| --- | --- | --- |
| Controller | Berlin Tourismus & Kongress GmbH (visitBerlin) | Determines purposes and means of processing. State-owned entity under Berlin Land oversight. |
| Processor | Klaravex GmbH | Processes personal data on documented instructions of the controller per Art. 28(3) DPA. |
| Sub-processor | Microsoft Ireland Operations Ltd (Azure, Microsoft 365) | EU establishment. Microsoft EU Data Boundary commitments apply. |
| Sub-processor | Microsoft Ireland Operations Ltd (Azure OpenAI Service) | Same legal entity; separate service contract under the Azure OpenAI Service terms. |

There are no further sub-processors. Klaravex does not subcontract operations of this system to any other party. If this changes, a sub-processor change notification per Art. 28(2) GDPR is sent to the visitBerlin DPO with no less than 30 days lead time and a right to object.

---

## 2. Sub-processor table

| Sub-processor | Service | Processing purpose | Location | EU Data Boundary | DPA reference |
| --- | --- | --- | --- | --- | --- |
| Microsoft Ireland Operations Ltd | Azure (PostgreSQL Flex, AI Search, Blob, Service Bus, App Service, Front Door, Key Vault, Monitor) | Hosting, storage, networking, telemetry | Germany-West-Central (primary), Germany-North (DR) | Yes — within EUDB scope | Microsoft Online Services DPA + Product Terms |
| Microsoft Ireland Operations Ltd | Azure OpenAI Service | LLM inference, embedding generation | France-Central (primary), Sweden-Central (failover) | Yes — within EUDB scope for the in-EEA processing path | Microsoft Online Services DPA + Azure OpenAI Service-specific terms |
| Microsoft Ireland Operations Ltd | Microsoft 365 (Graph API for SharePoint, Teams, Mail) | Source-system ingestion | Microsoft EU Data Boundary | Yes | Microsoft Online Services DPA |
| Microsoft Ireland Operations Ltd | Microsoft Entra ID | Identity, authentication, role membership | Microsoft EU Data Boundary | Yes | Microsoft Online Services DPA |

No US-based sub-processors are in the data path in normal operation. Microsoft's published EU Data Boundary commitments cover residual edge cases (limited support-engineering data crossing borders for diagnostic purposes); these are addressed in `data-residency.md` and in the DPIA.

---

## 3. Lawful-basis register (Art. 30 ROPA preview)

### 3.1 Processing of employee personal data

| Activity | Categories | Lawful basis | Notes |
| --- | --- | --- | --- |
| Authentication, session management | Employee identifier, group memberships | Art. 6(1)(b) (contract) + §26(1) BDSG (employment context) | Standard Entra ID-based authentication. |
| Profile sync from Entra ID | Name, email, department, role, manager, location, languages | Art. 6(1)(b) (contract) + §26(1) BDSG | Read from Entra ID; the visitBerlin tenant is the system of record. |
| Profile overlay (focus areas, subscribed topics, notification preferences) | User-edited overlay fields | Art. 6(1)(a) (consent) | Overlay is optional. Default values are minimal. |
| Telemetry of bot usage | Query timestamps, source IDs cited, latency | Art. 6(1)(f) (legitimate interest — system operation) + §26(1) BDSG | Aggregated for system observability; no per-user dashboards. Subject to works council co-determination. |
| Audit log (action log, 7 yr) | Who did what, when, against which content_id | Art. 6(1)(c) (legal obligation — accountability under Art. 5(2)) + BSI C5 evidence | Required to demonstrate compliance. |
| Read log (query + answer text, 90 days) | Bot conversation content | Art. 6(1)(f) — operational support + abuse investigation | 90-day TTL is the data-minimisation justification. |
| Content authorship attribution | Author identifier on each content item | Art. 6(1)(b) (contract) | Standard editorial attribution. |

### 3.2 Processing of personal data appearing in content

| Activity | Categories | Lawful basis | Notes |
| --- | --- | --- | --- |
| AI summarisation, tagging | Whatever PII appears incidentally in documents | Art. 6(1)(f) (legitimate interest — knowledge management) | Balanced against data-subject rights; balanced against the alternative (manual handling produces the same exposure, just distributed). |
| Bot answers surfacing content PII | Whatever PII appears in cited sources | Art. 6(1)(f) | Permission filter at retrieval is the primary control. |
| Storage of original documents | Document contents as uploaded | Art. 6(1)(f) | Confidentiality classification at Approver step is the editorial control. |

### 3.3 Processing of Tourism Data Hub PII (read-only)

| Activity | Categories | Lawful basis | Notes |
| --- | --- | --- | --- |
| Read-only queries to the data hub | Stakeholder name, email, phone, role at partner | Art. 6(1)(f) (legitimate interest — business communications) | Already the controller's pre-existing processing through the hub. The Knowledge Manager surfaces it through a new channel without copying. |
| Inclusion of hub data in bot answers | Same | Art. 6(1)(f) | Inherits the controller's existing legitimate-interest balancing for the hub. |

### 3.4 Processing of mailbox content (opt-in only)

If and only if a mailbox is opted in per ADR-0007:

| Activity | Categories | Lawful basis | Notes |
| --- | --- | --- | --- |
| Ingestion of functional-mailbox content | Sender, recipient (To, Cc — BCC stripped), subject, body, attachments | Art. 6(1)(f) (legitimate interest — knowledge management) **per mailbox**, with DPO sign-off | Lawful basis decided *per mailbox*, not as a blanket policy. Justification text recorded at opt-in. |
| Processing of external-sender content | Same | Art. 6(1)(f) — with explicit allowlist | Default-deny on external senders. |

Personal mailboxes are not eligible — blocked at the Admin Console level.

### 3.5 Processing of works-council-sensitive data

Per BetrVG §87(1) nos. 6 and 7, the introduction of a system capable of monitoring employee behaviour is subject to co-determination. The Knowledge Manager is in scope because the action log records per-user behavioural events. Klaravex commits to:

- Pre-go-live briefing of the works council on what the action log records and does *not* record.
- Written undertaking that the action log is not used as input to performance management or HR processes.
- Annual review with the works council on the metrics published from the system.

---

## 4. International transfers (Chapter V GDPR)

### 4.1 Posture
The Knowledge Manager does not, in normal operation, transfer personal data outside the EEA. All processing is in-EEA: Germany-West-Central (primary), Germany-North (DR), Sweden-Central and France-Central (Azure OpenAI).

### 4.2 Transfer impact assessment (Schrems II reasoning)
The relevant transfer risk is not a chapter-V transfer but the residual edge cases of Microsoft's EU Data Boundary commitments. Microsoft has publicly documented that limited engineering-support data may cross borders to enable diagnostic investigations. Klaravex's position:

- This is not a routine transfer for processing purposes; it is an exceptional support-data transfer.
- It is governed by the Microsoft Online Services DPA, which includes Standard Contractual Clauses (2021/914) where transfers occur.
- The categories of data potentially crossing in this manner are diagnostic metadata, not customer content; this is consistent with Microsoft's published commitments.
- The visitBerlin DPO is notified of any actual incident involving a cross-border data flow within 24 hours, per the Klaravex processor agreement.

We rely on the Microsoft Online Services DPA and the EU Data Boundary commitment, with the SCCs as supplementary measure for any residual edge case.

### 4.3 Adequacy
No third-country adequacy decision is being relied upon. Microsoft's EU entity acts as the contracting sub-processor.

---

## 5. Data subject rights mechanics

GDPR Art. 12–22 rights apply. The controller (visitBerlin) is responsible for fulfilling them; Klaravex as processor provides the mechanisms.

| Right | Klaravex support |
| --- | --- |
| Information (Art. 13, 14) | Klaravex provides the privacy-notice text covering processing in the Knowledge Manager; visitBerlin publishes. |
| Access (Art. 15) | Export of user-related data: profile, subscriptions, action-log entries about them, read-log entries (within retention), authored content. Triggered via DPO ticket; SLA 30 days. |
| Rectification (Art. 16) | Profile overlay fields user-editable. Entra-sourced fields rectified via Entra ID. |
| Erasure (Art. 17) | On leaving visitBerlin: Entra ID disablement triggers a 30-day grace, then automated purge of overlay, subscriptions, read-log entries about the user, and pseudonymisation of action-log entries (replacing identifier with hash). Authored content remains for the configured retention; ownership transferred per leaver process. |
| Restriction (Art. 18) | Per-user processing restriction toggle in Admin Console, controlled by DPO. Restricted users' telemetry not processed; only access is logged. |
| Portability (Art. 20) | Profile + overlay export as JSON; authored content already in the source M365 system. |
| Objection (Art. 21) | Per the Art. 6(1)(f) balancing, the controller weighs the objection. Klaravex provides the technical means to restrict the user's processing if accepted. |
| Automated decision-making (Art. 22) | No automated decision-making with legal or similarly significant effects. Bot answers are advisory and explicit; content matching does not affect employment. |

---

## 6. Records of processing activities (Art. 30) — populated template

### Controller's ROPA (visitBerlin)

| Field | Value |
| --- | --- |
| Activity name | visitBerlin Knowledge Manager — internal knowledge platform |
| Purpose | Centralised knowledge management with AI-supported tagging, matching, and Q&A |
| Categories of data subjects | Employees, external stakeholders (via Tourism Data Hub), incidental third parties in content |
| Categories of personal data | Identity, employment context, behavioural usage, business communications, incidental content PII |
| Recipients | Employees per permission model; DPO, Klaravex support per processor agreement; Microsoft as sub-processor |
| Transfers outside EEA | None in normal operation; Microsoft EU Data Boundary edge cases per `data-residency.md` |
| Retention | Per `dpia.md` §1.6 |
| Security measures | Per `bsi-c5.md` (technical and organisational measures) |

### Processor's ROPA (Klaravex)

Maintained by Klaravex per Art. 30(2), available on request to the visitBerlin DPO and supervisory authority.

---

## 7. Breach notification process and timeline

Per Art. 33 GDPR and the Klaravex processor agreement:

| Step | Owner | Timeline |
| --- | --- | --- |
| Detection | Klaravex SOC (Azure Monitor + Microsoft Defender for Cloud alerts) | t = 0 |
| Initial classification (is this a personal-data breach?) | Klaravex DPO + IT lead | within 4 h |
| Notification to visitBerlin DPO | Klaravex DPO | within 24 h (faster than the 72 h regulatory ceiling, by contract) |
| Joint investigation | Both DPOs + technical leads | ongoing |
| Notification to supervisory authority (if required) | visitBerlin DPO | within 72 h of awareness, per Art. 33(1) |
| Notification to data subjects (if Art. 34 triggered) | visitBerlin | without undue delay |
| Final incident report | Joint | within 30 days |

Klaravex maintains a breach-notification runbook; current version in the SoW annex.

---

## 8. Document control

- This dossier is reviewed annually and on material change (new sub-processor, new sub-processor location, new processing activity, new model in the bot pipeline).
- Reviewer: Klaravex DPO + visitBerlin DPO joint sign-off.

---

*End of GDPR dossier.*
