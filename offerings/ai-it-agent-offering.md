# Klaravex Managed AI Support Agent — Client Inclusion & Deployment Design

**Author:** Strategy/architecture working doc
**Date:** 2026-06-23
**Status:** Proposal for review — not yet published
**Surface concerned:** klaravex.com (US managed plans). `note_submissions` for acting on this → **Azure `klaravex-db`**. `.de` equivalent is a separate action → Cloud86.

---

## Executive Summary

This is **not** a standalone product sold against Atera Robin, and it is **not** dependent on Atera — the RMM/automation layer underneath is interchangeable. It is a **standard inclusion every Klaravex managed customer receives**: an AI support agent that fields *their* employees' IT problems 24/7 and resolves the common ones directly on the client's own platform (Microsoft 365 / Google Workspace / Entra ID / endpoints), with a senior Klaravex engineer owning anything that needs judgment.

The client gets one of two deployment models, chosen per client:

1. **Connected (hosted, rebranded):** the client's employees reach an AI agent **running on Klaravex infrastructure**, skinned with the client's brand (or co-branded). It acts on the client's tenant through scoped, delegated access. Fast to stand up, easy to maintain, scales across many clients.
2. **Deployed (in-tenant, dedicated):** Klaravex **stands up an agent instance inside the client's own environment**, so conversation and telemetry stay within the client's boundary. Higher assurance for regulated/data-resident clients; higher per-client operational overhead.

**The single most important constraint to design around: you are one operator.** The deployment model you default to determines whether this scales or buries you. Recommendation below: **lead with Connected/hosted multi-tenant; reserve Deployed/in-tenant for clients whose compliance posture genuinely requires data residency** (and price that overhead in).

The competitive research still matters as input — it tells us the market is validating autonomous AI IT support and that the under-served segment is exactly your ICP (5–50-seat regulated SMBs that no enterprise vendor will serve well). But the *framing* is now: **"your team gets an AI IT department, included."**

---

## Part 1 — What the Client Gets

A managed Klaravex customer's employees get:

- **Instant first response, 24/7.** An employee with a locked account, a mail issue, a "can't connect," a new-laptop setup question, gets an answer in seconds — not a ticket in a queue.
- **Actual fixes, not just answers.** For the common, well-bounded issues, the agent *performs the fix* on the client's platform (see action surface, §3) — password/MFA reset, license assignment, group/distribution membership, mailbox and OneDrive/Drive issues, re-provisioning, guided endpoint fixes.
- **A senior engineer for everything else.** Anything needing judgment — a security event, a migration question, anything compliance-relevant — escalates to a named Klaravex engineer who already knows the environment. No queue, no junior guessing.
- **A written record of every action** — useful for the client, and necessary for the regulated ones.
- **Optionally, their own brand on it.** In the Connected model the agent can appear as the *client's* internal helpdesk ("Acme IT Assistant"), making it feel like staff IT rather than an outsourced vendor.

This is positioned as **part of the managed relationship, deepening by tier** — not a line item, not a per-resolution meter.

---

## Part 2 — Deployment Architectures (the core decision)

### Model A — Connected (hosted on Klaravex infra, rebranded)

```
  Client employees
        │  (web widget / Teams / Slack / email / voice — client-branded)
        ▼
  ┌─────────────────────────────────────────┐
  │  Klaravex AI agent  (multi-tenant)        │
  │  • per-tenant config, branding, KB        │
  │  • per-tenant credential vault + isolation│
  └───────────────┬───────────────────────────┘
                  │ scoped, delegated admin (least privilege)
                  ▼
        Client tenant: M365 / Google Workspace / Entra ID / endpoints
```

