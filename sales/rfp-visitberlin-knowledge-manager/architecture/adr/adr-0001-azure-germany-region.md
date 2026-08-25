# ADR-0001 — Primary region Germany-West-Central, DR Germany-North

**Status:** Accepted
**Date:** 2026-06-27
**Context for:** Knowledge Manager for visitBerlin

## Context

visitBerlin is a state-owned company under Berlin Land oversight. The system processes personal data of employees (Art. 88 BDSG / works council co-determination domain) and personal data of stakeholders (CRM contacts surfaced through the Tourism Data Hub). The Berlin DPO and the Landesbeauftragter für Datenschutz will scrutinise data residency. The proposal §3 (Why Klaravex — point 2) and §4.9 commit to German-region default and no US services in the data path.

Microsoft offers two German Azure regions: Germany-West-Central (Frankfurt) and Germany-North (Berlin). Both are inside the Microsoft EU Data Boundary and inside Germany sovereign territory. Both are operated by Microsoft Deutschland MCIO under EU-only support models.

Alternatives considered:
- Microsoft Cloud for Sovereignty in a partner-operated configuration. Higher cost, slower service refresh, no operational advantage for this workload over standard Azure-Germany.
- Sweden-Central / France-Central as primary. In EEA but not in Germany; will raise unnecessary friction with the Berlin Land procurement and the DPO.
- A non-Microsoft sovereign EU cloud (OVH, IONOS, T-Systems Sovereign Cloud). Disqualified by the M365-native ingestion requirement — moving SharePoint / Teams / Mailbox content out of Microsoft into a separate sovereign cloud creates a worse data-protection posture, not a better one.

## Decision

Primary region: **Azure Germany-West-Central** (Frankfurt).
Disaster recovery region: **Azure Germany-North** (Berlin).
Both regions inside Germany. PostgreSQL geo-replication, Blob Storage GRS to Germany-North, Bicep DR stack pre-provisioned in Germany-North.

Azure OpenAI is hosted outside Germany (Sweden-Central or France-Central) because Azure OpenAI is not available in German regions as of 2026. This is the single exception and is covered by ADR-0005 and `compliance/data-residency.md`.

No service in the data path runs in a US region. Microsoft management-plane traffic that traverses non-EU infrastructure (rare, well-documented) is accepted as part of the standard Microsoft EU Data Boundary commitment.

## Consequences

**Positive**
- Sovereignty narrative is clean: all data at rest is in Germany.
- Berlin DPO and procurement should accept without an exhaustive transfer assessment for the in-Germany data path.
- DR posture is genuine (different Microsoft datacentres in different cities) rather than zone-redundant only.

**Negative**
- Azure-Germany service catalogue lags slightly behind US/EU-West regions. We have validated that every service this architecture depends on (PostgreSQL Flex, AI Search, Blob, Service Bus, Front Door, App Service, Key Vault, Monitor) is GA in Germany-West-Central. Azure OpenAI is the exception (see ADR-0005).
- Cross-region failover testing is operationally heavier than a single-region setup. Mitigated by quarterly DR drills (planned in proposal phase 3+).
- Cost ~5–10% higher than EU-West regions.

**Neutral**
- Disaster recovery to Germany-North uses GRS for Blob and a geo-replica for PostgreSQL Flex; RPO ≤ 15 min, RTO ≤ 4 h. Documented in `architecture.md` §12.
