# Data Protection Impact Assessment — outline
### visitBerlin Knowledge Manager — by Klaravex GmbH

**Status:** Outline for joint completion with the visitBerlin DPO
**Companion to:** `gdpr-dossier.md`, `nis2.md`, `bsi-c5.md`, `data-residency.md`, `../proposal/proposal.md`, `../architecture/architecture.md`
**Template basis:** EDPB DPIA template + DSK (Datenschutzkonferenz) short DPIA recommendation
**Date:** 2026-06-27

> This is a structured DPIA outline. It identifies every processing activity, the risks to data subjects, and the mitigating measures Klaravex and visitBerlin will implement. The final DPIA is to be **completed jointly with the visitBerlin DPO during proposal phase 1 (weeks 3–4)** and signed off before any production data is ingested (proposal phase 2, weeks 5–12). No production ingestion begins without DPIA sign-off.

---

## 1. Description of the processing (GDPR Art. 35(7)(a))

### 1.1 What is processed
The Knowledge Manager is a centralised, AI-supported knowledge platform for visitBerlin employees. It processes:

| Personal data category | Source | Lawful basis (preview — full register in `gdpr-dossier.md`) |
| --- | --- | --- |
| Employee identity and org-chart data (name, email, department, role, manager) | Microsoft Entra ID | Art. 6(1)(b) (contract) + Art. 88 BDSG / §26 BDSG (employment) |
| Employee profile overlay (focus areas, subscribed topics, notification preferences) | User-edited in the platform | Art. 6(1)(a) (consent) for non-mandatory fields |
| Employee usage data (queries to the bot, items read, items uploaded) | System telemetry | Art. 6(1)(f) (legitimate interest — operation) + works council co-determination |
| Content of uploaded documents (incidentally containing PII of colleagues, partners, citizens) | M365 ingestion + manual upload | Mixed; depends on source (see §3 below) |
| Stakeholder PII (name, email, phone, role at partner) | Tourism Data Hub, queried read-only | Art. 6(1)(f) (legitimate interest — business communications) |
| Mailbox contents (sender, recipients, subject, body, attachments) | Exchange Online — **opt-in only**, default disabled | Conditional on DPO sign-off per mailbox; lawful basis decided per mailbox |
| Bot conversation logs (query + answer text) | System telemetry | Art. 6(1)(f) — short retention (90 days) |
| Audit log (who-did-what events, content IDs cited, permission filter applied) | System telemetry | Art. 6(1)(c) (legal obligation — accountability under GDPR Art. 5(2)) + BSI C5 |

### 1.2 Purpose
- Central, searchable knowledge base.
- Automated processing (tagging, summarising, matching) to reduce manual handling.
- AI-supported question answering with mandatory source citation.
- Lifecycle management of content (validity, re-submission, archive).
- Audit-proof accountability of access and changes.

### 1.3 Scope
- ~300–600 employees (visitBerlin headcount baseline; pilot in one department, ~30–50 users).
- Inside visitBerlin's M365 tenant.
- Inside Azure Germany-West-Central (data at rest).
- Azure OpenAI in Sweden-Central or France-Central (in-EEA processing; see ADR-0005 and `data-residency.md`).

### 1.4 Data flows
- See `../architecture/data-flow.md` for the three narrative flows (upload, bot answer, lifecycle re-submission).
- See `../architecture/architecture.md` §2 for the system context diagram.

### 1.5 Recipients
- visitBerlin employees, scoped by the permission model (concept §4 / `architecture.md` §5).
- Klaravex operations team for support, under written processor agreement, with named individuals listed in the SoW annex.
- Microsoft as sub-processor for hosting and Azure OpenAI inference; no human Microsoft access to customer data in normal operation.

### 1.6 Retention
- Content originals: as long as content is in `Current`, `Review due`, `Outdated`, or `Archived` status, per lifecycle policy in `architecture.md` §3.4. Archive deletion via Administrator action.
- Action log: 7 years (BSI C5 evidence + accountability).
- Read log: 90 days (auto-TTL).
- User profile overlay: until the user leaves visitBerlin + 30 days (Entra ID disablement + 30-day grace).
- Embeddings and AI metadata: tied to the content item lifecycle.

