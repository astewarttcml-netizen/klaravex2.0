# ADR-0007 — Mailbox ingestion default disabled; per-mailbox opt-in only

**Status:** Accepted
**Date:** 2026-06-27

## Context

Concept §3.1 lists "automated import from email mailboxes" without bounding it. Concept §7 raises GDPR concern for the same feature. The literal reading — ingest all mailboxes by default — is a GDPR liability for several converging reasons:

- Personal mailboxes (`firstname.lastname@visitberlin.de`) carry communications subject to works-council co-determination and the German "fernmeldegeheimnis"-adjacent protections that apply even in employer-provided systems where private use is tolerated.
- Inbound emails from external senders include personal data of people who never consented to AI processing.
- BCC headers leak third-party recipient identities.
- Sent items expose drafts and ad-hoc reasoning the author did not intend to publish.

A safe default avoids these problems by default and lets the Administrator opt in mailbox-by-mailbox after DPO review.

## Decision

The mailbox connector ships **disabled** at deployment. Zero mailboxes ingested at go-live.

To enable a mailbox:

1. The Administrator selects a mailbox in the Admin Console's "Source connections" panel.
2. The UI requires a DPO sign-off field (free-text justification + DPO name) before "Enable" becomes clickable. This is a procedural control; the audit log records who clicked enable and the justification text.
3. Personal mailboxes are blocked at the Admin Console level (detected by Entra ID attribute — primary user mailbox of a natural person). Only shared / functional mailboxes are eligible.

Once enabled, the connector applies these filters:

- Drafts, calendar items, contacts, tasks: excluded.
- Sent items: excluded by default; optional opt-in per mailbox.
- BCC headers: stripped before AI processing.
- External senders: ingested only if the sender domain is on the per-mailbox allowlist; otherwise the message is logged-but-discarded.
- Attachments: pass through the same virus scan + sanitisation pipeline as manual uploads.

Implements proposal §6.7.

## Consequences

**Positive**
- The connector cannot ingest a mailbox by mistake. Misconfiguration on day one is impossible.
- DPO has a procedural gate; the audit log proves it was used.
- Default-deny matches GDPR Art. 25 data-protection-by-default expectation.

**Negative**
- Mailbox ingestion is unavailable until Administrators actively opt in. If the project team expects mailbox content from day one, they need to plan the DPO conversations in advance. Mitigated by the proposal §5 phase-1 workshops, which include the mailbox-scope decision.
- Personal-mailbox exclusion is a hard block. If a use case genuinely needs personal-mailbox content (e.g. capturing knowledge from a leaver), the path is a manual export by the leaver, not automated ingestion.

**Neutral**
- The connector code is the same code regardless of opt-in state; the gate is configuration.
