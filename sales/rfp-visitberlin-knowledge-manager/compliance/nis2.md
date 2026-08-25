# NIS2 scope and applicability
### visitBerlin Knowledge Manager — by Klaravex GmbH

**Companion to:** `dpia.md`, `gdpr-dossier.md`, `bsi-c5.md`, `data-residency.md`
**Date:** 2026-06-27

> **NIS2 status:** Directive (EU) 2022/2555 (NIS2 Directive). German transposition: NIS2-Umsetzungs- und Cybersicherheitsstärkungsgesetz (NIS2UmsuCG), in force.

---

## 1. Is visitBerlin in NIS2 scope?

### 1.1 The arguments

**Argument for in-scope status:**

- visitBerlin (Berlin Tourismus & Kongress GmbH) is wholly owned by the Land Berlin. State-owned entities of regional public administration are caught by NIS2 Annex I sector "Public administration entities of regional governments" subject to size and criticality thresholds.
- Berlin is the federal capital of Germany; significant administrative functions of visitBerlin support Land-Berlin-level economic policy (tourism is a material sector of Berlin's economy).
- If visitBerlin functions as a "public body" under the German transposition definition, it may be in scope as an "essential entity" regardless of size.

**Argument for out-of-scope status:**

- visitBerlin is a marketing and convention promotion company, not a regional public administration body in the strict sense. Its activities are commercial tourism marketing.
- The German transposition includes carve-outs for certain Land-level public bodies whose activities are not within the core public administration function.

### 1.2 The conclusion

This is a question for the visitBerlin legal team to resolve definitively. Klaravex's working assumption — and the basis on which this RFP response is constructed — is:

> **visitBerlin should plan for NIS2 in-scope status, even if a strict legal reading currently exempts it.** Berlin Land procurement and the Senatsverwaltung will increasingly require NIS2-equivalent controls of state-owned entities regardless of strict scope, and the Knowledge Manager is the kind of system that should be operated to NIS2-equivalent standards regardless.

The Knowledge Manager will be built and operated as if NIS2 applies. Klaravex is in scope as a digital supplier (regardless of the controller's status), and our supply-chain security obligations to visitBerlin satisfy a chunk of the controller's NIS2 risk-management obligations on this system.

---

## 2. NIS2 obligations applicable to this system (if in scope)

The relevant articles of NIS2 (Directive 2022/2555):

### 2.1 Cybersecurity risk-management measures (Art. 21)

| Measure | Klaravex implementation | Reference |
| --- | --- | --- |
| Risk-analysis and information-system security policies | Information Security Management System operated by Klaravex, mapped to ISO 27001:2022 and BSI C5 | `bsi-c5.md` |
| Incident handling | 24×7 SOC monitoring, runbook-driven response, post-incident review | `bsi-c5.md` IM domain |
| Business continuity, backup management, crisis management | DR runbook (Germany-WC primary → Germany-North DR); RPO ≤15 min, RTO ≤4 h | `architecture.md` §12, BCM domain |
| Supply chain security | Microsoft is the sole sub-processor; due diligence per Klaravex supplier-management policy | `gdpr-dossier.md` §2 |
| Security in acquisition, development, maintenance, including vulnerability handling | Secure SDLC: SAST in CI, dependency scanning, Defender for DevOps, code review, threat modelling | `bsi-c5.md` DEV domain |
| Policies and procedures to assess effectiveness | Quarterly governance review, annual penetration test, BSI C5 attestation roadmap | This dossier §5 |
| Basic cyber hygiene practices and cybersecurity training | Standard mandatory training for Klaravex personnel; visitBerlin training scope per change-management plan | `bsi-c5.md` HR domain |
| Use of cryptography and, where appropriate, encryption | TLS 1.3 in transit; AES-256 at rest (Azure Storage Service Encryption); customer-managed keys in Azure Key Vault if visitBerlin requests | `architecture.md` §9, KM domain |
| Human resources security, access control policies, asset management | Entra ID-based access control, Klaravex personnel cleared per HR domain | `bsi-c5.md` HR + IDM + AM |
| Multi-factor authentication, continuous authentication, secured voice/text/video where applicable | MFA enforced for all roles (Entra ID conditional access); MFA + PIM for privileged | `bsi-c5.md` IDM domain |

### 2.2 Incident reporting (Art. 23)

The NIS2 reporting timeline:

| Phase | Deadline | Recipient |
| --- | --- | --- |
| Early warning | 24 hours from awareness of significant incident | National CSIRT (BSI in Germany) |
| Incident notification | 72 hours from awareness | National CSIRT |
| Intermediate report | On CSIRT request | National CSIRT |
| Final report | 1 month from incident notification | National CSIRT |

Klaravex's contractual commitment to visitBerlin under the SoW: incident classification within 4 h of detection (see `gdpr-dossier.md` §7), enabling visitBerlin to meet the 24 h NIS2 early-warning deadline with a 20 h buffer.

A "significant incident" is defined by NIS2 Art. 23(3); for a knowledge platform, the threshold candidates are:
- Confidentiality breach affecting confidential or strictly confidential content.
- Availability disruption exceeding the RTO of 4 h.
- Integrity compromise (e.g. unauthorised content modification at scale).

The Klaravex breach-detection runbook is calibrated to these thresholds.

### 2.3 Supply-chain security (Art. 21(2)(d))

Klaravex's chain to visitBerlin:

```
visitBerlin (controller, possibly NIS2 in-scope)
   └─ Klaravex (processor, ICT service provider — in scope as supplier)
        └─ Microsoft (sub-processor — likely in scope as a managed-service provider under NIS2)
```

Klaravex's NIS2 posture as a supplier:

- Self-assessment against NIS2 Art. 21 measures, documented in the Klaravex ISMS.
- ISO 27001:2022 certification (current; certificate in SoW annex).
- BSI C5 Type 2 attestation as a service operator within 24 months of go-live (commitment per proposal §4.9).
- Annual penetration test on the Klaravex-operated portion of the visitBerlin tenant.
- Supplier security questionnaire on file with Microsoft, refreshed annually.

### 2.4 Management body responsibilities (Art. 20)

NIS2 Art. 20 holds the management body of an in-scope entity personally accountable for cybersecurity risk-management measures and requires them to take training. Klaravex provides:

- A management-body briefing for the visitBerlin board and the IT lead annually.
- Training material for the management body on the Knowledge Manager's specific risk profile.
- A post-incident briefing within 30 days of any significant incident.

---

## 3. If visitBerlin is NOT in NIS2 scope

Klaravex commits to the same controls regardless. The basis:

- Berlin Land procurement may push NIS2-equivalent requirements via contract on state-owned entities.
- visitBerlin is likely to fall in scope at the next NIS2 revision or under a stricter German transposition update.
- Operating to NIS2 standards is best-practice for a state-owned entity processing personal data and business-critical knowledge.

The cost delta between "NIS2-aligned" and "fully NIS2-compliant" is small once the underlying ISMS is in place; we do not propose to leave value on the table by stopping short.

---

## 4. Klaravex's own NIS2 posture as a supplier

Klaravex itself is in NIS2 scope as an ICT service provider (Annex I sector 8 — managed service providers / managed security service providers, depending on configuration). Our self-positioning:

- Registered with the BSI under NIS2UmsuCG.
- Annual NIS2 risk-management self-assessment.
- Incident reporting per Art. 23 to BSI for incidents affecting Klaravex's own services that flow through to customers.
- We hold a public-facing NIS2 supplier statement, available on request.

A NIS2-significant incident affecting Klaravex (e.g. compromise of our identity management or our IaC pipeline) is reported to BSI within 24 h and to the visitBerlin DPO immediately on detection.

---

## 5. Operational alignment plan

| Activity | Timing | Owner |
| --- | --- | --- |
| Legal opinion on visitBerlin NIS2 scope | Phase 1, week 3 | visitBerlin legal + Klaravex |
| BSI registration (if in scope) | Phase 1, week 4 | visitBerlin |
| Klaravex BSI registration as supplier | already current | Klaravex |
| Joint NIS2 incident-response runbook | Phase 2, week 8 | Joint |
| Penetration test (NIS2 supply-chain scope) | Phase 2, week 11 | External firm, Klaravex coordination |
| Management-body briefing | Phase 3, before pilot end | Klaravex + visitBerlin |
| First annual NIS2 self-assessment cycle | Phase 5, +12 months | Joint |

---

## 6. References

- Directive (EU) 2022/2555 (NIS2 Directive).
- NIS2UmsuCG (German transposition).
- BSI NIS2 guidance for operators.
- ENISA NIS Cooperation Group guidance on cybersecurity risk-management measures.
- Companion: `bsi-c5.md` (control implementation), `gdpr-dossier.md` §7 (breach notification process).

---

*End of NIS2 assessment.*
