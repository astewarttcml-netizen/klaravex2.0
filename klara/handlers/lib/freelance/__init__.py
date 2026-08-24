"""Klaravex freelance bid pipeline (ported from itexperts-berlin).

Submodules:
  - fm_cookie     Freelancermap session-cookie renewal (pure HTTP, no browser).
  - scout_multi   Multi-platform project discovery (FM scrape + PPH/Guru/Upwork Playwright).
  - submit_fm     Freelancermap.de bid submission via /api/projects/apply.
  - submit_pw     Upwork / PeoplePerHour / Guru via Playwright auto-submit.
  - converter     Won bid -> klaravex_clients lead + onboarding handoff.
"""