### 1.7 International transfers
- Not in normal operation. All data stays in the EEA.
- Microsoft EU Data Boundary covers the residual edge cases. Detailed in `gdpr-dossier.md`.

---

## 2. Necessity and proportionality assessment (Art. 35(7)(b))

### 2.1 Necessity
The concept §1.1 describes the operational pain — knowledge fragmentation across mailboxes, chats, and minds. The Knowledge Manager addresses this by centralising and automating. No less-invasive alternative achieves the operational goal at this scale:

- Manual taxonomy maintenance: fails at concept's scale; produces stale, abandoned wikis.
- Search-only (no AI): fails on concept §3.5 — natural-language bot is a stated requirement.
- Off-the-shelf SaaS without sovereign hosting: fails on data residency for a state-owned company.

### 2.2 Proportionality
- **Permission filter at retrieval (ADR-0002)**: the LLM never sees content the user is not permitted to read. The system is *not* a centralised mass-read on confidential content; it is a permission-scoped read.
- **No copy of the Tourism Data Hub (ADR-0003)**: structured PII is queried on demand, not duplicated.
- **Mailbox connector default off (ADR-0007)**: the highest-risk source defaults to disabled.
- **Two-tier audit log (ADR-0004)**: action log retains accountability metadata long-term, but content (PII) is purged at 90 days from the read log.

### 2.3 Data minimisation by design
- Profile fields are read from Entra ID (single source of truth); overlay fields are user-edited and optional.
- Mailbox connector filters (drafts/calendar/contacts/BCC/external senders excluded) limit ingestion to functionally necessary content.
- AI processing chain stores summaries and embeddings; the original text is retained because the bot must cite verifiable sources; no derivative profiling of employees is performed.

---

## 3. Risk assessment — per processing activity (Art. 35(7)(c))

For each activity: identified risks to data subjects' rights and freedoms, plus the mitigating measures (Art. 35(7)(d)). Residual risk is rated *low / medium / high*; the threshold for go-live is *low or medium with a documented mitigation plan*.

### 3.1 M365 SharePoint ingestion
**Risk:** SharePoint sites contain documents written by colleagues, partners, and citizens. PII appears incidentally (names, emails in document text). Indexing creates a centralised, searchable copy.

**Mitigations:**
- Per-site inclusion list — Administrators choose which sites are ingested; sites containing HR / payroll / contractual confidential data are excluded unless explicitly opted in.
- Permission filter at retrieval — only content the requesting user could already read in SharePoint is retrievable in the Knowledge Manager.
- Confidentiality-level assignment at Approval — every item is classified before publication.

**Residual risk:** **Low** if the per-site exclusion is honoured and the works council briefed.

### 3.2 M365 Teams ingestion
**Risk:** Channel content includes free-form conversations; PII routinely appears.

**Mitigations:**
- Per-channel inclusion list (default: nothing ingested).
- Personal chats excluded by design.
- Approver review with confidentiality-level assignment.

**Residual risk:** **Low** with channel-level governance discipline.

### 3.3 Mailbox connector (opt-in only)
**Risk:** Mailboxes carry external correspondents' PII, BCC recipients, sensitive subjects.

**Mitigations:**
- Default disabled (ADR-0007).
- Personal mailboxes blocked.
- Functional mailboxes only, after DPO sign-off, with justification text recorded.
- BCC stripped, drafts/calendar/contacts excluded, external-sender allowlist enforced.

**Residual risk:** **Medium**, contingent on DPO sign-off procedure being honoured. Go-live without DPO sign-off → block by design.

### 3.4 Tourism Data Hub PII queries
**Risk:** Stakeholder contact data is PII (name, email, phone). Bot answers will surface this data into chats and the read log.

