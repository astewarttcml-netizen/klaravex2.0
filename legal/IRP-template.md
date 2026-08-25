# Klaravex LLC — Incident Response Plan (IRP)

> **[DRAFT — counsel review pending per T8.3. Do not represent as a finalized,
> auditor-ready document until removed.]**
>
> **Version:** 1.0 (initial)
> **Effective:** 2026-06-10
> **Owner:** Anthony Stewart, Founder & Incident Commander
> **Next review:** 2027-06-10 (annual) or after any P1 incident
> **Classification:** Internal — share with clients only under MSA confidentiality

This document satisfies the "written Incident Response Plan" precondition required by:
- Cowbell Cyber policy FLY-CB-Q0N7TTC52 underwriting questions
- Klaravex's E&O / Tech E&O policy (bound 2026-06-10)
- SOC 2 Common Criteria CC7.3 (Incident Response)
- ISO 27001 A.16 (Information Security Incident Management)
- HIPAA Security Rule §164.308(a)(6) (Security Incident Procedures) — applicable only after T8.6 BAA is signed

---

## 1. Purpose & Scope

### 1.1 Purpose
This plan defines how Klaravex detects, contains, eradicates, recovers from, and learns from cybersecurity incidents affecting Klaravex-operated infrastructure OR client systems under Klaravex's management.

### 1.2 In scope
- Klaravex production infrastructure (Azure Container App `klaravex-api`, Cloud86 Postgres, klaravex.com / klaravex.com WordPress, Loki AI backend, Vapi/Twilio voice surface)
- Client endpoints + tenancies that Klaravex actively manages under a current MSA (Foundation / Assurance / Directive tiers + Co-Managed variants)
- Vendor-side incidents that materially affect Klaravex or its clients (Mercury bank, Stripe, OpenAI, Anthropic, Cowbell, Microsoft 365, Google Workspace, Atera, Smartlead, Vapi, Cloudflare)

### 1.3 Out of scope
- Client environments NOT under active Klaravex management (referred out)
- Physical security incidents at client premises (refer to client's own plan)
- Personnel / HR incidents (handled under separate HR policy when staff > 1)

---

## 2. Roles & Responsibilities

| Role | Person | Phone | Responsibility |
|---|---|---|---|
| **Incident Commander** | Anthony Stewart | +1 (424) 348-6010 | Final call on every decision. Sole authority to declare P1 / engage IR retainer / notify clients / engage counsel. |
| **Tech Lead** | Anthony Stewart | same | Forensics, containment, eradication, recovery. While Klaravex is single-operator, Loki AI assists with diagnosis but never decides. |
| **Communications Lead** | Anthony Stewart | same | All client + carrier + regulator communications. Drafts via `incident-comms` doc-agent template (`.loki/agents/incident-comms.md`) but Anthony signs every external send. |
| **Legal Counsel** | TBD (per T8.3) | TBD | Engaged for any incident involving PII/PHI/breach-notification triggers. Until counsel of record is named, default to Anthony's US tech attorney; for EU residents affected, also engage German Datenschutzbeauftragter when designated. |
| **Cyber IR Retainer** | Cowbell Resiliency / SpearTip MDR | claims@cowbellcyber.ai, 833-633-8666 | Engaged for any P1 with confirmed adversary action, ransomware, or data exfiltration. |
| **Carrier (Cyber)** | Spinnaker / Cowbell | claims@cowbellcyber.ai, 833-633-8666 | Notified within 72 hours of any incident that may trigger a claim. |
| **Carrier (E&O)** | (record per T8.2 follow-up) | TBD | Notified within 72 hours of any incident exposing Klaravex to client liability. |

While Klaravex is single-operator, the Incident Commander, Tech Lead, and Communications Lead roles all collapse to Anthony Stewart. As Klaravex scales, these roles separate. The plan does not change shape — only the names in this table change.

---

## 3. Severity Classification

| Severity | Definition | Examples | Decision authority | SLA |
|---|---|---|---|---|
| **P1 Critical** | Active compromise OR major service unavailability OR confirmed data exfiltration OR regulated-data exposure | Ransomware on a managed client; klaravex_api down >15 min; Stripe webhook secret leaked; PHI exposed; admin credentials in public paste | Anthony only. Engage Cowbell + IR retainer immediately. | Initial contain ≤ 1 hr · Eradicate ≤ 24 hr · Client notify ≤ 4 hr · Carrier notify ≤ 72 hr · Regulator notify ≤ 72 hr (GDPR) / 60 days (HIPAA) |
| **P2 High** | Partial service degradation OR a credential / key rotation event OR confirmed attempted intrusion blocked | Single client's M365 tenant locked; suspicious OAuth grant detected; one chat session abused for prompt injection; a Cloud86 outage affecting WordPress | Anthony decides; can be delegated to Tech Lead once role separates | Initial contain ≤ 4 hr · Eradicate ≤ 48 hr · Client notify ≤ 24 hr |
| **P3 Medium** | Low-impact incident with no data exposure | Failed phishing simulation engagement; one false-positive Loki escalation; KB chat returning nonsense (G28 H10 pre-fix class) | Tech Lead | Eradicate ≤ 5 business days |
| **P4 Low** | Process / advisory finding with no incident | Routine vulnerability discovered in client environment; Cowbell Insight surfaced | Tech Lead handles in normal queue | Treated as normal work, not incident |

Anyone in doubt about severity classifies UP, not down. P3 misclassified as P4 is rarely consequential; P1 misclassified as P3 is catastrophic.

---

## 4. Detection Sources

### 4.1 Automated
- Azure Container App health probe + `loki-watchdog-azure.sh` (every 30 min; fail = `revision restart` × 1, then escalate)
- Healthchecks.io external dead-man's-switch (catches a fully-down host that can't alert about itself)
- AuditLog middleware (`infra/loki_handlers/audit_log.py`) flags 5xx spikes
- Stripe webhook dedup (`klaravex_stripe_events`) — duplicate event rate > 5% in 1 hr is a signal
- OpenAI monthly budget check-and-record (`lib/openai_budget.py`) — > 90% used is a signal
- Atera RMM alerts on managed endpoints (channel: `klaravex_tickets`)
- Twilio + Vapi inbound logs (call disposition, escalation rate)
- Smartlead reply categorization (unsubscribe / complaint / abuse flags)
- Loki chat audit log (`klaravex_loki_audit`) — flag any session with 5+ escalation triggers
- Cowbell Insights notifications (cowbell.insure portal)

