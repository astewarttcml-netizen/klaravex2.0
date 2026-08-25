# BSI C5:2020 control mapping
### visitBerlin Knowledge Manager — by Klaravex GmbH

**Companion to:** `dpia.md`, `gdpr-dossier.md`, `nis2.md`, `data-residency.md`
**Date:** 2026-06-27

> **C5 attestation roadmap:** Klaravex commits to BSI C5 Type 2 attestation as the operator of the Knowledge Manager within 24 months of go-live (proposal §4.9). This document is the control mapping that will form the basis of that attestation engagement. Until Type 2 is achieved, the operating posture is "C5-aligned" — controls implemented and evidence maintained, without independent attestation.

C5 catalogue version: **C5:2020** (BSI Cloud Computing Compliance Criteria Catalogue, current as of 2026).

---

## 1. How to read this document

For each of the 17 C5 control domains, this document states:

- **Objective** — what the domain is for.
- **Implementation** — how the Knowledge Manager / Klaravex / Azure stack implements it.
- **Evidence** — the artefact that demonstrates the control is in place.
- **Notes** — material caveats.

Where a C5 control overlaps with an ISO 27001:2022 Annex A control, the reference is given. Where a C5 control overlaps with a BSI Grundschutz building block, the reference is given.

---

## 2. OIS — Organisation of Information Security

**Objective:** Ensure information security is governed organisationally.

**Implementation:**
- Klaravex operates an ISMS aligned to ISO 27001:2022 (Annex A.5).
- Documented information-security policy approved by Klaravex management.
- Defined ISMS roles: CISO, DPO, system owner per service, on-call rotation.
- Annual risk assessment covering all Klaravex-operated services including the visitBerlin Knowledge Manager.
- Annual management review.

**Evidence:** Klaravex ISMS document set, current ISO 27001 certificate, annual management-review minutes.

**Notes:** Maps to ISO 27001 A.5.1, A.5.2; BSI Grundschutz ISMS.1.

---

## 3. SP — Security Policies and Instructions

**Objective:** Documented, communicated, regularly reviewed security policies.

**Implementation:**
- Policy hierarchy: top-level Information Security Policy → topical policies (access control, cryptography, supplier management, incident response, secure development, change management, BCM, data protection, acceptable use).
- Policies reviewed annually and on material change.
- Communicated to all Klaravex personnel; mandatory acknowledgement on hire and annually.

**Evidence:** Policy register; acknowledgement records.

**Notes:** ISO 27001 A.5.10.

---

## 4. HR — Human Resources

**Objective:** Personnel with access to customer data are trustworthy and trained.

**Implementation:**
- Background checks (Führungszeugnis equivalent) on all Klaravex personnel with access to customer environments.
- Confidentiality agreements signed at hire.
- Mandatory security awareness training on hire and annually.
- Specific training for personnel handling customer data (GDPR, BSI C5 operating procedures, incident response).
- Documented leaver process: access revocation within 4 h of role change / termination.

**Evidence:** HR records; training completion records; access-review records on leaver actions.

**Notes:** ISO 27001 A.6.1, A.6.2, A.6.3, A.6.5.

---

## 5. AM — Asset Management

**Objective:** Assets known, owned, classified.

**Implementation:**
- Asset inventory maintained in Klaravex's CMDB. Knowledge Manager assets (Azure resources, code repositories, secrets) tagged with `customer:visitberlin` and `environment:{dev|staging|prod}`.
- Asset owner per asset.
- Classification scheme aligned to the customer's confidentiality model — Knowledge Manager content inherits the confidentiality_level attribute (concept §4.1, `architecture.md` §5).

**Evidence:** CMDB extract scoped to the visitBerlin engagement; asset-owner register.

**Notes:** ISO 27001 A.5.9, A.5.12.

---

## 6. PS — Physical Security

**Objective:** Physical access to assets controlled.

**Implementation:**
- All data-plane assets are in Microsoft datacentres (Germany-West-Central, Germany-North, Sweden-Central, France-Central).
- Microsoft datacentre physical security is the responsibility of Microsoft as sub-processor; covered by Microsoft's own C5 attestation (current).
- Klaravex offices: badged access, visitor log, no customer data on premises by policy.

**Evidence:** Microsoft C5 attestation (sub-processor evidence); Klaravex office physical-security policy.

**Notes:** ISO 27001 A.7.

---

## 7. RB — Operational Security (Regular Operation / Regulärer Betrieb)

**Objective:** Day-to-day operations executed securely.

