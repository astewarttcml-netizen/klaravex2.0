---
title: "Security Readiness Checklist"
subtitle: "For regulated US small businesses — Healthcare, Legal, Financial"
version: "2026-07 · US Edition"
brand: "Klaravex"
tagline: "Clarity. Security. Results."
---

::: cover

![Klaravex](../assets/klaravex-logo-full.svg){.brand-logo}

# Security Readiness Checklist

*The 12-domain framework Klaravex uses to onboard every new client.*

**For regulated US small businesses — Healthcare · Legal · Financial**

*2026-07 · US Edition*

**klaravex.com/readiness-review**

:::

::: page

## How to use this checklist

This checklist maps a regulated small business's security posture across **12 domains**. Each item is a yes/no question a regulator, an auditor, or your client's procurement office might reasonably ask.

**Score each item as:**

- **Yes** — this is documented, tested, and evidence exists to prove it
- **Partial** — the control exists in practice but the paper trail is thin
- **No** — this doesn't exist, or exists only informally in someone's head

**How to read the domain results:**

- **Green** (all items Yes) — you're likely audit-ready in that domain
- **Yellow** (some Partial/No) — you have controls but they aren't documented or tested
- **Red** (mostly No) — a competent adversary — or auditor — will exploit this

**Working the checklist**

Set aside 45 minutes. Walk it end-to-end honestly. Getting a Yellow is not a failure — most regulated SMBs land Yellow across half these domains. Knowing the gap is the whole point.

**Scope note**

This is an operational checklist grounded in HIPAA Security Rule, SOC 2 Trust Services Criteria, ISO/IEC 27001:2022, and the FTC Safeguards Rule (2023 update). It is not legal, tax, or medical advice. Regulatory interpretation is always situation-specific — a qualified attorney or auditor is the right final word on any specific application.

:::

::: page

## Domain 1 — Governance & policy

The paperwork that says who owns your security program and what "acceptable" means.

- [ ] There is a **written information security program** dated within the last 12 months
- [ ] A **named security leader** (internal or fractional CISO) has documented authority to enforce it
- [ ] A **risk assessment** has been completed within 12 months and maps to your specific assets
- [ ] The **residual risk** has been formally acknowledged by ownership or the board

> **Why this matters:** the FTC Safeguards Rule, HIPAA §164.308, and ISO 27001:2022 A.5.1 all require a written program with a named owner. "We take security seriously" is not a program.

## Domain 2 — Asset & data inventory

You can't defend what you don't know exists.

- [ ] There is an inventory of **endpoints, servers, and cloud tenants** — dated within the last 90 days
- [ ] **Data classification** is defined: what qualifies as PHI, PII, or client-confidential
- [ ] A **data flow diagram** shows where regulated data enters, lives, and leaves
- [ ] The inventory is **reviewed and updated** on a documented cadence (quarterly typical)

> **Why this matters:** an incident starts with "which endpoint was compromised?" If you can't answer within an hour, the breach window widens.

:::

::: page

## Domain 3 — Access control & identity

Who can touch what, and how you take access back.

- [ ] **MFA is enforced** on every user account with email or file access — no exceptions
- [ ] **Privileged access** is reviewed at least quarterly, with least-privilege documented
- [ ] The **off-boarding process** removes access within 4 hours of separation (not "eventually")
- [ ] **Service accounts** have documented owners, rotated credentials, and no interactive login

> **Why this matters:** credential theft is the #1 initial-access vector in SMB breaches. MFA alone blocks ~99% of automated attacks.

## Domain 4 — Endpoint & network defense

The technical controls that stop known-bad traffic before it reaches your users.

- [ ] **EDR** (not just legacy antivirus) is deployed on every endpoint with a real 24/7 escalation path
- [ ] **Patch cadence** is documented; critical CVEs are deployed within 14 days of vendor release
- [ ] **Network segmentation** separates client-facing systems from administrative and finance systems
- [ ] **DNS filtering** + **email security gateway** actively block known-malicious traffic

> **Why this matters:** the average dwell time between initial access and detection at unprepared SMBs is 27 days. EDR + 24/7 monitoring shrinks that to hours.

:::

::: page

## Domain 5 — Backup & recovery

The last line of defense — the one you'll be grateful for.

- [ ] **Immutable backups** exist for every regulated data store (protection against ransomware)
- [ ] A **restore test** has been performed within the last 90 days, with a written result
- [ ] **Recovery Time Objective (RTO)** and **Recovery Point Objective (RPO)** are documented per system
- [ ] Backups are **stored off-site** or in a separate cloud tenant with independent credentials

> **Why this matters:** most SMBs have backups. Very few have tested restores. Untested backups are hope, not resilience.

## Domain 6 — Vendor & third-party risk

Your security is a chain — and it snaps at the weakest supplier.

- [ ] A **vendor inventory** exists with data-handling classification per vendor
- [ ] **Business Associate Agreements (BAAs)** are executed for every HIPAA-relevant vendor
- [ ] Critical vendors' **SOC 2 reports** (or equivalent) are reviewed annually
- [ ] Vendor **security incident procedures** are documented — who calls whom, how fast

> **Why this matters:** most 2025 healthcare breaches began at a vendor, not the covered entity. The MOVEit and Change Healthcare incidents are recent, sharp reminders.

:::

::: page

## Domain 7 — Incident response

When (not if) something happens, who does what — in the first hour?

- [ ] A **written incident response plan** names roles, escalation paths, and phone numbers
- [ ] A **tabletop exercise** has run within the last 12 months, with documented gaps + fixes
- [ ] A **24/7 escalation path** exists to a competent responder (internal or MSSP partner)
- [ ] **Client-notification templates** are pre-drafted and legally reviewed

