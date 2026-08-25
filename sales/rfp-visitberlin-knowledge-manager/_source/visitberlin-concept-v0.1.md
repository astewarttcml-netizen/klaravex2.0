# visitBerlin — Berlin Tourismus & Kongress GmbH

## Project Description — Knowledge Manager

> An AI-supported knowledge platform for capturing, structuring and
> needs-based distribution of company information.
>
> Concept draft for discussion within the project team
> **Version 0.1 (draft)** — provided by visitBerlin

---

## 1. Background and Objectives

### 1.1 Background
Within visitBerlin, business-relevant information is currently exchanged through heterogeneous and often transient channels — by email, via chat messages (e.g. Microsoft Teams) and verbally in meetings and personal conversations. This creates structural weaknesses:

- Knowledge is scattered, hard to find and tied to individual people or mailboxes.
- Information is lost when staff change roles or in day-to-day operations.
- There is no reliable, searchable single source of truth for company-wide knowledge.
- Employees often receive information by chance rather than based on their needs — sometimes too much (overload), sometimes too little (knowledge gaps).

### 1.2 Objective
The Knowledge Manager is a central, AI-supported knowledge platform. All business-relevant information will be stored centrally in written or documented form (Word documents, Excel spreadsheets, presentations, studies, notes, etc.), automatically processed by AI and made available to employees according to their needs.

**Core principle:** what was previously communicated by email, chat or verbally is documented in the Knowledge Manager in a binding way and thereby made permanently usable.

### 1.3 Overarching project goals
- Establish a central, reliable knowledge base for the entire company.
- Provide needs-based information — each employee receives the information relevant to their work.
- Reduce knowledge loss and dependence on individual knowledge holders.
- Enable efficient discovery of knowledge through a natural-language search or bot.
- Ensure the currency, confidentiality and traceability of the stored content.

---

## 2. Basic Functional Principle

The Knowledge Manager combines two complementary mechanisms:

> **Fig. 1:** Overview — feeding sources, the read-only connected tourism data hub, AI-supported processing, and push and pull distribution to employees.

### 2.1 Push — active distribution of information
As soon as new content is added, the system automatically distributes it to the employees for whom it is relevant. Relevance is derived from the activity profile and from individually subscribed topics. This proactively informs employees about news without them having to search themselves.

### 2.2 Pull — active queries by employees
Employees can query the knowledge base themselves at any time — via an AI-supported bot in natural language. This allows them to find information they need, have forgotten or want to look up. The bot answers questions based on the stored content and references the underlying sources.

### 2.3 The role of artificial intelligence
The AI handles the processing and preparation of content. Specifically:
- Automatic **tagging** of newly added content (topics, keywords, categories).
- Automatic **summarization** of documents (short version for quick orientation).
- **Matching** of content to activity profiles and subscribed topics.
- **Answering** natural-language questions based on the knowledge base (retrieval-supported answers with source references).
- **Output** of content in a prepared form (e.g. thematically bundled digests).

> **Fig. 2:** AI-supported processing chain when new content is added.

---

## 3. Core Functions

### 3.1 Adding and capturing content
Content enters the Knowledge Manager via various sources:
- Manual upload of documents (Word, Excel, PowerPoint, PDF, studies).
- Automated import from connected source systems: email, Microsoft SharePoint and Microsoft Teams.
- **Read-only connection to the tourism data hub** (graph database): it holds, among other things, all POI information, participating Berlin Welcome Card (BWC) partners as well as address and contact data of stakeholders and cooperation partners (from the CRM). This data is referenced and queried but **not copied** into the Knowledge Manager — the data hub remains the system of record.
- Direct entry of short notes / messages within the platform.

When content is added, the system records metadata (title, author, date, source, responsible unit) and uses AI to add keywords, a category and a summary. Optionally, the person adding the content can review and adjust these suggestions before publication.

The tourism data hub plays a special role among the sources: it is connected on a read-only basis. Structured master data such as POIs, BWC partners and contact data of stakeholders and cooperation partners are maintained there and queried or referenced by the Knowledge Manager when needed. This keeps the data hub as the leading, always up-to-date system and avoids duplicate or outdated data.

### 3.2 Employee profile
Each employee maintains a profile describing their role and activities (e.g. department, role, focus areas, markets/regions). On this basis, the system automatically matches the relevant information.

### 3.3 Topic subscriptions
Beyond the standard knowledge relevant to their work, employees can subscribe to additional topics on which they wish to be informed regularly.

### 3.4 Frequency of information delivery
Employees individually decide how often they want to receive information:
- **Instant** — immediately as soon as a news item is added.
- **Several times a day** — bundled into several deliveries per day.
- **Daily** — once a day as a daily digest.
- **Weekly** — once a week as a weekly overview.

The frequency can be set individually per topic or subscription (e.g. work-critical topics 'instant', general topics 'weekly').

### 3.5 Bot / natural-language query
Via a chatbot, employees can query the knowledge base in natural language. The bot respects the permissions of the requesting person and returns only content they are authorized to access. Answers include references to the underlying sources. When needed, the bot can also include structured information from the tourism data hub — such as POI data, BWC partners or contact data of stakeholders and cooperation partners — and reference it in its answers.

---

## 4. Permission and Role Model

