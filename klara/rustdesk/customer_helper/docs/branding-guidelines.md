# Klaravex Customer Helper — Branding Guidelines

This document defines the brand surface for the one-time customer
helper. It is downstream of `brand/brand-strategy.md` (the master) — when
they disagree, the master wins; this doc gets updated.

## Why a separate guideline doc

The helper is the **first software-product surface** a paying Klaravex
customer ever sees. It is launched in the moments of highest tension:
something is broken, the customer just paid, and they're trusting us with
keyboard + mouse access to their machine. Every brand decision has to
support **trust + clarity + competence**, not delight or marketing flair.

The marketing site can have animation, gradients, hero imagery — the
helper cannot. Hold the line.

## Voice & tone

| Trait | Show | Avoid |
|---|---|---|
| Direct | "You're connected." | "Awesome, you're all set!" |
| AI-transparent | "Klara (AI) is controlling your computer" | "Klaravex is on it!" |
| Calm | Single sentence per state | Multiple paragraphs / FAQ-style |
| Competent | "Configuring the secure connection." | "Setting things up…" |

## Type

- **Family:** Inter, system fallback chain.
- **Sizes:** 20px for state headlines, 14px body, 11px legal microcopy,
  12.5px indicator label.
- **Weight:** 600 for headlines + indicator label; 400 elsewhere.
- **Never** use weight 700+ in the helper. The bold UI is the brand
  marker; thicker fonts read as system-alert.

## Color

All colors live in `branding/colors.toml`. Hex values:

| Token | Hex | Use |
|---|---|---|
| `bg` | `#0D1117` | Main background. Identical to klaravex.com hero. |
| `surface` | `#161B22` | Cards, panels, input fields. |
| `border` | `#30363D` | Hairline dividers only. |
| `text` | `#F3F4F6` | Primary copy. |
| `muted` | `#9CA3AF` | Secondary copy, legal microcopy. |
| `accent_1` → `accent_2` | `#6366F1` → `#7C3AED` | CTA gradient, only on primary buttons. |
| `success` | `#10B981` | "You're connected" check icon. |
| `danger` | `#DC2626` | STOP button. |
| `indicator` | `#EF4444` | Pulse dot. Slightly brighter than `danger` so it stays legible against any wallpaper. |

**Forbidden:** any color outside this list. No additional accents. No
custom shades for individual states.

## Logo usage

- The **icon** (gradient K mark on dark) is the only mark used in the
  helper.
- It appears at exactly two sizes: 28×28 in the brand bar, 32×32 in the
  Dock/taskbar icon. Never scaled below 24×24 (the gradient breaks).
- The wordmark is NOT used in the helper. Customers already know they're
  in Klaravex Support; redundant branding feels like marketing.

## The indicator overlay

The indicator is the most important brand surface in the helper. It is
the only thing the customer sees once the session is active. Design
rules:

1. **Always-on-top** across every display, even fullscreen video. This
   is a trust signal — disappearing during a Netflix episode would
   suggest we hid surveillance.
2. **Pulsing red dot** + label. The pulse is 1.6s ease-out, animation-
   paused when `prefers-reduced-motion: reduce` is set.
3. **STOP button** — `#DC2626` background, white text, 700 weight, 11.5px
   letterspacing 0.6px. This is the ONE place we use heavier type.
4. **Draggable** via the badge area; the STOP button is `-webkit-app-
   region: no-drag` so accidental drags don't trigger the button.
5. **Never** uses transparency below 0.85 — it must be readable against
   white desktops.
6. **Never** auto-hides. Even after 4 hours of session it stays put.
7. Default copy: `"AI is controlling your computer"` →
   `"Klara (AI) is controlling your computer"` once `operator_label`
   is delivered → `"<Operator Name> is controlling your computer"` when
   a human takes over.

## Permission prompts

macOS Screen Recording and Accessibility prompts use the strings in
`macos/Info.plist.template`. The text is **the customer's first read of
Klaravex** in a system dialog — every word matters. Rules:

- Lead with what we DO ("share your screen") not what we NEED.
- Name Klara explicitly so the prompt matches the indicator overlay.
- End with the session-ends-when-closed promise.

## What this helper must NOT do

- No telemetry beyond the redeem-API call. No analytics SDK. No crash
  reporter that uploads without explicit prompt. (If we add Sentry
  later, it must be opt-in per session.)
- No auto-update mechanism. The token has a 30-minute TTL — the helper
  is downloaded fresh every session. If we shipped auto-update we'd
  defeat the "wipes on close" property.
- No persistent state outside the per-session config file (which is
  wiped on exit).
- No mention of "AI" hidden behind "smart assistant" or similar
  euphemisms. Brand voice rule #3: AI-transparent.
- No defense / DIB / CMMC vocabulary anywhere in the helper UI. Out of
  scope per `brand/brand-strategy.md`.

## Localization

- `strings.en.toml` — US (klaravex.com) customers. This is the sole
  required locale file.
- The helper always uses English strings. Locale auto-detection was
  removed with the Germany cleanup; the `--locale` CLI flag and
  `KLARAVEX_LOCALE` env var are accepted but unused.

Add `strings.fr.toml`, `strings.es.toml`, etc. when needed. The schema
is the same; every key MUST be translated (no fallback merging).

## Accessibility floor

- All interactive elements have `aria-label` or visible text.
- Focus indicators on the STOP button use `outline: 2px solid #F3F4F6`
  (high contrast against the dark badge).
- Pulse animation respects `prefers-reduced-motion`.
- All copy ≥ 14px (body) or ≥ 11px (legal microcopy at WCAG-acceptable
  contrast `#9CA3AF on #0D1117` = 5.74:1).
- Keyboard: Tab cycles between input → Continue button. Indicator
  overlay is not focusable from the main webview to prevent accidental
  STOP via Tab+Enter.