**Mitigations:**
- Read-only adapter (ADR-0003); no copy.
- Read-log retention 90 days (ADR-0004).
- Permission filter at retrieval applies to hub records too — only users with appropriate clearance can trigger hub hops returning PII.
- Hub records labelled as such in the bot's source-citation panel; the user is visibly aware they are looking at PII.

**Residual risk:** **Medium**. The DPIA argument is: this is the same data visitBerlin already processes through the data hub; the Knowledge Manager surfaces it through a different channel with shorter retention and the same permission model.

### 3.5 Bot answer logging (read log, 90 days)
**Risk:** Free-text answers contain whatever PII the cited sources contained.

**Mitigations:**
- 90-day automatic TTL (ADR-0004).
- Access to the read log restricted to Administrators + the DPO (Entra ID PIM-protected role).
- Read-log access events are themselves recorded in the action log (auditor-auditing-the-auditor pattern).

**Residual risk:** **Low** given the short retention.

### 3.6 Audit log (action log, 7 years)
**Risk:** Action log records user identifiers and behavioural patterns (which content the user accessed, which queries the user made). Could be misused for employee monitoring.

**Mitigations:**
- Action log read access is itself logged.
- Works council briefing on what the action log records and what it does *not* record.
- Klaravex contractually prohibited from accessing the action log except for stated support purposes.
- No content text in the action log (only IDs).

**Residual risk:** **Low**, contingent on works council co-determination per §26 BDSG.

### 3.7 AI summarisation and tagging
**Risk:** The LLM processes document text, which contains PII. Inference is in Azure OpenAI in Sweden-Central / France-Central.

