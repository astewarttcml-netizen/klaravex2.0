# Service Level Agreement (SLA)
## Klaravex LLC

> **DRAFT — to be reviewed with US tech attorney before use in client engagements.**
> Version: 1.0 | Effective Date: [DATE]
> Klaravex LLC, Wyoming | hello@klaravex.com

This Service Level Agreement ("SLA") governs the response and resolution targets for services
provided by Klaravex LLC to its managed IT clients. This SLA is incorporated by reference into
the applicable Master Service Agreement (MSA) and Statement of Work (SOW).

---

> **Advisory-scope disclaimer:** This SLA applies to managed IT support and readiness advisory
> services. Klaravex provides readiness advisory services. Nothing in this agreement constitutes
> legal, regulatory, or compliance counsel.

---

## 1. Severity Tiers and Response Targets

### P1 — Critical

**Definition:** Complete system outage, active security incident, ransomware or breach event, or
total loss of access to mission-critical systems (email, file storage, authentication infrastructure).

**Examples:**
- Business email system (M365 / Google Workspace) completely inaccessible for all users
- Active malware infection or ransomware in progress
- Unauthorized access detected to client network or data systems
- Total VPN / remote access failure preventing all remote work
- Firewall failure exposing internal network to internet

**Response target:** 2 hours from ticket creation
**Resolution target:** 4 hours from ticket creation (or documented workaround in place)
**Communication cadence:** Hourly updates until resolved
**Coverage:** 24/7/365 for active security incidents; business hours (M–F 8am–6pm EST) for non-security P1s unless client has agreed extended coverage in the SOW

---

### P2 — High

**Definition:** Major service degradation affecting a significant portion of users or a critical
business function. System is partially functional but business operations are severely impaired.

**Examples:**
- M365 / Google Workspace partially accessible (intermittent failures for >25% of users)
- Backup system failure or data backup not running for >24 hours
- VPN degraded — partial user access
- Endpoint security tool (EDR) offline on >25% of enrolled devices
- Email filtering / anti-spam failure allowing pass-through of malicious mail

**Response target:** 4 hours from ticket creation
**Resolution target:** 8 hours from ticket creation (or documented workaround in place)
**Communication cadence:** Every 4 hours until resolved
**Coverage:** Business hours (M–F 8am–6pm EST); on-call escalation available for P2s with active security implications

---

### P3 — Medium

**Definition:** Reduced functionality or service degradation affecting individual users or
non-critical systems. Business can continue to operate normally.

**Examples:**
- Individual user unable to access a specific application or service
- Minor M365 / Google Workspace configuration issue for one department
- Non-urgent patch deployment failure on one endpoint
- Single-user password reset or MFA re-enrollment
- Printer or peripheral connectivity issue

**Response target:** Next business day from ticket creation
**Resolution target:** 3 business days from ticket creation
**Communication cadence:** Upon resolution or if delay expected
**Coverage:** Business hours (M–F 8am–6pm EST)

---

### P4 — Low

**Definition:** Minor issues, general inquiries, how-to questions, non-urgent configuration
requests, or enhancement requests that do not affect current service functionality.

**Examples:**
- Request for a new user account or device setup (non-urgent)
- General IT guidance or how-to question
- Software installation on a single endpoint (non-business-critical)
- Policy or documentation update request
- Billing, contract, or administrative inquiry

**Response target:** 3 business days from ticket creation
**Resolution target:** 10 business days from ticket creation (or per SOW delivery schedule)
**Communication cadence:** Upon resolution or per agreed project schedule
**Coverage:** Business hours (M–F 8am–6pm EST)

---

## 2. Measurement and Reporting

2.1 **Ticket creation** — The SLA clock starts when a support ticket is created via the Klaravex client portal, support@klaravex.com, or the Loki AI chat widget (for escalated issues). Verbal or informal reports (text, WhatsApp, personal email) do not start the SLA clock until a formal ticket is created.