- **Access to client platform:** via **delegated admin with least privilege** — for Microsoft, **GDAP** (Granular Delegated Admin Privileges) scoped to only the roles the fix-set needs (e.g. Helpdesk Admin, not Global Admin); for Google Workspace, a scoped service account / admin role; endpoints via the RMM agent (vendor-agnostic).
- **Pros:** one codebase to maintain; new clients onboard in hours not days; patching/improvement is centralized; lowest marginal cost per client → **this is the model that scales for a solo operator.**
- **Cons:** client conversation data transits/rests on Klaravex infra → **DPA required for every client, BAA for healthcare**; demands hard **multi-tenant isolation** (per-tenant credential scoping, data segregation, no cross-tenant prompt/context bleed). Tenant isolation failure is the catastrophic risk here — design for it from day one.

### Model B — Deployed (dedicated instance inside the client's environment)

```
  Client employees
        │
        ▼
  ┌──────────────────────────────────────────┐
  │  Klaravex agent instance — runs INSIDE     │
  │  client tenant / VM / container            │
  │  • data stays in client boundary           │
  │  • Klaravex manages + updates remotely      │
  └───────────────┬────────────────────────────┘
                  ▼
        Client's own M365 / Workspace / Entra ID / endpoints
```

- **Pros:** conversation + telemetry stay in the client's boundary → strongest story for **GDPR/NIS2 data residency, BAA-sensitive healthcare, or clients with their own security mandates**; isolation is physical/logical by default (one instance, one tenant).
- **Cons:** **N instances to patch, monitor, secure, and rotate credentials for** — operational overhead grows linearly with client count; version drift across clients; incident response is per-instance. **This does not scale for one person past a handful of clients** unless heavily templated and remotely managed (containerized, config-as-code, central update push).

### Decision

| Factor | Connected (A) | Deployed (B) |
|---|---|---|
| Time to onboard | Hours | Days |
| Marginal cost / client | Low | High |
| Scales for solo operator | **Yes** | Only if templated + few clients |
| Data residency / regulated fit | Needs DPA/BAA + strong isolation | **Strongest** |
| Maintenance | Centralized | Per-instance (drift risk) |
| Catastrophic risk | Cross-tenant data bleed | Per-instance compromise/neglect |

**Recommendation:** **Default to Connected (A) with rigorous per-tenant isolation.** Offer Deployed (B) only to clients whose compliance posture *requires* in-boundary data — and **price the operational overhead into their tier** (it is a premium, not a default). Build B as a *templated, centrally-managed* container from the start; never as a bespoke per-client snowflake, or it will consume all your delivery time.

---

## Part 3 — What "fix issues on their platform" actually means

Define the **action surface** explicitly before this is sold, because "the AI fixes issues" written loosely is an E&O liability (same discipline as "readiness" vs "compliance").

| Tier of action | Examples | Who acts |
|---|---|---|
| **Auto-resolve (AI executes)** | Password reset, MFA reset/re-register, account unlock, license assign/unassign, distribution/group membership, mailbox quota & basic mail-flow fixes, OneDrive/Drive sharing fixes, re-run a known-good script, guided self-service walkthroughs | AI, on pre-approved playbooks, scoped credentials |
| **Propose + human-approve** | Anything touching security config, conditional access, anything compliance-relevant, bulk changes | AI prepares, Klaravex engineer approves/executes |
| **Human-only** | Incidents, migrations, network/firewall (UniFi) changes, anything novel | Senior engineer |

- **Least privilege is non-negotiable:** the agent's credentials grant *only* the auto-resolve set. It is structurally incapable of the human-only actions — that is a security control, not a policy.
- **Every action is logged** with who/what/when (the written record), satisfying both client transparency and your own audit posture.
- **The human is the approval gate** for anything beyond the auto-resolve set — which is also your honest, defensible answer to "is it safe to let AI touch our systems?"

---

## Part 4 — Security, Tenancy & Compliance