**Mitigations:**
- In-EEA processing under the Microsoft EU Data Boundary commitment.
- Azure OpenAI's content-filtering policies for abuse monitoring run in-region.
- No training of public models on visitBerlin data (Azure OpenAI's commercial terms).

**Residual risk:** **Low**.

### 3.8 AI question answering (bot)
**Risk:** Combines §3.5 and §3.7 risks. Plus the risk of hallucination producing factually false statements about real people.

**Mitigations:**
- Mandatory source citation; no claim is presented without a source pointer.
- Hallucination-rate target <2 % with weekly sampling (proposal §6.9).
- Feedback channel ("incorrect" flag) feeds into source quality review.

**Residual risk:** **Medium**, the hallucination dimension. Acceptable with the monitoring regime.

### 3.9 Employee usage telemetry
**Risk:** Patterns of bot use and document access could be misused for behavioural profiling of employees.

**Mitigations:**
- Telemetry is aggregated for system observability (not per-user dashboards).
- Per-user usage views are not built; if requested in v2, they require a fresh DPIA delta.
- Works council co-determination on the metrics that are published.

**Residual risk:** **Low**, contingent on no per-user dashboards.

### 3.10 Cross-cutting: prompt injection from hostile uploads
**Risk:** A hostile or compromised Author embeds adversarial text in a document, causing the bot to exfiltrate confidential content from other documents in the retrieval context to users who should not see them. Not a GDPR-language risk strictly but a data-subject-rights risk all the same (information about data subjects leaking to unauthorised recipients).

**Mitigations:**
- Pre-ingestion sanitisation (invisible text stripped).
- Instruction-pattern classifier flags suspicious documents for Approver review (proposal §6.2 control 2).
- Permission filter at retrieval limits blast radius (LLM cannot exfiltrate content it does not see — ADR-0002).
- Post-generation permission check (defence in depth).

**Residual risk:** **Low** with the layered controls.

---

## 4. Mitigating measures summary (Art. 35(7)(d))

| Control | Mitigates | Reference |
| --- | --- | --- |
| Permission filter at retrieval | §3.1, §3.2, §3.4, §3.10 | ADR-0002, `architecture.md` §3.3 |
| No-copy data hub | §3.4 | ADR-0003 |
| Two-tier audit log | §3.5, §3.6 | ADR-0004, proposal §6.3 |
| Mailbox opt-in only | §3.3 | ADR-0007, proposal §6.7 |
| Sanitisation + injection-flag classifier | §3.10 | proposal §6.2, `architecture.md` §3.2 |
| Azure OpenAI in EEA, no US services | §3.7, §3.8 | ADR-0005, `data-residency.md` |
| Hallucination sampling regime | §3.8 | proposal §6.9 |
| Works council briefing | §3.6, §3.9 | DPIA process step, this document |
| Bulk-upload notification cap | n/a directly; operational risk reduction | proposal §6.8 |
| DPO sign-off gates for mailbox opt-in | §3.3 | ADR-0007 |

---

## 5. Residual risk assessment

After all mitigations:

| Activity | Residual risk | Acceptable for go-live? |
| --- | --- | --- |
| SharePoint ingestion | Low | Yes, with per-site inclusion governance |
| Teams ingestion | Low | Yes, with per-channel inclusion governance |
| Mailbox connector | Medium | Yes, only after per-mailbox DPO sign-off |
| Data Hub PII queries | Medium | Yes, with the no-copy + permission-filter architecture |
| Read log | Low | Yes |
| Action log | Low | Yes, after works council briefing |
| AI summarisation | Low | Yes |
| Bot answering | Medium (hallucination dimension) | Yes, with monitoring regime |
| Usage telemetry | Low | Yes, with no-per-user-dashboard commitment |
| Prompt injection | Low | Yes, with layered controls |

No residual high risk identified. Therefore prior consultation with the supervisory authority (Berliner Beauftragte für Datenschutz und Informationsfreiheit) per GDPR Art. 36 is **not** triggered. If during joint DPIA completion the visitBerlin DPO disagrees, the consultation process is initiated before go-live.

---

## 6. DPO consultation plan

| Milestone | Activity | Deliverable |
| --- | --- | --- |
| Proposal phase 1, week 3 | DPO kickoff workshop | Confirm scope, identify additional risks not in this outline |
| Phase 1, week 4 | Works council briefing — Klaravex + DPO + product owner | Co-determination engagement per §26 BDSG, BetrVG §87 |
| Phase 2, week 6 | Per-mailbox opt-in workshop (if any) | DPO sign-off form template |
| Phase 2, week 8 | DPIA draft 1 review | Internal review against this outline |
| Phase 2, week 10 | DPIA final | Signed and filed |
| Phase 2, week 12 | Go-live readiness review | Go / no-go on production data ingestion |
| Phase 3, week 16 | Operational review during pilot | Adjust controls based on real telemetry |
| Phase 4, week 24 | DPIA delta review before rollout | Confirm no new risks at full scale |
| Phase 5+ | Annual DPIA refresh | Standard process |

---

## 7. Go-live sign-off criteria

The following must all be true before production data is ingested:

1. DPIA is signed by the visitBerlin DPO and the Klaravex DPO.
2. Works council has been briefed and any co-determination resolution is in place.
3. Per-site / per-channel / per-mailbox inclusion lists are configured and DPO-signed.
4. Permission-filter mechanism has been independently verified (penetration test by an external firm, scoped to permission leak in RAG).
5. Audit-log retention is set to the agreed values.
6. Klaravex processor agreement and Microsoft sub-processor chain are signed.
7. Hallucination-rate baseline measurement is documented from the pilot.
8. Klaravex on-call rotation is staffed and a DR drill has been executed in staging.

---

## 8. References

- GDPR (Regulation (EU) 2016/679), particularly Art. 5, 6, 25, 28, 30, 32, 33, 35, 88.
- BDSG (Bundesdatenschutzgesetz), particularly §26 (employee data).
- BetrVG (Betriebsverfassungsgesetz), particularly §87(1) nos. 6, 7 (co-determination on monitoring and software).
- DSK short DPIA template (Datenschutzkonferenz).
- EDPB DPIA guideline (WP248 rev.01).
- BSI C5:2020 (companion document).

---

*End of DPIA outline.*
