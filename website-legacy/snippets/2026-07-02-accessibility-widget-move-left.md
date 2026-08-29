# T14.24 · Accessibility widget → bottom-left

**Date:** 2026-07-02
**Problem:** Civic-style accessibility widget bubble collides with the Loki (Klara) chat bubble at the bottom-right of every page on klaravex.com.
**Fix:** move the accessibility widget to the bottom-left via CSS override. Klara chat stays bottom-right (primary conversion CTA).

## 1. Preferred — plugin setting

If the plugin exposes a "Position" or "Placement" option:
- WordPress Admin → the plugin's settings page → Position → **Bottom-Left**
- Save.

If that option exists, use it and skip the CSS. Plugin-native positioning is more robust than CSS overrides.

## 2. Fallback — CSS override

Paste this into **one** of:
- Kadence Theme Options → Advanced → Custom CSS
- WPCode → Add Snippet → CSS → Site-wide → Active
- Elementor Custom CSS (if you use Elementor)
- `functions.php` via a `wp_head` action hook (last resort)

```css
/* Klaravex: move accessibility widget to bottom-left so it doesn't collide with the Klara chat bubble.
   Covers the common selectors used by Civic, UserWay, accessiBe, EqualWeb, and generic WP accessibility widgets. */

/* 1) Civic-style / generic id selectors */
#civic-accessibility,
#civic_accessibility_widget,
#accessibility-widget,
#accessibility_widget,
[id^="civic-accessibility"] {
  left: 24px !important;
  right: auto !important;
  bottom: 24px !important;
}

/* 2) UserWay */
.userway_buttons_wrapper,
[data-uw-widget],
#userway-widget-wrapper,
iframe[title="accessibility widget"] {
  left: 24px !important;
  right: auto !important;
  bottom: 24px !important;
}

/* 3) accessiBe */
.acsb-widget,
[data-acsb-widget],
#accessibility-menu-launcher,
[aria-label="accessibility menu"] {
  left: 24px !important;
  right: auto !important;
  bottom: 24px !important;
}

/* 4) EqualWeb + generic aria-labelled iframes */
[aria-label*="accessibility" i][role="button"],
iframe[title*="accessibility" i] {
  left: 24px !important;
  right: auto !important;
  bottom: 24px !important;
}

/* 5) One-web-accessibility, WP Accessibility Helper */
#owa-widget,
#wpah-icons,
.wpah-widget {
  left: 24px !important;
  right: auto !important;
  bottom: 24px !important;
}

/* 6) Ensure the widget stays above other bottom-left elements (footer, cookie banner) */
[id^="civic-accessibility"],
.userway_buttons_wrapper,
.acsb-widget,
#owa-widget,
.wpah-widget,
[data-uw-widget] {
  z-index: 2147483000 !important;   /* just under absolute max so cookie modals can still overlay */
}
```

## 3. JS fallback (only if the plugin's iframe wrapper resists CSS)

Some accessibility widgets create their bubble inside a Shadow DOM or iframe with inline styles that beat CSS. If the CSS above doesn't take effect, add this JS snippet **as well** (WPCode → JS → footer, site-wide):

```html
<script>
(function () {
    'use strict';
    var SELECTORS = [
        '#civic-accessibility',
        '#accessibility-widget',
        '.userway_buttons_wrapper',
        '[data-uw-widget]',
        '.acsb-widget',
        '#owa-widget',
        '.wpah-widget',
        'iframe[title*="accessibility" i]',
        '[aria-label*="accessibility" i][role="button"]'
    ];
    function moveLeft(el) {
        if (!el || !el.style) return;
        el.style.setProperty('left', '24px', 'important');
        el.style.setProperty('right', 'auto', 'important');
        el.style.setProperty('bottom', '24px', 'important');
    }
    function scan() {
        SELECTORS.forEach(function (sel) {
            try {
                var nodes = document.querySelectorAll(sel);
                for (var i = 0; i < nodes.length; i++) moveLeft(nodes[i]);
            } catch (e) { /* selector may not be supported in some old browsers */ }
        });
    }
    // Run on DOM ready + after plugin injects itself + every 2s for the first 20s.
    if (document.readyState !== 'loading') scan();
    else document.addEventListener('DOMContentLoaded', scan);
    var tries = 0;
    var interval = setInterval(function () {
        scan();
        if (++tries > 10) clearInterval(interval);
    }, 2000);
})();
</script>
```

## 4. Verification

After paste + WP cache purge:
1. Reload klaravex.com in an incognito tab
2. Accessibility bubble should now sit at bottom-left
3. Klara chat bubble should still be bottom-right
4. Both should be tappable — no overlap
5. Test at 320px viewport (mobile) — both should still fit without stacking

## 5. Which selector matched?

If you want to know which specific widget you have (helps future-proofing), run this in the browser console on klaravex.com:

```js
['#civic-accessibility','#accessibility-widget','.userway_buttons_wrapper','[data-uw-widget]','.acsb-widget','#owa-widget','.wpah-widget'].forEach(s => console.log(s, document.querySelectorAll(s).length));
```

The line reporting `1` (or more) is the selector Klaravex's plugin actually uses. Trim the CSS above to just that block if you want a cleaner override.

## 6. If neither of the above works

Send the widget vendor name (usually in the footer of the Accessibility menu or on the plugin's line in WP Admin → Plugins). Loki can write a targeted rule for that specific plugin's selectors.

---

*Paste-ready. Klara chat bubble untouched — keeps its bottom-right conversion position.*