> **Why this matters:** the first 60 minutes of a breach are the difference between contained and catastrophic. If you're reading the plan for the first time during the incident, you've already lost.

## Domain 8 — Training & phishing

Your people are the surface area 91% of attacks aim at.

- [ ] **Annual security awareness training** is completed by every user, evidenced by records
- [ ] **Quarterly phishing simulations** are run, with click-rate tracked and improving
- [ ] **New-hire security orientation** happens within the first 30 days of start
- [ ] **Role-specific training** exists for privileged users (admins, finance, HR)

> **Why this matters:** click rates below 5% on simulated phish are achievable and defensible. Above 15% signals a program that isn't landing.

:::

::: page

## Domain 9 — Encryption & data protection

Making stolen data useless — before it becomes a breach report.

- [ ] **Full-disk encryption** is enforced on every endpoint (laptops especially)
- [ ] **TLS 1.2+** is required everywhere; internal TLS certificates are managed with expiration monitoring
- [ ] **Cloud storage encryption at rest** is verified per tenant (Microsoft 365, Google Workspace, Azure, AWS)
- [ ] **Removable-media policy** exists — USBs, external drives — with technical enforcement where possible

> **Why this matters:** most state breach-notification laws include an "encrypted-data safe harbor." Proper encryption changes a breach into a non-event legally.

## Domain 10 — Physical & remote work

The security perimeter isn't the office wall anymore.

- [ ] **Office access** is controlled; a visitor log is maintained with dates and escort names
- [ ] A **remote-work security policy** is documented (home-network, screen-lock, family use)
- [ ] Company-managed devices are used for regulated data; **BYOD** is contained to non-regulated flows
- [ ] **Lost/stolen device** procedure exists with remote-wipe capability

> **Why this matters:** the shift to remote/hybrid work permanently expanded the attack surface. Physical controls that assume office-only presence are outdated.

:::

::: page

## Domain 11 — Monitoring & audit

Seeing what happened — and being able to prove it after the fact.

- [ ] **Central log collection** covers identity, endpoint, cloud, and email systems
- [ ] Alerts are **routed to a human** who acts within one hour, 24/7 (not just "we get emails")
- [ ] Log retention meets your **longest regulatory requirement** (HIPAA 6 years, FTC 5 years typical)
- [ ] **Log integrity** is protected — logs can't be silently altered by an attacker with local admin

> **Why this matters:** during an incident, logs are your only evidence of scope. During an audit, logs are your only evidence of controls working.

## Domain 12 — Compliance mapping & evidence

Being audit-ready means the evidence is at your fingertips, not on a scavenger hunt.

- [ ] Every control is **mapped to at least one framework** (HIPAA / SOC 2 / ISO 27001 / FTC Safeguards)
- [ ] An **evidence repository** exists with dated screenshots, policies, and test results
- [ ] **Client security questionnaires** are answered within 5 business days, with evidence
- [ ] The **overall program is reviewed** by an outside party (auditor, vCISO, or consultant) annually

> **Why this matters:** the difference between "we're secure" and "we're audit-ready" is documentation. Auditors and buyers don't reward trust — they reward evidence.

:::

::: page

## Score yourself

**Count only the items you can say Yes to.**

Total items: 48 (12 domains × 4 items each)

| Score | Diagnosis |
|---|---|
| **40 – 48** | Audit-ready. Your program can survive scrutiny. Focus is refinement and evidence hygiene. |
| **28 – 39** | Real program with real gaps. Every gap here is exploitable. Fix the Red domains first. |
| **16 – 27** | You have tools but not a program. The next audit or breach reveals the gap. |
| **0 – 15** | Exposure. A single incident becomes existential. This is the highest priority in your business. |

**Which domains were Red or Yellow for you?** Note them:

________________________________________________________________________

________________________________________________________________________

________________________________________________________________________

**Two questions worth answering honestly:**

1. If a competent auditor knocked on your door tomorrow, how many hours until you could produce evidence for every Yes above?
2. If a client sent you a security questionnaire this week, would you know who owns the response?

:::

::: page

## The gap the checklist reveals

Most regulated small businesses land **Yellow across half these domains**. The pattern is universal: the tools are bought, but the **program that ties tools into a defensible whole is missing**.

That's not a technology gap. It's an ownership gap.

Klaravex closes it.

- **Foundation tier** — managed IT + core security controls, wired into a documented baseline
- **Assurance tier** — adds deeper monitoring and 24/7 security operations, evidence-backed
- **Directive tier** — the complete regulated-SMB program: readiness advisory + MDR + a **named vCISO** who owns your posture

One team. One relationship. One bill. **Program. Not portal.**

The checklist you just filled out is the same one Klaravex uses to onboard every new Directive client. If we work together, this is the artifact your future auditor sees — with every Yes evidenced, and every Red or Yellow closed on a documented roadmap.

:::

::: page

## Next step

**Book a 30-minute readiness review.**

Klaravex walks a domain-by-domain score with you, identifies the two highest-risk items in your specific environment, and shows what closing them costs — with no obligation and no agency-style rituals.

- **Book online:** `klaravex.com/readiness-review`
- **Email reply:** reply to the email that delivered this checklist and we'll send a scheduling link
- **In a hurry?** Reply "urgent" and we'll be in touch within one business hour

---

### About Klaravex

Klaravex is the AI-augmented managed IT and security firm for regulated US small businesses. AI handles first-line work instantly. Senior human experts handle the rest. Three services — Foundation, Assurance, Directive — delivered as one accountable relationship.

**Clarity. Security. Results.**

*klaravex.com · US-owned, US-delivered · Regulated SMB focused*

:::
