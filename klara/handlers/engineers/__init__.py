"""Klaravex engineer agents — 5 pillar owners delivering the website's offerings.

One engineer per pillar from klaravex.com. Each engineer owns their pillar
end-to-end: sales support, service playbook, gap analysis, documentation,
ticket triage, QBR sections.

Roster (file name → pillar slug → engineer):
  - managed_security.py        managed_security        ManagedSecurityEngineer
  - regulatory_readiness.py    regulatory_readiness    RegulatoryReadinessEngineer
  - microsoft_365.py           microsoft_365           Microsoft365Engineer
  - ai_adoption.py             ai_adoption             AIAdoptionEngineer
  - strategic_advisory.py      strategic_advisory      StrategicAdvisoryEngineer

The base class lives in `base.py`. Per-engineer system prompts + specialty
keywords + pillar metadata live in their respective modules. The dispatcher
in `dispatcher.py` routes tickets to the right engineer by SKU + keyword
match. The router in `router.py` exposes the HTTP surface.

Engineer outputs land in `klaravex_engineer_actions` (migration 018) as
status=pending. Anthony approves via /portal/admin/approvals.

First-run deliverable per engineer is a PILLAR GAP ANALYSIS (not a service
playbook) — each engineer audits their pillar against the website promise
and existing infrastructure, then publishes findings + a documentation
backlog. See `base.first_gap_analysis()`.
"""
from .router import router  # noqa: F401

__all__ = ["router"]