Because the Knowledge Manager also contains confidential content that may only be accessible to a defined group, a tiered authorization concept is required. A two-dimensional model of confidentiality levels and roles/management levels is proposed.

> **Fig. 3:** Two-dimensional permission model — access results from the confidentiality level and the role.

### 4.1 Confidentiality levels of content

| Level                | Description                                                   | Typical access                       |
| -------------------- | ------------------------------------------------------------- | ------------------------------------ |
| Public / general     | Intended for all employees                                    | Entire workforce                     |
| Internal             | General internal information                                  | All internal staff                   |
| Confidential         | Sensitive content with a restricted circle                    | Defined areas / functions            |
| Strictly confidential| Highly sensitive content (e.g. management, HR, contracts)     | Tightly limited, named circle        |

> **Note:** the levels listed here are a proposal. The final number and naming of the levels should be agreed with data protection, the staff council and management. At a minimum — as discussed — two levels must be represented (generally accessible vs. restricted).

### 4.2 Roles in the system

| Role             | Tasks / permissions                                                                |
| ---------------- | ---------------------------------------------------------------------------------- |
| Reader           | Access to approved content according to profile and permission; manage subscriptions; use the bot |
| Author           | Add content, provide metadata, submit for approval                                 |
| Content Owner    | Editorial responsibility, upkeep and currency of a topic or document area          |
| Approver / editor| Review and approve content before publication; assign the confidentiality level    |
| Administrator    | Manage users, roles, permissions, source connections and system configuration      |

Access to a specific object results from the combination of the content's confidentiality level and the person's role/permission. Both push distribution and bot queries respect these permissions without exception.

---

## 5. Currency and Lifecycle of Content

To ensure that the stored objects are genuinely current and valid, each content item is given a defined lifecycle with an automatic validity check.

> **Fig. 4:** Lifecycle of a content item with automatic re-submission after the validity period expires.

### 5.1 Validity period and re-submission
- When content is added, a validity period is set — manually or suggested by the AI depending on the content type (e.g. 6, 12 or 24 months).
- After the period expires, the system automatically submits the item to the responsible Content Owner for review ('re-submission').
- The responsible person confirms continued validity, updates the content or archives it.

### 5.2 Status and labelling

| Status      | Meaning                                                                   |
| ----------- | ------------------------------------------------------------------------- |
| Current     | Content is reviewed and within the validity period                        |
| Review due  | Validity period expired, review pending                                   |
| Outdated    | Marked as no longer valid, no longer actively distributed                 |
| Archived    | Removed from the active stock but retained in an audit-proof manner       |

Outdated or overdue content is labelled accordingly or excluded in bot answers and push deliveries, so that no one relies on information that is no longer valid.

### 5.3 Versioning and traceability
- Changes to content are versioned; earlier states remain traceable.
- Logging of who added, changed, approved or archived which content and when.

---

## 6. Further Recommended Functions

Beyond the requirements described so far, the following functions are recommended as additions:
- **Full-text and keyword search** in addition to the bot query, including filters by topic, date, responsible person and confidentiality level.
- **Source and trust display:** bot answers always reference the underlying documents so that answers remain verifiable.
- **Feedback function:** employees can mark content as helpful, outdated or incorrect and thereby contribute to quality assurance.
- **Favourites / personal watchlist** for frequently needed content.
- **Notification channels:** delivery via email, Teams or as an in-platform notification.
- **Duplicate detection:** the AI flags already existing, similar content when adding new items.
- **Reporting / metrics** for administration and management (e.g. used topics, knowledge gaps, overdue content).
- **Multilingual support:** given the international markets, support for several languages in search and output may be useful.

---

## 7. Data Protection, Security and Governance

As a state-owned company, visitBerlin is subject to particular requirements for data protection and information security. The following points should be clarified early:
- Involve the data protection officer and — where required — the staff council from the outset.
- GDPR compliance, particularly for the automated import from email mailboxes (personal data).
- Clarify which AI components are used and where data is processed (data residency, data processing agreements).
- Strictly enforce the authorization concept in all functions (push, pull, search, bot).
- Define clear governance responsibilities: who maintains, who approves, who checks currency, who manages permissions.
- **Tourism data hub:** since the read-only connection also queries personal contact data (stakeholders, cooperation partners from the CRM), data protection-compliant use must be ensured. This data is for general internal use; the data hub remains the system of record and the Knowledge Manager does not store copies.
- Audit-proof logging of access and changes.

---

## 8. Open Points and Proposed Next Steps

### 8.1 Points still to be clarified
- Final definition of the confidentiality levels and roles (to be agreed with data protection and management).
- Selection of the specific technical platform or AI solution (including data protection / hosting questions).
- Prioritization of the source connections (email, SharePoint, Teams) — what first, what later.
- Definition of the default validity periods per content type.
- Effort and responsibility for the initial population of the knowledge base (migration of existing knowledge).
- Acceptance and commitment: how to ensure that knowledge is actually added in future?

### 8.2 Proposed next steps
- Agree the concept within the project team and prioritize requirements (must / should / could).
- Review data protection and security requirements early (a DPIA may be required).
- Market / solution research and selection of suitable technologies.
- Define a manageable pilot area (e.g. one department or one topic field) for a prototype.
- Pilot with real content and users, evaluate and refine.
- Gradual rollout across the entire company including training and change management.
