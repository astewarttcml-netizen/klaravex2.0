# Packaged Offer — "IT + WISP Compliance for CPA Firms" (Accounting Vertical)

**Task:** `stratex-accounting-vertical-2026-08-17` (competitive-intel finding #4)
**Author:** Loki (host-session orchestrator)
**Date:** 2026-08-18
**Status:** OFFER SPEC — pending Anthony approval before publishing/pricing surfaces

---

## 1. The vertical thesis (why accounting first)

Accounting is the best-defined vertical because it has a **regulatory forcing
function with a hard deadline**: every e-file ERO is required by the IRS to
maintain a written information security plan (WISP, IRS Pub 4557), and the FTC
GLBA Safeguards Rule requires a formal written information security program.
A tax-season incident (partner lockout, phishing, lost laptop) is both an
availability crisis and a compliance failure. Competitors (Verito, Rightworks,
Cetrom) have already validated the spend band at **$129–249/user**.

Klaravex already lists "accounting" but does not sell it differently. This offer
packages the existing capabilities into a single, vertical-specific bundle.

## 2. Pricing reconciliation (binding)

- **Competitor anchor:** Verito / Rightworks / Cetrom publish **$129–249/user**.
- **Klaravex live tiers (authoritative, Anthony, 2026-08-16):** Foundation $49 /
  Assurance $79 / Directive $129 per user/mo.
- **Directive from `stratex-b2b-pricing`:** "use my pricing" — do NOT change the
  live tiers. The $129–249 competitor range is the *anchor we compare against*,
  not a target we copy.

**Strategic result:** Klaravex's **Directive tier at $129/user is the *bottom*
of the competitor band** and bundles compliance readiness the competitors sell
separately. That is the win: "Verito charges $129–249/user for hosted software
*plus* you still need compliance help — Klaravex gives you the full IT stack,
security, and WISP/GLBA readiness at $129/user."

## 3. The packaged offer (sub-30-staff CPA firms)

Name (internal): **"Accounting Directive"** — a compliance-forward bundle built
on the Directive tier, scoped and messaged for firms ≤ 30 staff.

### 3.1 What's included (maps to existing Directive $129/user)

| Pillar | Deliverable | Maps to |
|---|---|---|
| **Daily IT** | Workstations, M365/Google Workspace, tax software (CCH, Drake, Lacerte, ProSeries, UltraTax), client portals, Wi-Fi/VPN, printers — patched, monitored, fixed | Foundation+ |
| **Security** | EDR/MDR, managed firewall, phishing-resistant MFA, dark-web monitoring of staff/partner credentials, IR playbook | Assurance+ |
| **WISP / compliance readiness** | Written Information Security Plan (IRS Pub 4557 + e-file ERO), GLBA Safeguards mapping, quarterly refresh of controls documentation | **Directive (the differentiator)** |
| **vCISO-lite** | Designated qualified individual guidance, quarterly posture review, auditor-ready evidence handoff | Directive |
| **Tax-season surge** | Priority SLA during Jan–Apr filing window; same-hour senior engineer escalation | Value-add |

### 3.2 Recommended price anchor (do NOT alter live tiers)

- **Lead pitch price: Directive $129/user/mo** — positioned as "at the bottom of
  what hosted-CPA-software vendors charge (~$129–249/user) *before* you add the
  compliance work."
- Secondary anchor for smaller firms (≤ 10 staff): **Assurance $79/user** for
  firms that already have a WISP and only need the security/IT layer.
- **One-time onboarding** (optional, from existing SKU): WISP gap-analysis /
  initial WISP drafting quoted separately (matches the existing one-time
  catalog — do not fold into the $129 recurring unless Anthony approves).

## 4. Positioning (voice-policy clean, US "we")

> **"The WISP won't write itself. Your tax software won't answer the phone
> during lockout. We handle both."**

Supporting subhead:

> "We run the IT, security, and IRS Pub 4557 / GLBA Safeguards readiness for
> firms of 5 to 50 people — a named US engineer owns your account, and our AI
> resolves the routine before it ever becomes a ticket. From $129 per user per
> month, flat, no surprises."

*(Reuses the expert-led + AI-accelerated framing from the positioning memo;
drops the unsourced "89%"; leads with the regulatory forcing function.)*

## 5. What's already built vs. what's left

- ✅ **Landing-page copy exists** (`.private/drafts/cpa-landing-page-wp-blocks.md`)
  — needs a pricing section + WISP emphasis added, and the "89%" claims softened
  per the `89pct-claim` memo.
- ✅ **Keyword/negative-keyword sets exist** (`.private/drafts/google-ads-cpa-keywords.csv`,
  `-negatives.csv`).
- ⬜ **Publish the pricing block** on the CPA landing page (adds the $129/user
  Directive anchor + the "vs $129–249" comparison).
- ⬜ **WISP deliverable template** for the readiness pillar (a reusable WISP
  skeleton the Directive tier delivers) — net-new asset.
- ⬜ **Sales one-pager** for the 30-min discovery call (the "compare vs Verito"
  table).

## 6. Decisions requested

| # | Question | Options |
|---|---|---|
| 1 | Approve "Accounting Directive" as the vertical offer name + $129/user (Directive) lead anchor? | Approve / rename / different anchor |
| 2 | Add the pricing/comparison block to the existing CPA landing page? | Yes (I'll PATCH WP) / Hold |
| 3 | Authorize building a reusable WISP skeleton deliverable? | Yes / Hold |
| 4 | Fold WISP drafting into the $129 recurring, or keep it as separate one-time? | Recurring / separate one-time (recommended) |

No site change made. This is an offer spec for Anthony's approval; the live
pricing tiers remain unchanged.
