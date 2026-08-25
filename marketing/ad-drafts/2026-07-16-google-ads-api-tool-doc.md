# Klaravex Ads Automation — Tool Documentation

**Owner:** Klaravex LLC (Wyoming)
**Contact:** astewart@klaravex.com
**Purpose of this document:** describes the internal tool applying for Google Ads API Basic Access.

## What this tool is

An internal automation layer that manages Klaravex's own Google Ads account
programmatically. It is not a product sold or offered to external customers,
advertisers, or agencies — it exists solely to manage Klaravex's own advertising
spend and reporting.

## What it does

- **Campaign and ad group management:** creates and updates Search campaigns, ad
  groups, keywords, and responsive search ads for Klaravex's own account.
- **Budget and bid management:** adjusts daily budgets and bid strategies based on
  performance data pulled from the account.
- **Conversion reporting:** retrieves conversion and performance metrics (clicks,
  cost, conversions, conversion value) and feeds them into Klaravex's internal
  reporting and CRM systems (a Postgres-backed lead/ticket pipeline) for
  attribution and pipeline reporting.

## What it does not do

- Does not manage or access any other advertiser's Google Ads account.
- Does not offer campaign management as a service to third parties.
- Does not share Google Ads account data with any external party outside Klaravex.

## Technical scope

- Read access: campaign/ad group/keyword performance, conversion actions.
- Write access: campaign, ad group, keyword, and ad creation/updates; budget and
  bid adjustments — all scoped to Klaravex's own linked Google Ads account only.
- Authentication: OAuth 2.0 via a Google Cloud Platform project owned by Klaravex,
  developer token issued under Klaravex's own Manager (MCC) account.

## Intended audience

Internal only — Klaravex's own marketing operations. No external users or
customers interact with this tool directly.
