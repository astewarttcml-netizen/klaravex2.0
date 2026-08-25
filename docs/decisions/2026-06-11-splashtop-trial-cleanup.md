# Decision: Splashtop EU trial cleanup (2026-06-11)

## Context

Tonight (2026-06-11) Anthony signed up for a "SOS - 300 & Access Performance" trial in the Splashtop EU portal (`my.splashtop.eu`), hoping it could replace the now-dead Atera→Splashtop SOS bridge. The trial converts to a paid subscription in 7 days (2026-06-18). Investigation of the EU portal and the Splashtop API documentation confirmed that the self-serve tier exposes no generic REST API — only six helpdesk integrations (ServiceNow, Zendesk, Freshservice, Freshdesk, Jira, Salesforce) — so the AI-controlled remote session product cannot be built on top of it. Sales-led options (Enterprise REST, OEM SDK) were also ruled out tonight as too expensive and slow for the current stage.

## What we learned tonight

- Self-serve Splashtop SOS tiers (including the "300 & Access Performance" trial currently active) expose **zero generic REST API**. Only fixed helpdesk app integrations are available; none of them is a session-creation endpoint Klara could call.
- The only REST API for session management lives in Splashtop's **Enterprise tier**, which is sales-led, quoted at ~$5K+/yr, and requires a contract — not viable at Klaravex's current pre-revenue stage.
- Splashtop's **OEM SDK** (white-label, programmatic session creation) is also sales-led with custom contract pricing, even longer procurement cycle than Enterprise.
- Klaravex's chosen architecture for AI-controlled remote sessions is the in-house build in `docs/architecture/ai-remote-session.md` (the "G28 spec"): custom helper app + Hetzner-hosted relay + Claude Opus 4.7 vision + Klara voice gate. **Splashtop is not on the critical path for the core product.**
- Splashtop's only remaining possible role is a **manual-fallback remote-control tool** for Anthony to take over when the AI-controlled flow does not exist yet or fails — i.e. a stopgap, not a building block.
- Consistency check with `docs/decisions/2026-06-11-atera-lifecycle.md`: that decision cancels Atera ($149/mo, $0 realized value, no B2B client). The Splashtop question is the same shape — pay for a tool that delivers value only conditionally — and should be answered with the same capital-discipline logic unless the conditional value is materially higher per dollar.

## Three options

### Option 1: LET EXPIRE — do nothing, trial converts to nothing on day 7

- Action required: none, **EXCEPT** verify there is no payment method on file that will auto-charge on 2026-06-18.
- Cost: $0 if no payment method captured; $20–30/mo (verify in EU portal) if Splashtop auto-bills on trial conversion.
- Risk: silent auto-bill if a card was captured at trial signup. Also: lose access to the EU console and any browsed-but-not-exported configuration.
- Reversal: Anthony can sign up for a fresh trial or paid tier later.

### Option 2: CANCEL NOW — log in, navigate to subscription, cancel before any charge

- Action required: ~5 min in `my.splashtop.eu` — Settings → Subscription → Cancel.
- Cost: $0.
- Risk: Splashtop may present a save-the-customer discount during the cancel flow; ignoring it is fine — discount price doesn't change the architectural fit.
- Reversal: same as Option 1 — fresh signup any time.

### Option 3: DOWNGRADE to a paid manual-fix safety net (cheapest SOS tier)

- Action required: pick cheapest SOS tier (~$20–30/mo — **verify in EU portal**), commit a payment method, accept conversion.
- Cost: ~$240–360/yr.
- Value delivered: manual fallback while the AI-controlled session is built — Anthony can take a Splashtop SOS code from a customer and connect manually instead of refunding.
- Risk: paying for a tool that becomes obsolete the moment the in-house Windows MVP ships (~3–4 weeks of focused build per the G28 spec, longer with distraction). Also: no path to making this tool part of the AI flow — it's pure handoff.
- Reversal: cancel any time.

## Comparison: does Option 3 actually deliver value during the AI-controlled build?

Build timeline per `ai-remote-session.md`: Windows-only MVP is realistically **4–8 weeks** of focused work (the spec calls major decisions DECIDED but no code is shipped; code-signing cert issuance alone is 3–5 business days). Call against Option 3's ~4-week window:

