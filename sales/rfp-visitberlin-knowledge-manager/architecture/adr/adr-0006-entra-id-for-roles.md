# ADR-0006 — Roles managed as Entra ID security groups

**Status:** Accepted
**Date:** 2026-06-27

## Context

Concept §4.2 defines five roles (Reader, Author, Content Owner, Approver, Administrator). Permission decisions in the system depend on the user's role plus the content's confidentiality level and responsible-unit attribute (concept §4, ADR-0002).

Two implementation options:

1. **Parallel role table** inside the Knowledge Manager. Administrators assign roles in the Admin Console; the system maintains its own user-to-role mapping.
2. **Entra ID security groups.** Each role is one or more Entra ID groups; assignment happens in the visitBerlin tenant's existing identity-management process; the Knowledge Manager reads group membership at session time.

## Decision

Roles are Entra ID security groups:

| Role | Entra ID group |
| --- | --- |
| Reader | implicit (all employees in the tenant) |
| Author | `KM-Author` |
| Content Owner | `KM-ContentOwner-<area>` (one per content area) |
| Approver | `KM-Approver-<area>` |
| Administrator | `KM-Administrator` |

Confidentiality clearance (the ABAC `clearance_max_level` attribute) is also resolved from an Entra ID group membership pattern: `KM-Clearance-Internal`, `KM-Clearance-Confidential`, `KM-Clearance-StrictlyConfidential`. Default clearance for any tenant member is `Internal` (per the staff-council-friendly default in concept §4.1).

The Knowledge Manager Admin Console can *view* the role assignments but cannot *write* them — assignment changes go through Entra ID (PIM, Access Reviews, etc., per visitBerlin's existing identity-governance setup).

## Consequences

**Positive**
- Role assignment uses the same process the visitBerlin IT team already operates: onboarding, offboarding, leaver process, joiner-mover-leaver, PIM for elevated roles.
- Single source of truth for identity. No parallel governance to drift from Entra ID.
- Compliance posture: Entra ID's audit log is the authoritative record of who held which role when. The Knowledge Manager's audit log references it.

**Negative**
- The Admin Console UX for "who is an Author" is read-only; an Administrator must context-switch to Entra ID admin to change assignments. Mitigated by deep-linking the Admin Console to the relevant Entra ID group page.
- A change in Entra ID takes up to one session cache TTL (15 min) to take effect in the Knowledge Manager. Acceptable; "instantaneous" role revocation is not a stated requirement, and forced sign-out (Entra ID `revokeSignInSessions`) terminates active sessions for emergency cases.

**Neutral**
- Per-area Content Owner / Approver groups grow with the taxonomy. Group provisioning is automatable via Entra ID PowerShell or Graph during taxonomy expansion.
