# Klaravex Site Images — Deploy Guide

All 8 images are generated, optimized (~250 KB), and HOSTED at stable public URLs on klaravex.com:

| Site | Hero image URL | Section image URL |
|------|----------------|-------------------|
| klaravex.com | …/klaravex-com-hero.jpg ✅ LIVE | …/klaravex-com-section.jpg |
| personal.klaravex.com | …/personal-com-hero.jpg | …/personal-com-section.jpg |
| klaravex.com | …/klaravex-de-hero.jpg | …/klaravex-de-section.jpg |
| personal.klaravex.com | …/personal-de-hero.jpg | …/personal-de-section.jpg |

Base path = `https://klaravex.com/wp-content/uploads/2026/06/`
Local copies: `klaravex/site-images/web/*.jpg`

---
## ✅ DONE
**klaravex.com** — hero is LIVE (set via Customizer → Additional CSS). Also fixed the broken hero-bg 404.

---
## TO FINISH each remaining site (≈30 sec each)
Log into that site's **WP Admin → Appearance → Customize → Additional CSS**, paste the rule, **Publish**.

### personal.klaravex.com
(uses the same `--hero-photo-url` pattern — this also fixes its hero 404)
```css
.hero-photo{--hero-photo-url:url('https://klaravex.com/wp-content/uploads/2026/06/personal-com-hero.jpg') !important;}
```

### klaravex.com  (hero container = `.hero-body`)
```css
.hero-body{
  background-image:linear-gradient(rgba(10,12,20,.72),rgba(10,12,20,.86)),
    url('https://klaravex.com/wp-content/uploads/2026/06/klaravex-de-hero.jpg');
  background-size:cover; background-position:center;
}
```

### personal.klaravex.com  (hero container = `.hero-body`, lighter overlay for the warm photo)
```css
.hero-body{
  background-image:linear-gradient(rgba(12,14,22,.50),rgba(12,14,22,.74)),
    url('https://klaravex.com/wp-content/uploads/2026/06/personal-de-hero.jpg');
  background-size:cover; background-position:center;
}
```

> Tip: for a self-hosted copy on each domain, upload the matching `web/*.jpg` to that site's
> Media Library and swap the URL — but the klaravex.com-hosted URLs work cross-domain as-is.

---
## Phase 2 (optional) — section images
The four `*-section.jpg` (dashboard / EU-sovereignty / help scenes) are hosted and ready to drop
behind a content section once heroes are confirmed.
