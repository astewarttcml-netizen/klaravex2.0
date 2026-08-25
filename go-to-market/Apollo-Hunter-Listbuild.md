# Klaravex — List Building with Apollo + Hunter.io → Smartlead
Workflow: Apollo (find people) → export → Hunter (find missing + VERIFY all) → keep only valid → map to Smartlead CSV → assign to campaign.
RULE: use Apollo for DATA ONLY. Send from Smartlead (warmed secondary domain), not Apollo — protects deliverability and uses the tool you're paying for.

═══════════════════════════════════════════════
APOLLO — People Search filters (one saved search per segment)
═══════════════════════════════════════════════

▶ SEGMENT 1 — US BOOKKEEPER / FRACTIONAL CFO
- Person Titles: Bookkeeper, Owner, Founder, Fractional CFO, Accountant, Managing Member, Principal
- # Employees (company): 1–10
- Industry: Accounting
- Location: United States  (start with 3–4 metros you want to serve)
- Keywords (company/person): "bookkeeping", "QuickBooks", "fractional CFO"
- Exclude: large CPA firms (set employees ≤10), staff-level titles
- Tip: boutique/solo firms convert best — they personally own the client relationship.

▶ SEGMENT 2 — CYBER / COMMERCIAL INSURANCE BROKER
- Person Titles: Insurance Broker, Insurance Agent, Producer, Account Executive, Commercial Lines, Agency Owner, Principal
- # Employees: 1–50
- Industry: Insurance
- Location: United States
- Keywords: "commercial insurance", "business insurance", "cyber"
- Exclude: captive agents (e.g. State Farm/Allstate single-carrier) — target INDEPENDENT agencies (they can refer freely)

▶ SEGMENT 3 — BERLIN STEUERBERATER  (data only → outreach via LinkedIn, not cold email)
- Person Titles: Steuerberater, Partner, Inhaber, Geschäftsführer
- # Employees: 1–10
- Industry: Accounting
- Location: Berlin, Germany
- Keywords: "Steuerberater", "Steuerkanzlei"
- Use Apollo to FIND them + grab LinkedIn URLs; do outreach on LinkedIn (UWG — no DE cold email).

For each: Save Search → Select all → Export CSV (gives name, title, company, email if found, LinkedIn, location).

═══════════════════════════════════════════════
HUNTER.IO — find missing + verify (the deliverability step)
═══════════════════════════════════════════════
1. For any Apollo row WITHOUT an email: Hunter **Email Finder** (first name + last name + company domain) or **Domain Search** for the firm.
2. Run the ENTIRE list through Hunter **Email Verifier** (bulk). KEEP only status = "valid". Drop "invalid" and most "accept-all/risky".
   → Verified list = bounce rate <3% = Smartlead stays out of spam. This step is non-negotiable.
3. (Hunter Chrome extension also pulls emails straight off company sites/LinkedIn for one-offs.)

═══════════════════════════════════════════════
MAP TO SMARTLEAD CSV (headers from Smartlead-leadlist-TEMPLATE.csv)
═══════════════════════════════════════════════
email,first_name,last_name,company,segment,personalization,linkedin_url,city
- email          ← Hunter-verified email
- first_name     ← Apollo
- company        ← Apollo
- segment        ← bookkeeper | insurance_broker | steuerberater_LINKEDIN_ONLY
- personalization← one specific detail (their niche/city/client type) — write it per lead or in bulk per segment
- linkedin_url   ← Apollo (use for LinkedIn-only segment + pairing)

═══════════════════════════════════════════════
DAILY FLOW (solo)
═══════════════════════════════════════════════
- Pull ~50–100 Apollo leads/segment → verify in Hunter → keep valid → upload to the matching Smartlead campaign.
- Smartlead drips them at your ramped daily cap (don't dump 500 at once — feed the campaign).
- Berlin list → LinkedIn connection requests (10–20/day) instead.