**Implementation:**
- Documented operating procedures per service (deployment, monitoring, backup, restore).
- Change management: all changes via GitHub PR + Bicep `what-if` + governance-board approval for prod.
- Capacity management: Azure Monitor metrics; thresholds and alerts on growth indicators.
- Vulnerability management: dependency scanning in CI; OS patching via Azure-managed services (no customer-managed OS); container base-image updates on a 30-day cycle minimum.
- Logging and monitoring per the OBS domain below.

**Evidence:** Operating procedures register; change-management records; vulnerability-scan reports.

**Notes:** ISO 27001 A.8.6, A.8.7, A.8.8.

---

## 8. IDM — Identity Management

**Objective:** Identities managed across their lifecycle; authorisations granted on least-privilege basis.

**Implementation:**
- All identities (employees, Klaravex personnel) are managed in Microsoft Entra ID — visitBerlin's tenant for end users; Klaravex's tenant for operators.
- MFA enforced for all roles (conditional access policy).
- Privileged access via Entra ID PIM with just-in-time activation, approval workflow, and time bounds.
- Quarterly access reviews on all privileged role memberships.
- Role assignment in Klaravex follows least-privilege; the support role does not include data-read by default — that requires a separate, time-bound, customer-notified PIM activation.

**Evidence:** PIM activation logs; access-review records; conditional-access policy export.

**Notes:** ISO 27001 A.5.15, A.5.16, A.5.17, A.5.18, A.8.2, A.8.3, A.8.5.

---

## 9. CKM — Cryptography and Key Management

**Objective:** Cryptography appropriate; keys managed.

**Implementation:**
- Data in transit: TLS 1.3 enforced (Front Door minimum TLS policy, App Service minimum TLS policy).
- Data at rest: AES-256 via Azure Storage Service Encryption; Azure-managed keys by default; customer-managed keys (CMK) in Azure Key Vault available on request.
- Application secrets in Key Vault, never in source. CI/CD authenticated via federated credentials.
- Key rotation: managed keys rotated per Microsoft policy; CMK rotation on the customer's policy (default annual).

**Evidence:** Azure policy assignments (e.g. "Storage accounts should require infrastructure encryption"); Key Vault audit log.

**Notes:** ISO 27001 A.8.24.

---

## 10. COS — Communications Security

**Objective:** Network communications protected.

**Implementation:**
- All data-plane services exposed only via private endpoints in VNet (`architecture.md` §9).
- Public ingress only through Azure Front Door (Premium) with WAF (OWASP Core Rule Set).
- Egress to Microsoft 365 Graph: via Front Door NAT pool (static IPs for tenant CAS lists).
- Egress to Azure OpenAI: private endpoint over Microsoft backbone.
- Data Hub link: private peering or site-to-site VPN, no public Internet path.

**Evidence:** Network architecture diagram (`architecture.md` §2); NSG / WAF policy exports.

**Notes:** ISO 27001 A.8.20, A.8.21, A.8.23.

---

## 11. KOS — Portability and Interoperability

**Objective:** Customer can extract data and migrate.

**Implementation:**
- All customer content stored in canonical formats: documents in original blob storage (unchanged); metadata in PostgreSQL (standard SQL); audit logs in PostgreSQL.
- Export tooling: customer-triggered export of metadata + content as a single archive (Apache Parquet for tabular, original files for documents).
- No proprietary lock-in; the source content lives in the customer's M365 tenant.

**Evidence:** Export-tool documentation; sample export.

**Notes:** ISO 27001 A.5.30 (ICT readiness for business continuity overlaps).

---

## 12. BCM — Business Continuity Management

**Objective:** Service continues across failure scenarios.

**Implementation:**
- DR design: Germany-WC primary, Germany-North DR. RPO ≤15 min, RTO ≤4 h (`architecture.md` §12).
- Quarterly DR drill during pilot operation; twice-yearly thereafter.
- BCM policy covering scenarios beyond technical DR (Microsoft regional outage, Klaravex personnel availability, supplier failure).
- Communication plan to visitBerlin DPO and IT lead within 30 min of any significant incident.

**Evidence:** BCM policy; DR-drill execution reports.

**Notes:** ISO 27001 A.5.29, A.5.30.

---

## 13. IM — Incident Management

**Objective:** Incidents detected, classified, contained, resolved, reviewed.

**Implementation:**
- 24×7 SOC monitoring via Microsoft Defender for Cloud + Azure Monitor.
- Incident-response runbook covering detection, triage, containment, eradication, recovery, lessons-learned.
- Classification severities and notification SLAs per `gdpr-dossier.md` §7 and `nis2.md` §2.2.
- Post-incident review within 30 days of any significant incident; report shared with visitBerlin.

**Evidence:** Incident register; runbook; post-incident review template.

**Notes:** ISO 27001 A.5.24–A.5.28; NIS2 Art. 23.

