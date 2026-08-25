# Statement of Work (SOW)

**DRAFT — REVIEW WITH QUALIFIED LEGAL COUNSEL BEFORE USE.**
This template is a working frame for engagement-specific scoping. Have counsel review the standard fields before publishing it as a fillable template for client signature.

---

**SOW No.:** {{SOW_NUMBER}}
**SOW Date:** {{SOW_DATE}}
**Effective Date:** {{SOW_EFFECTIVE_DATE}}
**Underlying Agreement:** Master Services Agreement between Klaravex LLC ("Klaravex") and **{{CLIENT_LEGAL_NAME}}** ("Client") dated {{MSA_DATE}}.

This SOW is governed by the Underlying Agreement. In the event of conflict, the Underlying Agreement controls unless this SOW expressly references the section being modified.

## 1. Engagement Summary

**Engagement name:** {{ENGAGEMENT_NAME}}
**Service category:** {{Foundation | Assurance | Directive | Co-Managed | Fixed-Fee Assessment | Project | Add-on | Block Hours | Procurement}}
**Primary Klaravex contact:** {{KLARAVEX_CONTACT}} ({{EMAIL}})
**Primary Client contact:** {{CLIENT_CONTACT}} ({{EMAIL}})

**One-paragraph summary.** {{SUMMARY_PARAGRAPH}}

## 2. Scope of Services

### 2.1 In scope

{{LIST_OF_IN_SCOPE_ACTIVITIES}}

Example (Foundation tier):
- Loki AI helpdesk available 24/7 to {{USER_COUNT}} named users
- Microsoft 365 / Azure / Google Workspace / AWS user lifecycle management
- Ubiquiti UniFi network management for {{SITE_COUNT}} sites
- Microsoft Intune endpoint management
- MFA + Conditional Access baseline configuration and ongoing tuning
- Monthly operational summary report

### 2.2 Out of scope

The following are expressly out of scope under this SOW. Klaravex may provide them under a separate SOW or change order:

- {{LIST_OF_OUT_OF_SCOPE_ACTIVITIES}}
- Defense / DIB / CMMC / ITAR / export-controlled environments
- On-site work outside {{SERVICE_REGION}}
- Custom application development outside identified runbooks
- Legal counsel and tax advisory services

### 2.3 Assumptions and Client responsibilities

- Client provides timely access to systems, credentials, and personnel necessary for performance
- Client designates one primary technical contact
- Client backs up critical data prior to material changes per documented runbooks
- Client maintains current software licenses for in-scope products
- {{OTHER_CLIENT_ASSUMPTIONS}}

## 3. Deliverables

| # | Deliverable | Acceptance criteria | Target date |
|---|---|---|---|
| D1 | {{DELIVERABLE_1}} | {{ACCEPTANCE_1}} | {{DATE_1}} |
| D2 | {{DELIVERABLE_2}} | {{ACCEPTANCE_2}} | {{DATE_2}} |
| D3 | {{DELIVERABLE_3}} | {{ACCEPTANCE_3}} | {{DATE_3}} |

## 4. Timeline and Term

**Term.** {{SOW_TERM}} (e.g., 12-month initial term, auto-renewing in 12-month increments unless either Party gives 60 days' notice; or, fixed-fee engagement targeting completion by {{TARGET_DATE}}).

**Key milestones.**
- {{MILESTONE_1}}
- {{MILESTONE_2}}
- {{MILESTONE_3}}

## 5. Fees and Payment

### 5.1 Fee structure

{{ONE_OF: Recurring | Fixed-fee | Time-and-materials | Block-hours}}

**Recurring example:**
- Foundation tier: $100 per user per month × {{USER_COUNT}} users = ${{MONTHLY_TOTAL}}
- Billing: monthly in advance, Net 15
- Annual prepay option: 10% discount on a 12-month prepayment

**Fixed-fee example:**
- Cyber-Insurance Readiness Assessment: ${{FIXED_FEE}}
- Billing: 50% on SOW execution, 50% on final report delivery
- Up to {{FEE_CREDIT_PCT}}% of the assessment fee credits toward remediation work performed by Klaravex within {{CREDIT_WINDOW}} months

**T&M example:**
- Rate: ${{HOURLY_RATE}}/hour for engineering, ${{HOURLY_RATE_VCISO}}/hour for vCISO/vCIO
- Estimate: {{HOUR_ESTIMATE}} hours, not-to-exceed without written authorization
- Billing: monthly in arrears, Net 15, with detailed time entries

**Block-hours example:**
- Block size: {{BLOCK_HOURS}} hours at ${{BLOCK_RATE}}/hour
- Expiration: {{BLOCK_EXPIRY}} months from SOW execution
- Refill: automatic at {{REFILL_THRESHOLD}} hours remaining unless Client declines

### 5.2 Expenses

Pre-approved expenses reimbursable at cost. Travel beyond {{LOCAL_RADIUS}} requires advance written approval.

### 5.3 Change orders

Material changes to scope, fees, or timeline require a written change order signed by both Parties. Change orders take the form of an amendment to this SOW.

## 6. Acceptance

Each Deliverable is accepted on the earlier of (a) Client's written acceptance, or (b) ten (10) business days after delivery if Client has not provided written rejection identifying specific failures of acceptance criteria.

## 7. Service Levels (where applicable)

| Severity | Description | Response target | Resolution target |
|---|---|---|---|
| SEV-1 | Production down or active security incident | 30 min | 4 hours |
| SEV-2 | Major function impaired | 2 business hours | 1 business day |
| SEV-3 | Minor function impaired | 1 business day | 5 business days |
| SEV-4 | Question or feature request | 2 business days | Best effort |

Service level credits, if any: {{SLA_CREDIT_TERMS_OR_NONE}}.

## 8. Data and Compliance

8.1 **PHI.** No. PHI is out of scope under the MSA (§7.2); Klaravex's infrastructure is not HIPAA-eligible. Do not mark "Yes" or reference a BAA unless and until the BAA is formally reactivated (see legal/BAA-template.md banner).
8.2 **EU/UK Personal Data.** {{Yes / No}}. If yes, the DPA between the Parties dated {{DPA_DATE}} applies.
8.3 **Compliance frameworks in scope:** {{HIPAA | SOC 2 | ISO 27001 | NIS2 | DORA | None}}.
8.4 **No defense / DIB / CMMC.** Klaravex does not perform CMMC, DFARS 7012, or ITAR-controlled work under this SOW.

## 9. Personnel

**Klaravex named personnel:** {{NAMED_TEAM_OR_NONE}}.
**Co-managed IT.** {{If applicable, the Client's internal IT designee is {{CLIENT_IT_DESIGNEE}}.}}

## 10. Termination

In addition to the termination provisions of the Underlying Agreement:

- Termination for convenience requires {{NOTICE_DAYS}} days' notice
- On termination, Klaravex delivers a transition package containing access credentials, current configuration baselines, runbooks specific to Client's environment, and any in-flight tickets, for a fee of {{TRANSITION_FEE_OR_INCLUDED}}

## 11. Signatures

**KLARAVEX LLC**

By: ____________________________
Name: {{KLARAVEX_SIGNATORY}}
Title: {{KLARAVEX_SIGNATORY_TITLE}}
Date: __________________________

**{{CLIENT_LEGAL_NAME}}**

By: ____________________________
Name: {{CLIENT_SIGNATORY}}
Title: {{CLIENT_SIGNATORY_TITLE}}
Date: __________________________
