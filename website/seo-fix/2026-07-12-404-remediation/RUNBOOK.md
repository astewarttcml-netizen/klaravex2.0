# GSC 404 + Redirect Remediation — 2026-07-12

**Source:** Google Search Console reports (2026-07-12)
**Findings:** 6 real 404s (of 10 flagged) + `/hello-world/` WordPress default sample post still live.
**Verified against:** live curl 2026-07-12 + `page-sitemap.xml`.

## 1. Import redirects (WP-Admin GUI, ~2 min)

1. Log into `klaravex.com/wp-admin`
2. Ensure `Redirection` plugin installed + active (`Tools → Redirection`)
3. `Tools → Redirection → Import/Export → Import`
4. Upload `redirection-plugin-import.json` (in this dir)
5. Confirm group `GSC-2026-07-12-404-remediation` appears with **6 rules**
6. All rules default to enabled. No further clicks needed.

Rules imported (all 301 except last):

| From | To | Code |
|---|---|---|
| `/services/cloud-productivity/` | `/business/services/foundation/` | 301 |
| `/services/network-security/` | `/business/services/assurance/` | 301 |
| `/services/strategy-transformation/` | `/business/services/directive/` | 301 |
| `/personal/identity-data-cleanup/` | `personal.klaravex.com/` | 301 |
| `/personal/scam-recovery/` | `personal.klaravex.com/` | 301 |
| `/de/personal/it-help/` | (410 Gone) | 410 |

The 410 tells Google the DE page is intentionally retired — Search Console will drop it from the index in ~2 crawl cycles. Better than a bare 404 or a redirect to an unrelated page.

## 2. Delete the Hello World sample post (WP-CLI, ~30s)

`/?p=1` currently redirects to `/hello-world/` — that's the default WordPress sample post created at install. Never a real page. Ship-blocker for SEO polish.

```bash
# From the klaravex.com WP install shell (Azure App Service SSH or WP-CLI over Azure Container Apps)
wp post get 1                              # verify it is the Hello World post
wp post delete 1 --force                   # hard delete (skip trash)
wp cache flush                              # invalidate all page caches
```

If WP-CLI unavailable: WP-Admin → Posts → All Posts → find "Hello world!" → Trash → then empty trash.

## 3. Verify (2 min)

```bash
# Should all now redirect 301 → new target (200) in 1 hop:
for u in \
  https://klaravex.com/services/cloud-productivity/ \
  https://klaravex.com/services/network-security/ \
  https://klaravex.com/services/strategy-transformation/ \
  https://klaravex.com/personal/identity-data-cleanup/ \
  https://klaravex.com/personal/scam-recovery/; do
  curl -sS -o /dev/null -m 10 -L -w "%{http_code} <- %{url_effective}\n" "$u"
done

# Should return 410:
curl -sS -o /dev/null -m 10 -w "%{http_code}\n" https://klaravex.com/de/personal/it-help/

# Hello-world post gone:
curl -sS -o /dev/null -m 10 -L -w "%{http_code} <- %{url_effective}\n" "https://klaravex.com/?p=1"
```

## 4. Notify Google (1 min)

1. GSC → **Sitemaps** → resubmit `https://klaravex.com/sitemap_index.xml`
2. GSC → **URL Inspection** → for each of the 6 remediated URLs → click **Request Indexing** (individually — GSC rate-limits to ~10/day, so plan across two sessions if needed)
3. GSC → **Page Indexing → Not Found (404)** report — the 6 old URLs should move to `Excluded → Redirected` or `Excluded → Not found (Gone)` within 1-2 crawl cycles (typically 3-14 days)

## 5. Not fixed in this pass — flag for follow-up

- `/wp-content/*` GSC entry — GSC's wildcard hides the specific asset URLs. Need to open the GSC report and see which assets are actually 404-ing. If it's just directory-index requests (`/wp-content/uploads/`), those correctly return 403 and can be ignored. If it's specific asset files (`.jpg`/`.css`), those either need restoring or the linking pages need updating.
- Google reports 10 URLs with active redirects (contact, personal/, cyber-insurance, www→apex, privacy variants, ?p=1). All verified healthy — 1 hop → 200. No fix needed; GSC report is informational. `?p=1 → /hello-world/` covered by Part 2 (deleting the post makes `?p=1` return 404, then GSC drops the reference).
