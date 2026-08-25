# ADR-0009 — IaC in Bicep, not Terraform

**Status:** Accepted
**Date:** 2026-06-27

## Context

The deployment is single-cloud (Azure-only, ADR-0001). The IaC choices are Bicep, Terraform, or Pulumi.

The visitBerlin IT team is a Microsoft-shop. Procurement may scrutinise non-Microsoft tooling more than Microsoft tooling for a state-owned-company project. The system's lifetime supplier-support story matters more than a hypothetical multi-cloud future.

## Decision

Bicep is the IaC language.

- All Azure resources defined as Bicep modules under `/infra/bicep/`.
- Module structure: one module per service (PostgreSQL, AI Search, Blob, Service Bus, Front Door, etc.), composed by per-environment top-level files.
- Parameter files per environment (`dev.bicepparam`, `staging.bicepparam`, `prod.bicepparam`).
- Deployment via GitHub Actions using `azure/login` (federated credential) and `azure/arm-deploy`.

## Consequences

**Positive**
- First-party Microsoft tooling; Azure-resource coverage is up-to-date the day a new SKU GAs.
- No third-party state file to manage (Bicep is template-based; what-if and incremental deployments are first-class).
- Visual Studio Code support, IntelliSense, and `az deployment what-if` are all standard.
- Procurement story is "Microsoft tools for Microsoft cloud" — simple.

**Negative**
- Bicep is Azure-only. A future multi-cloud requirement (not planned, not relevant for a state-owned tourism marketing entity) would mean a port.
- Terraform's module ecosystem is broader. Mitigated by Bicep's `br/public:` registry covering all services in this architecture.

**Neutral**
- Migration to Terraform later is mechanical if it ever becomes necessary.
