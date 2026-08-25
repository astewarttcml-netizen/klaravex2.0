# Klaravex Ads Management Tool — Google Ads API Design Document

## Purpose
An internal tool used by Klaravex LLC (managed IT, security, and compliance-readiness advisory for US small businesses — klaravex.com) to programmatically review and manage its own Google Ads campaigns. The tool is used exclusively by Klaravex staff to monitor and optimize the company's own advertising spend; it is not offered as a product or service to external clients.

## Intended use of the Google Ads API
- Create and launch new Search and Performance Max campaigns for Klaravex's own service lines as they are introduced or refined.
- Retrieve campaign, ad group, and keyword performance metrics (impressions, clicks, cost, conversions) for reporting and analysis.
- Review and adjust bids, budgets, and campaign status for Klaravex's own Search and Performance Max campaigns.
- Pull search-term and audience data to refine targeting for Klaravex's core service lines (managed security, HIPAA/SOC 2/ISO 27001 readiness advisory, M365/Google Workspace/AWS management, Ubiquiti UniFi network management) aimed at target verticals (healthcare, legal, financial, and other regulated SMBs).
- Consolidate performance data alongside other marketing channels (organic social, cold outreach) already integrated into Klaravex's internal systems, for unified reporting.

## Campaign types supported
Search and Performance Max.

## Access model
- Internal use only. Access is restricted to Klaravex employees/contractors managing the company's own advertising account(s).
- No external users, clients, or third parties will have access to the tool or the API token.

## Technical implementation
- Built directly against the official Google Ads API using Google's supported client library (Python: `google-ads`).
- Not a third-party or resold tool — developed and operated in-house by Klaravex.
- Does not use the App Conversion Tracking and Remarketing API; Klaravex is a services business, not a mobile app publisher.

## Data handling
- Only Klaravex's own Google Ads account data is accessed — no client or third-party account data.
- Credentials (OAuth client secret, refresh token, developer token) are stored in a private, access-controlled credential vault and are never exposed in code, logs, or client-facing surfaces.