### 4.2 Human
- Direct client report via support@klaravex.com → `email_agent` triages (NOT for incident reports — those bypass and go straight to Anthony's phone)
- Voice line +1 (424) 348-6010 → Vapi triage → automatic Anthony escalation on the `escalate_to_anthony` tool
- Anthony's own observation
- Vendor notification (Microsoft Security Response Center, Stripe Security, Cowbell, etc.)

### 4.3 What is NOT a detection source
- Loki AI cannot declare a P1. It can ESCALATE — Anthony declares. This is a hard rule.
- A doc-agent (e.g. `incident-comms`) cannot send a client-facing breach notification without Anthony's review (`.loki/agents/CONVENTIONS.md` rule).

---

## 5. The Six Phases

### 5.1 Preparation (continuous, not incident-specific)
- Maintain this document (annual review minimum)
- Maintain the contact list in §2 — phone numbers and emails must be tested twice yearly
- Run tabletop exercise annually (minimum)
- Verify the Cowbell IR retainer access path before incident (do this as part of the free Risk Engineering Assessment call — see `.loki/insurance/cowbell-followups-2026-06-10.md`)
- Verify Mercury and Stripe accounts are reachable on the carrier-side via a non-Klaravex email (this prevents a "we can't log in to recover" loop during an active incident — out of scope for first version of this doc)
- Maintain `.loki/security/containment-architecture.md` (already exists per T8.9) describing what Loki CAN and CANNOT do during an incident

### 5.2 Identification
**Trigger:** any signal from §4 that fits a severity tier in §3.

**Actions (in order):**
1. Anthony confirms the signal is real (not a false positive — check logs, replay)
2. Classify severity per §3
3. Open a ticket in `klaravex_tickets` with severity prefix (e.g., `[P1] AKS compromise — 2026-06-10`)
4. Start the timer on the §3 SLA
5. If P1 or P2: page the rest of §2 (currently just Anthony's phone; future Tech Lead separation will expand this)
6. Snapshot relevant state immediately (logs, DB tables, container revision name, Azure activity log timestamp) — store in `.loki/incidents/<YYYYMMDD>-<slug>/`

**Do NOT:**
- Power off a compromised host before snapshotting (loses forensic value)
- Delete logs to "tidy up" — even seemingly-benign cleanup destroys evidence
- Make any external statement before §5.4 is complete

### 5.3 Containment (short-term + long-term)
**Short-term (within 1 hour for P1):**
- Network: revoke compromised credentials, rotate keys, isolate the affected node (Azure CA: `az containerapp ingress disable`; client endpoint: Atera quarantine)
- Identity: revoke Microsoft Graph / Google Workspace / Mercury / Stripe / Atera sessions; rotate API keys; require MFA re-enrollment
- Data: snapshot the affected tables, revoke connection-string secret, force a new Cloud86 password through their support if needed
- Communications: pre-stage external messages but DO NOT send until §5.4

**Long-term:**
- Replace the affected node entirely (do not "clean and reuse")
- Add detection for the technique used so we catch a repeat
- Update `.loki/memory/semantic/anti-patterns.json` so future Loki cycles know

### 5.4 Eradication
- Confirm the attacker has no remaining access (no dormant scheduled tasks, no rogue OAuth grants, no persistence in cron, no hidden Atera agents)
- Confirm all credentials touched by the incident are rotated
- Confirm the vulnerability the attacker exploited is patched (or the vulnerable path is removed)
- Run a full vulnerability scan (Cowbell Spotlights post-incident scan is included with the policy)

### 5.5 Recovery
- Restore service in a controlled cadence: critical client-facing first, then secondary
- Monitor for re-entry (tighter alerting, lower thresholds) for at least 14 days
- Reconnect external integrations one at a time, verifying each
- Don't declare "recovered" until 72 hours have passed without recurrence

### 5.6 Lessons learned (post-incident)
- Within 5 business days of recovery: a written post-mortem in `.loki/incidents/<YYYYMMDD>-<slug>/post-mortem.md`
- Five-whys analysis
- Action items with named owners + due dates (added to TASKS.md as G-prefixed entries)
- Update §3 (severity), §4 (detection), §5 (response) of this document if the incident exposed a gap
- Update `.loki/memory/semantic/anti-patterns.json` and `.loki/state/relevant-solutions.json`
- Share with affected clients (per §6 communications) — never as a "we got hacked" admission of incompetence, but as a "here's what happened, what we changed, what it means for you" professional disclosure
- Carrier post-incident report (Cowbell may request this in the claim flow)

---

## 6. Communications

### 6.1 Internal (single-operator note)
While Klaravex is single-operator, "internal communications" means Anthony talking to himself via tickets, audit log, and CONTINUITY.md. As Klaravex hires its first non-founder employee, this section expands to define internal Slack / Telegram / Teams channels for incident coordination.

### 6.2 Client
- **Within 4 hours of confirming a P1** affecting their environment: brief notification email (template: `incident-comms` agent → `.loki/agents/incident-comms.md`), drafted by AI, signed by Anthony, sent from astewart@klaravex.com
- **Within 24 hours of confirming a P2**: same shape, less urgent tone
- Status page updates at status.klaravex.com (NOT YET BUILT — backlog for post-launch)
- Final post-mortem within 5 business days of recovery
- All client communications are reviewed by Anthony before send. The `incident-comms` agent NEVER auto-sends.

### 6.3 Carrier
- **Cowbell (cyber):** claims@cowbellcyber.ai or 833-633-8666 within 72 hours of identifying any incident that may trigger a claim. Reference policy FLY-CB-Q0N7TTC52.
- **E&O carrier:** (per T8.2 follow-up — Anthony records carrier details after binding); within 72 hours of identifying any incident that could expose Klaravex to client liability.
- Use the §5.2 snapshot package as the basis for the carrier notice.

### 6.4 Regulator
- **GDPR (EU clients):** notify supervisory authority within 72 hours if personal data is likely affected. For Klaravex's German-served clients, the supervisory authority is the relevant Landesdatenschutzbeauftragter for the client's Bundesland.
- **HIPAA (US healthcare clients, post-T8.6 BAA):** breach affecting > 500 individuals → notify HHS within 60 days; ≤ 500 → annual roll-up. Document at `.loki/incidents/<YYYYMMDD>-<slug>/hipaa-breach-determination.md` for every incident touching a BAA client, even if the determination is "no breach".
- **State (US):** all 50 states have breach notification laws with varying thresholds. Defer to counsel — but a 30-day deadline is the floor in most states.
- **CCPA / CDPA (US):** notify affected residents per the state-specific timeline; defer to counsel.

### 6.5 Public
- No public statement before client + carrier + counsel have all been engaged
- Press inquiries go to counsel-of-record; Anthony does NOT speak to press during active incident
- Final blog post / Twitter post AFTER §5.6 post-mortem is written and counsel has cleared it

---

## 7. Specific incident playbooks (referenced)

These are abbreviated. Full playbooks live in `.loki/security/playbooks/` as they're written.

### 7.1 Ransomware on a managed endpoint
1. Atera quarantine the endpoint
2. Disconnect from the client's network at the router (instruct client by phone)
3. DO NOT pay ransom; engage Cowbell IR retainer
4. Document encrypted file types for IR team
5. Begin recovery from immutable backups (T8.1 underwriting precondition — verify backups are immutable + tested)

### 7.2 Stripe webhook secret leaked
1. Rotate webhook secret in Stripe dashboard
2. Update `STRIPE_WEBHOOK_SECRET` in Azure Container App env
3. Deploy a new revision
4. Audit `klaravex_stripe_events` for the last 24h for events that would have been forged successfully (none should be — Stripe SDK rejects bad signatures at construct_event)
5. Notify Stripe security; notify Cowbell within 72 hr

### 7.3 Mercury account compromise
1. Call Mercury fraud line immediately (number on back of card)
2. Freeze all cards (in-app + API via `mercury_webhook.py` budget enforcement)
3. Audit `klaravex_marketing_spend` for the last 60 days
4. Notify Cowbell within 72 hr
5. Notify any pending vendor whose payment was scheduled

### 7.4 PHI exposure (post-T8.6)
1. Confirm scope — which clients, which records, how many individuals
2. Engage counsel BEFORE notifying client
3. Run §5.3 short-term containment
4. HIPAA breach determination via 4-factor test (probability of compromise)
5. If breach: notify clients within 60 days, HHS per §6.4
6. NEVER NEVER notify the public before counsel + HHS

### 7.5 Loki / KB chat prompt injection that exfiltrates data
1. Confirm what was leaked from the chat session's audit log
2. Add the prompting pattern to the input guardrail blocklist (`guardrails_input.py`)
3. Re-run guardrail middleware tests
4. If data leaked = client data: §7.4 PHI exposure path applies if PHI; otherwise standard breach notification

### 7.6 Loki chat or email_agent auto-replies to a vendor (G22-class)
1. Sweep the agent's Sent folder for similar autoreplies
2. Anthony manually apologizes from astewart@klaravex.com to each affected counterparty
3. Patch the agent's skip list to cover the missed sender class (G22 pattern: add to FINANCIAL_DOMAINS / TRANSACTIONAL_LOCAL_PARTS / TRANSACTIONAL_SUBJECT_PATTERNS in `infra/loki_handlers/agents/email_agent.py`)
4. Add a regression test
5. Deploy

---

## 8. Backup & recovery (referenced from T8.1)

- **klaravex_api code:** lives in git; Anthony's local clone + repo backup
- **klaravex_* DB tables (Cloud86 + Azure):** nightly logical backups via `pg_dump` (path: `.loki/backups/<host>/<YYYYMMDD>.sql.zst`); 30-day retention
- **WordPress (klaravex.com, personal.klaravex.com, klaravex.com):** Plesk auto-backup nightly + manual snapshot before any major change
- **Atera tenant config:** export weekly to `.loki/backups/atera/`
- **Stripe / Mercury / Smartlead / Atera / Vapi configs:** screenshot all dashboards monthly; store in 1Password Klaravex vault under "Vendor Dashboard Snapshots"
- **1Password vault:** Klaravex vault has a dedicated emergency-access trustee (TBD — recommended: Anthony's US tech attorney once retained per T8.3)
- **Test restore quarterly** — a backup that's never restored is a backup that doesn't exist

---

## 9. Tabletop schedule

Minimum twice yearly (Q1 and Q3). Scenarios that MUST be on the rotation:
- Ransomware on a Foundation-tier B2B client
- Klaravex backend cold start during launch-week traffic spike (verifies the §5.5 controlled-cadence recovery)
- Stripe webhook signature mismatch caused by secret-rotation bug (test the §7.2 playbook)
- A G22-class agent-misbehavior incident — first version was Mercury auto-reply; future patterns expected

---

## 10. Version log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-06-10 | Anthony Stewart + Loki AI | Initial draft. DRAFT header — counsel review pending per T8.3. Cowbell-template comparison pending per `.loki/insurance/cowbell-followups-2026-06-10.md` follow-up #4. |
