# Klaravex Site Relaunch — Live Deploy Session
**Date:** 2026-06-07
**Target:** klaravex.com (LiteSpeed-cached WordPress, host: cloud86.io)
**Method:** WP Admin (logged in as `kvx_6e383878`), WPCode snippets + Theme File Editor, driven via browser automation.

---

## What went LIVE

### 1. New homepage theme — ACTIVATED
- Theme: **Klaravex** (`klaravex-theme`) — installed + activated (replaced "IT Experts Berlin — Dark Command Center").
- Full new homepage: Syne hero "89% of IT issues resolved before you finish your coffee", stat pills, How It Works, AI capabilities meter, case study cards, **live portal mock dashboard**, CTA.
- Old theme still installed → 1-click rollback if needed.

### 2. Condensed nav (44 → 5)
- New menu **"Klaravex Primary"** (term id 18): Services / How It Works / Results / Client Portal / Contact.
- Assigned to `klaravex-theme` → primary location (nav-menus.php → Manage Locations).

### 3. Klara AI chat widget — REDESIGNED (WPCode snippet #234)
- Renamed Loki → **Klara** (all user-facing). Internal IDs stay `loki-*` for backend compat.
- Dark/indigo design, trust ribbon ("89% resolved here"), quick-reply chips, transparency footer.
- Backend UNTOUCHED: `api.klaravex.com/api/v1/chat/*`, WP proxy, EN/DE i18n, contact tab, GDPR, page suppression.
- Original backed up: `widget/loki-widget-ORIGINAL-backup.js`.

### 4. Global brand polish (WPCode CSS snippet #464)
- Theme accent vars blue `#2563EB` + cyan `#06B6D4` + orange `#FF8A4C` → indigo `#6366F1`/`#818CF8`.
- All headings → Syne. Inline editor colors overridden. Applies site-wide.
- Mobile fixes: heading scale/wrap (no h-scroll), announcement bar.
- New-theme subpage layout (full-width, `.kx-page`).

### 5. Contact page (WPCode CSS #460 + JS #462)
- Form (CF7), Calendly embed, and info card → dark indigo brand.
- Calendly URL dark-themed (`background_color=0B0D15&...`) — edited in page content (page id 15).
- **Form → Calendly flow**: on submit, prefills Calendly with name+email, shows confirmation cue, scrolls to booking.

### 6. Site animations (WPCode JS snippet #463)
- Scroll reveal, hover micro-interactions, stat count-up, page fade. Defensive 2.5s safety net. Respects reduced-motion.

### 7. Subpage fixes (Theme File Editor)
- `page.php` — removed duplicate WP title, removed 800px constraint (full-width).
- `footer.php` — fixed 5 broken (404) links → all 15 verified 200.
- `header.php` — hardcoded clean "K" mark + KLARAVEX wordmark; removed old custom-logo image (`klaravex-logo-dark.png`).

---

## WPCode snippet registry (live)
| ID | Name | Type | State |
|----|------|------|-------|
| 234 | Loki Chat Widget (now Klara) | JS | active |
| 235 | Loki CTA Intercept | JS | active |
| 460 | Contact Page Polish | CSS | active |
| 462 | Contact → Calendly Prefill | JS | active |
| 463 | Site Animations | JS | active |
| 464 | Global Brand Polish | CSS | active |
| 465 | CF7 → Notion | PHP | **INACTIVE — needs token** |
| 467 | ONE-TIME builder (menu/logo) | PHP | inactive (done) |

---

## OPEN ITEMS
1. **Notion token** — DB found (IT Experts Bookings, data source `ee8c2f57-956c-4cf3-af92-f39ff26e94b9`), mapping proven with a test row. Snippet #465 staged inactive. To finish: create Notion integration → share DB with it → paste token in #465 → activate. Field map: your-name→Name, your-company→Company, your-email→Email, your-phone→Phone, your-message→Message, Status→New, Submitted→date.
2. **Rotate WP admin password** — passed through chat session.
3. **Real logo** — currently the "K" mark placeholder; swap if a designed logo exists.
4. **.eu / .es / .de variants** — discussed early, not started. Personal theme built (`themes/klaravex-personal-theme.zip`) but not deployed.
5. Delete Notion test row "TEST — Sarah Chen (delete me)".

## Rollback notes
- Theme: reactivate "IT Experts Berlin — Dark Command Center" in themes.php.
- Widget: restore `widget/loki-widget-ORIGINAL-backup.js` into snippet #234.
- All polish is in WPCode snippets — deactivate individually to revert.
