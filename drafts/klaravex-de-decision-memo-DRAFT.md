# DECISION MEMO — What should klaravex.com be?

**Status:** Draft for decision. No site changes made.
**Prepared:** 2026-06-08
**Owner:** Anthony
**Decision required:** Resolve the brand/strategy conflict created by klaravex.com in its current form.

---

## Objective

Determine the correct role of `klaravex.com` and eliminate the current brand collision, before it absorbs SEO authority, ad spend, or client trust under an unresolved identity.

## Background / current state

`klaravex.com` is live and is, in substance, a re-skinned copy of `klaravex.com`:

- Leads with **NIS2** ("in force since December 2025"), **DSGVO compliance**, Berlin-local positioning.
- Contains a section literally headed **"why IT Experts Berlin."**
- Carries `@ITExpertsBerlin` (Twitter) and `facebook.com/itexperts.berlin` (publisher) metadata.
- Links a NIS2 checklist hosted on **klaravex.com**.
- WhatsApp contact is a **placeholder/non-routable number** (`wa.me/15559823944` — 555 prefix).
- No visible **Impressum** (§5 DDG) or DSGVO notice in nav/footer.

## Conflict with documented strategy (CLAUDE.md)

| Documented rule | klaravex.com reality |
|---|---|
| NIS2 / DORA / German regulatory belong to **klaravex.com**, NOT the Klaravex brand | klaravex.com leads with NIS2 + DSGVO |
| klaravex.com operates **independently**, keeps its own brand, **not** migrating to Klaravex | klaravex.com is itexperts-berlin content under the Klaravex name |
| Registered domains: .com / .io / .eu | .de was not in the planned set |
| klaravex.com leads US; EU served under DPA, EU entity visa-gated | .de presents as a Berlin-local German consultancy |

**Bottom line:** klaravex.com is currently the one thing the strategy explicitly tried to avoid — a third hybrid brand that blurs the line between Klaravex (US) and IT Experts Berlin (DE).

---

## Options

### Option A — Redirect klaravex.com → klaravex.com (301)
Treat .de as a defensive domain only; the German market stays under the established IT Experts Berlin brand.

- **Pros:** Honors the documented separation exactly. Consolidates German SEO into the entity that already ranks. Zero brand confusion. Cheapest to maintain.
- **Cons:** "Klaravex" gains no German-language footprint (but per strategy, it isn't supposed to yet — EU is visa-gated).
- **Migration risk:** Low. A 301 preserves any link equity.

### Option B — Redirect klaravex.com → klaravex.com (301)
Pure defensive hold pointing at the US flagship.

- **Pros:** Simple. Protects the spelling. No second German brand.
- **Cons:** Sends German-intent visitors to a US-positioned page (poor fit, high bounce). Wastes any German content already indexed.
- **Migration risk:** Low.

### Option C — Rebuild klaravex.com as a clean German-language Klaravex storefront
Strip all "IT Experts Berlin" references; run it as the EU face of Klaravex.

- **Pros:** Gives Klaravex a real EU presence.
- **Cons:** Directly contradicts the visa-gated EU strategy and the "don't lead with NIS2/DORA" rule. Creates **two competing German consultancies** (klaravex.com vs. klaravex.com) chasing the same Berlin SMB keyword set — they cannibalize each other. Triggers German entity/tax/Impressum obligations now. Highest cost, highest risk.
- **Migration risk:** High — competes with your own established property.

### Option D — Leave as-is
- **Pros:** None.
- **Cons:** Live placeholder phone number, missing Impressum (Abmahnung exposure), dual-brand confusion, SEO split with klaravex.com.
- **Verdict:** Not viable.

---

## Recommendation

**Option A — 301 redirect klaravex.com → klaravex.com.**

Rationale: it is the only option that matches the strategy you already committed to writing. The German market has an established vehicle (klaravex.com); a second German brand splits authority and invites the exact NIS2/DORA scope-creep your own rules fence off from Klaravex. Keep klaravex.com as a defensive registration that funnels to the German entity. Revisit only if/when the EU entity is formed post-visa — at which point a clean Klaravex-EU build (Option C) becomes coherent.

**If you want a German-language Klaravex page now anyway** (against the documented strategy), do it as a single page under klaravex.com/de or klaravex.eu — not as a standalone .de that competes head-to-head with klaravex.com.

---

## Immediate remediation (independent of the A/B/C decision)

These are live defects to fix regardless of what klaravex.com ultimately becomes:

1. **Placeholder phone** `wa.me/15559823944` — dead contact path. Remove or replace.
2. **Missing Impressum / DSGVO notice** — legal requirement for any German-facing page. Confirm or add.
3. **Cross-brand metadata** — `@ITExpertsBerlin`, facebook publisher tag, klaravex.com checklist link — inconsistent NAP harms local SEO.
4. **personal.klaravex.com** returns empty — deploy or remove the DNS record so it isn't a hanging subdomain.

## Risks of inaction
- **Legal:** Missing Impressum = Abmahnung risk (German competitors/law firms actively pursue these).
- **SEO:** Two near-identical German sites split ranking signal and may trigger duplicate-content suppression.
- **Trust:** A live placeholder phone number on a consultancy site signals neglect to exactly the SMB buyers you want.

## Rollback
A 301 redirect is fully reversible — remove the redirect rule to restore the standalone site. No data loss. Recommend snapshotting current klaravex.com content before any redirect so it can be repurposed later.

---

## Decision

- [ ] Option A — redirect to klaravex.com (recommended)
- [ ] Option B — redirect to klaravex.com
- [ ] Option C — clean German Klaravex rebuild (against current strategy)
- [ ] Remediation items 1–4 actioned regardless
