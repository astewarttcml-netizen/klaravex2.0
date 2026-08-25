# WordPress Publish Checklist — for Loki
**Target:** klaravex.com · Cloud86 shared hosting · Kadence + kadence-child · WP 7.0
**Path:** Plesk → Websites & Domains → Klaravex.com → WordPress tab → WP Toolkit
**Rule of the road:** build everything as **DRAFT**, never live-edit a published page. Anthony reviews, then publishes.

---

## 0. Before touching pages
1. **Take a full Cloud86 backup** (Plesk → Backup Manager) — restore point before any bulk change.
2. Confirm WP revisions are enabled (they are by default) — every page edit is revertable.
3. Load the **brand spec** into working memory: US-English, USD, "readiness/advisory" not "compliance" in marketing, AI-transparent, no Berlin/NIS2/DSGVO on .com.
4. Build the **service-page template** first (see `04-...md` Part 3) and save as a reusable Kadence pattern. Every service page derives from it.

## 1. Publish order (priority = revenue + market fit)
Build/refresh in this sequence; each is a DRAFT until Anthony approves.

| # | Page | Source copy | Why this order |
|---|---|---|---|
| 1 | Homepage edits (AI band, 24/7 stat, security-forward hero) | `02` A1–A3, `07` framing | Front door; sets positioning |
| 2 | /how-our-ai-works/ | `02` B | Transparency = trust differentiator |
| 3 | /business/services/managed-security-mdr/ | `07` 1A | #1 market demand |
| 4 | /business/services/cyber-insurance-readiness/ | `07` 1B | Lead magnet — makes phone ring |
| 5 | /managed-it-plans/ (re-tier + corrected pricing) | `07` Part 2 | Converts visitors to plans |
| 6 | /business/services/security-awareness-training/ | `07` 1C | Recurring margin |
| 7 | /business/services/aws-cloud/ + /google-workspace/ + /ai-workflow-automation/ | `02` C1–C3 | Multi-cloud + AI moat |
| 8 | Remaining 14 ported service pages (Americanized) | itexperts source + `02` E | Depth |
| 9 | /about/ (US entity + founder story) | `02` F | Story = brand |
| 10 | /personal/ hub + it-help + resume-job-search + tech-kit | `02` D1–D5, `04` | Consumer revenue (cash-now) |
| 11 | /personal/pricing/ | `04` Part 2 | Conversion |
| 12 | Legal: Privacy (CCPA+GDPR-as-processor), Terms, DPA | (needs counsel) | Compliance |
| — | **/personal/scam-recovery/** | `02` D4 | **HOLD — do not publish until E&O bound + counsel sign-off** |

## 2. Per-page build steps (repeat for each)
1. Pages → Add New → apply the service-page template pattern.
2. Paste copy from the source file; keep H1/section order from the template.
3. Set the URL slug to match the IA in `01-...md` §5 exactly.
4. Add SEO title + meta description (provided in source where noted).
5. Internal-link: every service page → /managed-it-plans/ and /contact/ (Free Assessment).
6. Set status = **Draft**. Do not publish.

## 3. Americanization grep gate (MANDATORY before any publish)
For each page, search the content for these — **must be zero hits:**
`€`, `EUR`, `NIS2`, `DSGVO`, `Berlin`, `Impressum`, `Datenschutz`, `optimise`, `centre`, `organisation`, `English-speaking`
Also confirm: the word "compliance" does not appear in marketing copy (use "readiness/advisory"); phone is the US business line, not the old `wa.me/...` WhatsApp.

## 4. Navigation
Update the primary menu to the `01-...md` §5 structure: Business (Services / Industries / Plans / Pricing / Contact) · How It Works · About · Personal. Remove dead links — every menu item must resolve to a real page (no "coming soon").

## 5. Final pre-launch validation (Anthony reviews)
- [ ] Every nav + in-page link resolves (no 404, no "#")
- [ ] Mobile renders cleanly (Kadence preview at phone width)
- [ ] Grep gate passed on all pages
- [ ] Pricing matches `07` (Foundation $100 / Assurance $165 / Directive $295)
- [ ] Forms deliver to hello@ / support@klaravex.com
- [ ] Footer has legal links
- [ ] Scam-recovery page still unpublished pending E&O + counsel
- [ ] Loki backend points to the KB so it can cite the new articles

## 6. Known WP-CLI gotcha (from CLAUDE.md)
The WP-CLI UI tokenizer splits on spaces and strips `()`. Use the chip-based subcommand selector + single-word args only. Prefer the WP admin GUI for page builds; reserve CLI for bulk slug/menu ops.

## 7. After publish
- Submit sitemap.xml to Google Search Console.
- Add schema markup (Organization, Service, FAQ) — see SEO skill.
- Set up analytics + form-conversion tracking.
- Offer Anthony a scheduled weekly "site + lead" digest.