- Expected inbound consumer calls during the 4-week build window: **realistically 0–10** total. Klara is live but Klaravex has no paid marketing, no SEO authority yet, and no consumer-facing brand presence at the .com level. Even at $79 close rate with zero infrastructure to attract calls, demand will be near zero.
- Of those calls, fraction that need remote control at all (vs. phone-only resolution): ~50%.
- Of remote-control calls, fraction Anthony would actually rescue manually (vs. refund the $79): generously ~50% — he's also building the product.
- Expected manually-rescued sessions in the 4-week window: **0–2.5 sessions**, midpoint ~1.
- Revenue saved: 1 × $79 = **$79** (vs. refunding).
- Cost of Option 3 over 4 weeks: ~$30. Net: ~+$49 if exactly 1 rescue happens, –$30 if zero rescues.

Break-even is **~0.4 manual rescues over 4 weeks**, i.e. one rescue every ~10 weeks pays for itself. That's a low bar — but it depends on call volume being non-zero. If realistic call volume is closer to 0–2 calls over the entire build window (plausible given no marketing spend), Option 3 is dead weight; Option 1 or 2 wins.

The decisive factor: **Klaravex has no consumer call volume right now**, full stop. Spending $20–30/mo to insure against a manual-fallback need on calls that aren't happening is the same anti-pattern as keeping Atera — paying for readiness when readiness is delivering $0.

## Recommendation

**Option 2: CANCEL NOW.** Splashtop self-serve has no API path to the core product, the in-house G28 build is the committed architecture, and expected consumer call volume during the 4-week build window is too low to justify even a $20–30/mo manual-fallback insurance line. Cancelling tonight (in the morning, by Anthony) eliminates any auto-bill risk on 2026-06-18, holds capital as runway, and is consistent with the Atera SWITCH decision from earlier today. This recommendation depends on the assumption that **consumer call volume during the 4-week build window is fewer than ~1 manual-rescue-eligible call**, which matches Klaravex's current marketing state (no paid acquisition, no SEO authority, brand newly registered). If Anthony has reason to believe call volume will be materially higher — e.g. a planned launch announcement or press hit before the MVP ships — Option 3 is the correct answer instead.

## Action items for Anthony

1. Tomorrow morning, log in to `my.splashtop.eu` with the trial credentials and navigate to **Settings → Subscription**. Confirm trial expiration date and verify whether a payment method was captured at signup.
2. If a payment method is on file, click **Cancel Subscription** (or equivalent) and confirm. Take a screenshot of the cancellation confirmation page and save to 1Password under "Klaravex → Splashtop EU trial cancellation 2026-06-11".
3. If no payment method is on file, still click cancel to be explicit — do not rely on "trial just expires." Same screenshot + 1Password save.
4. Check the Mercury account on 2026-06-18 and again on 2026-06-25 to confirm no Splashtop EU charge appears. If a charge appears, dispute via Mercury and re-open the cancellation with Splashtop support.
5. Add a calendar reminder for 2026-07-11 to revisit: if the in-house Windows MVP is still >2 weeks from ship at that point AND consumer call volume has materialized, re-evaluate signing up for a fresh paid Splashtop SOS tier as a manual fallback.

## What Loki will NOT do

- **Loki will NOT cancel the Splashtop trial tonight.** This is a decision document. Anthony decides in the morning and executes the cancellation himself in the EU portal.
- **Loki will NOT add a payment method to Splashtop.** Under no circumstance will the host session or any subagent attach a Mercury card, Klaravex card, or any other credential to a Splashtop account.
- Loki will NOT contact Splashtop sales about Enterprise or OEM tiers without an explicit per-action instruction from Anthony.

## Open questions for Anthony

- **Was a payment method captured at trial signup?** If yes, Option 2 (cancel now) becomes urgent rather than just prudent — the trial converts to billing on 2026-06-18 and the cancellation must land before then.
- **Realistic consumer call volume for the next 6 weeks?** The recommendation assumes near-zero. If a launch, AMA, press hit, or paid-ad test is planned that could push 10+ calls into the window, Option 3 (keep paid SOS as fallback) becomes the correct call instead.
- **Did Anthony export any configuration from the EU portal during tonight's browse session?** If yes, cancellation is purely cost-side. If no, there may be a small one-time hassle re-doing whatever was configured if Klaravex returns to Splashtop later — but the trial signup itself was minimal, so this is almost certainly a non-issue.