---

## 14. PI — Provider-related Security (Lieferantenbeziehungen / Provider-Beziehungen)

**Objective:** Risks from sub-providers managed.

**Implementation:**
- Sub-processor: Microsoft (sole). Microsoft Online Services DPA + Product Terms + Azure OpenAI service-specific terms.
- Microsoft's own C5 attestation reviewed annually.
- Sub-processor change notification per Art. 28(2) GDPR.

**Evidence:** Sub-processor register (`gdpr-dossier.md` §2); Microsoft C5 attestation.

**Notes:** ISO 27001 A.5.19, A.5.20, A.5.21, A.5.22, A.5.23.

---

## 15. SIM — Compliance (Sicherheitsmanagement-Compliance)

**Objective:** Compliance with legal, regulatory, contractual requirements is monitored.

**Implementation:**
- Compliance register tracking GDPR, BDSG, NIS2 / NIS2UmsuCG, BSI C5, ISO 27001, BetrVG co-determination obligations, customer contractual obligations.
- Annual compliance review.
- Internal audit on Klaravex ISMS annually.

**Evidence:** Compliance register; internal-audit reports.

**Notes:** ISO 27001 A.5.31, A.5.32, A.5.34, A.5.36.

---

## 16. DEV — Secure Software Development

**Objective:** Software is developed securely.

**Implementation:**
- Secure SDLC policy.
- Threat modelling at each major design change.
- SAST in CI (CodeQL or equivalent).
- Software Composition Analysis (Dependabot + Defender for DevOps).
- Code review on every PR; two-reviewer rule for security-sensitive code paths (permission filter, audit logging, identity).
- Pre-prod security gate in CI/CD; releases require sign-off from a named approver.

**Evidence:** SDLC policy; CI configuration; PR-review evidence sampling.

**Notes:** ISO 27001 A.8.25, A.8.26, A.8.27, A.8.28, A.8.30.

---

## 17. ACQ — Procurement

**Objective:** Procurement of services and components done with security considered.

**Implementation:**
- Supplier security questionnaire for new suppliers; current suppliers reviewed annually.
- Procurement decisions on sub-processors require CISO + DPO sign-off.
- Microsoft (sole sub-processor here) reviewed annually.

**Evidence:** Supplier-management policy; current supplier questionnaires.

**Notes:** ISO 27001 A.5.19; significant overlap with PI.

---

## 18. BC — Customer Communication and User Documentation

**Objective:** Customer can operate the service securely; customer is informed of relevant changes.

**Implementation:**
- Service description (this proposal + architecture documents).
- Operating documentation: Admin Console help, runbooks, escalation paths.
- Change notification: written notification to the visitBerlin product owner and DPO for any change affecting security posture; 30-day lead for non-urgent, immediate for emergency.
- Service-status communication: a status page available to the visitBerlin team; major incidents notified by direct contact.

**Evidence:** Change-notification log; documentation set; status-page archive.

**Notes:** ISO 27001 A.5.4 (overlaps with SP and BCM).

---

## 19. Cross-walk to ISO 27001:2022 Annex A

The control mapping above references the relevant ISO 27001 Annex A controls. Klaravex's ISO 27001:2022 certificate is current; the visitBerlin engagement is in scope of that certification from go-live.

## 20. Cross-walk to BSI IT-Grundschutz

For the visitBerlin BSI Grundschutz baseline (if maintained), the relevant building blocks are: ISMS.1, ORP.1–ORP.4, CON.1–CON.3, OPS.1, OPS.2, OPS.3, INF.1, NET.1, NET.3, SYS.1, APP.3 (web), APP.4 (cloud), DER.1–DER.4. The C5 controls above are a superset of the relevant Grundschutz module baseline.

---

## 21. Attestation roadmap

| Milestone | Timing | Deliverable |
| --- | --- | --- |
| C5-aligned operation | from go-live | Documented controls, evidence collection |
| First C5 readiness assessment (internal) | +6 months | Gap analysis, remediation plan |
| Pre-audit gap-close | +12 months | Remediation evidence |
| BSI C5 Type 1 attestation (point-in-time) | +18 months | Type 1 report |
| BSI C5 Type 2 attestation (period covering 6+ months) | +24 months | Type 2 report shared with visitBerlin |
| Annual surveillance | +36 months and yearly | Continued Type 2 reports |

The auditor will be a BSI-accredited firm; selection in coordination with visitBerlin if visitBerlin has a preferred firm.

---

## 22. Document control

- Reviewed annually and on material change.
- Reviewer: Klaravex CISO + visitBerlin IT lead joint sign-off.

---

*End of BSI C5 mapping.*