2.2 **Business hours** — For P3/P4 purposes, business hours are Monday–Friday, 8:00am–6:00pm US Eastern Time, excluding US federal holidays.

2.3 **Monthly reporting** — Klaravex will provide monthly reports to clients on ticket volume, severity distribution, and SLA performance. Deviation reports will be provided for any month in which P1 or P2 targets are missed.

2.4 **Loki AI triage** — Loki AI handles first-contact triage for all incoming requests. P3/P4 tickets may be fully resolved by Loki AI autonomously. P1/P2 tickets are escalated to a senior engineer immediately. Loki handles approximately 60–70% of interactions by volume autonomously; the remaining 30–40% requires human engineer review.

---

## 3. Client Responsibilities

3.1 The client agrees to provide timely responses to information requests from Klaravex. The SLA clock is paused during periods when Klaravex is awaiting information or access from the client.

3.2 The client agrees to maintain Atera RMM agents on all in-scope endpoints (B2B clients). Removal of Atera agents from enrolled endpoints may impair Klaravex's ability to meet SLA targets.

3.3 The client agrees to notify Klaravex promptly of any events, changes, or incidents that may affect Klaravex's ability to deliver services.

---

## 4. Exclusions

The following are explicitly excluded from SLA coverage and Klaravex's performance obligations:

4.1 **PHI processing** — Klaravex's Loki AI backend and managed IT infrastructure operates on Hetzner VPS (Germany), which is **not HIPAA-eligible**. Klaravex does not process, store, or transmit Protected Health Information (PHI) on its infrastructure. HIPAA readiness advisory engagements are scoping and gap assessment services only.

4.2 **Client-caused events** — Issues arising directly from client actions, including but not limited to: changes to network or firewall configuration made without Klaravex involvement; unauthorized software installation; failure to apply security patches recommended by Klaravex; providing incorrect credentials or information.

4.3 **Third-party platform outages** — Service disruptions caused by outages at Microsoft (M365), Google (Workspace), AWS, Stripe, or other third-party platforms are outside Klaravex's control. Klaravex will assist with escalation and workarounds during such outages but SLA targets are suspended.

4.4 **Internet and ISP issues** — Klaravex cannot guarantee network performance outside of managed network infrastructure it has deployed.

4.5 **Force majeure** — SLA targets are suspended during events beyond reasonable control, including natural disasters, pandemics, government orders, power outages at hosting facilities, or acts of war or terrorism.

4.6 **Consumer services** — Consumer-tier services (personal IT help, resume writing, AI coaching, identity cleanup) are not covered by this B2B SLA. Consumer services are delivered on a best-effort basis with response expectations documented in the applicable service description.

4.7 **Scope outside the SOW** — Issues or requests outside the defined scope of the applicable SOW are not subject to SLA guarantees. Out-of-scope requests will be scoped and quoted separately.

---

## 5. SLA Credits (Optional — include if agreed in MSA)

Where expressly agreed in the MSA, the following SLA credits apply for missed P1/P2 targets:

| Missed target | Credit |
|--------------|--------|
| P1 response missed by >2 hours | 5% of monthly invoice |
| P1 resolution missed by >8 hours | 10% of monthly invoice |
| P2 response missed by >4 hours | 2.5% of monthly invoice |
| P2 resolution missed by >12 hours | 5% of monthly invoice |

Credits are capped at 20% of the applicable monthly invoice per calendar month. Credits do not apply to excluded events per Section 4. Credits must be claimed within 30 days of the incident.

---

## 6. Governing Law

This SLA is governed by the laws of the State of Wyoming, United States of America, without regard to conflicts of law provisions.

---

## 7. Review and Updates

Klaravex reviews this SLA annually and may update targets with 30 days' written notice to active clients. Updates do not apply retroactively to in-progress engagements.

---

*This is a template prepared for Klaravex LLC internal use. Review with a qualified US technology
attorney before presenting to clients or executing as part of a client engagement.*
