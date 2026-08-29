# website-legacy — DO NOT DEPLOY

**Archived 2026-08-29.** This Bun/React SPA is an older, divergent version of the
Klaravex marketing site. It is **not** connected to the live site.

## The live site is WordPress

klaravex.com runs on WordPress (custom `klaravex-theme`, Rank Math, LiteSpeed,
Contact Form 7, Code Snippets). All edits go through the WP REST API or the
theme's PHP templates — never through this directory.

## Why this was archived

- **Stale pricing**: $100/$165/$295 tiers here vs. $49/$79/$129 live.
- **Stale positioning**: "Managed Security & Regulatory Readiness" vs. the live
  "89% AI / 11% human" AI-first MSP positioning.
- **Stale verticals and CTAs**: "Book a discovery call" / mailto contact vs.
  live "Free IT Assessment" funnel with a working CF7 form.
- Deploying this stack would regress the live site (30+ indexed pages, Rank
  Math schema, chat widget, working forms).

## If you need something from here

The `copy/` docs and `faq.html` were partially mined for the live `/faq/` page
(rewritten to current positioning before publishing). Treat everything else as
historical reference only. Broken absolute symlinks (`favicon.png`,
`og-image.png` → old macOS paths) were left as-is; real assets live in
`brand/exports/`.