- **Connected model:** mandatory **DPA** per client; **BAA** for any healthcare client (HIPAA); explicit **tenant isolation** at the credential, data, and context layers; data-handling that survives a GDPR/NIS2 question on the `.de` side.
- **Credential handling:** per-tenant scoped credentials in an isolated vault; **never** a shared high-privilege credential across tenants; rotation policy; injection routed and logged (consistent with project credential-handling rules).
- **GDAP expiry:** delegated admin relationships in Microsoft **expire** — monitoring for GDAP relationship expiry must be part of the managed runbook, or the agent silently loses its ability to act (common failure mode — detect via Partner Center / scheduled check).
- **Data minimization for regulated clients** is the lever that pushes a client from Model A to Model B.

---

## Part 5 — Packaging Into Existing Tiers

Do **not** create a 4th SKU. It deepens by tier:

- **Foundation** — AI first response + auto-resolve common fixes on the client platform (Connected model), full audit log.
- **Assurance** — + proactive handling (RMM event → AI reaches out to the affected user), priority human escalation, optional client-branding.
- **Directive** — + Deployed/in-tenant option where compliance requires it, compliance-aware change control, vCISO context. **Lead the sales conversation here per GTM note.**

**Pricing differentiator to state plainly:** flat, included, **no per-resolution metering**. (The enterprise agentic vendors meter per action and gate pricing behind sales — your flat managed inclusion is the opposite and is a real selling point.)

---

## Part 6 — Risks, Failure Modes, Rollback

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cross-tenant data/context bleed (Connected) | Medium if isolation is loose | Catastrophic — regulated client breach | Per-tenant isolation by design; isolation tests before each onboarding |
| Overclaiming what the AI auto-fixes | High if copy is loose | E&O exposure | §3 action-surface table; legal review of present-tense claims |
| Over-privileged agent credential | Medium | Breach blast radius | Least-privilege scoping = security control, not policy |
| GDAP relationship expiry | High over time | Agent silently can't act | Runbook monitor for delegated-admin expiry |
| Deployed-model sprawl (Model B) | High past ~3–5 clients | Consumes all delivery time | Templated container, central update push, residency-only criteria |
| Exposing internal name "Loki" / founder | Medium (existing pages do — §7) | Voice-policy breach | White-label = client brand; else "Klaravex AI"; never "Loki" |

**Rollback:** website side is copy on managed-plan pages — unpublish/revert, no infra impact. Per-client side: Connected access can be revoked by removing the delegated relationship; Deployed instances can be decommissioned per client. Keep proactive-autonomy behind a beta flag until proven.

---

## Part 7 — How This Appears on the Site (and voice note)

It is **a benefit on the managed-plans / "how our AI works" pages**, not a Robin-style hero product page:

- A feature block on each managed plan: *"Your team gets an AI IT assistant — included."*
- A short "how it works" explainer: instant response → fixes common issues on your systems → senior engineer owns the rest → full record. Optionally your brand on it.
- One line on data handling per model (residency option for regulated clients).
- CTA: Book a Free IT Assessment.

**Voice/branding (binding):** white-label deployments carry the *client's* brand. Where Klaravex-branded, the AI is **"Klaravex AI" — never "Loki"** on a client-facing surface, and **never name infra vendors** (Atera, Hetzner, Azure, Vapi). **⚠ Existing `website/copy/17-how-our-ai-works.md` names "Loki" publicly — contradicts the policy. Resolve (sanction it as a public persona, or rename) before this ships, so the AI's name is consistent across the site.**

---

## Recommended Next Steps
1. **Confirm default deployment model** (recommend Connected/hosted as default, Deployed reserved for residency-required clients).
2. **Lock the auto-resolve action surface** (§3) — exactly which fixes the AI executes vs. proposes. This is the liability boundary.
3. **Decide white-label policy** — do clients get their brand on it by default, co-brand, or Klaravex-branded? And resolve the "Loki" public-naming inconsistency.
4. On approval, I'll draft the managed-plan feature copy + a short "AI IT assistant" explainer section as `website/copy/25-managed-ai-assistant.md` in your existing format, voice-compliant.
