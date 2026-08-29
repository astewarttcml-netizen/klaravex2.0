# Page: B2B Contact (`/business/contact/`)
**WordPress slug:** business/contact
**SEO Title:** Contact Klaravex — Book a Discovery Call
**Meta Description:** Book a 30-minute discovery call or send a message. Serving US and EU SMBs across M365, Google Workspace, and AWS.
**No-index:** No

---

## SECTION 1: HERO

**Headline:** Let's talk.

**Sub-headline:** Book a 30-minute discovery call, or send us a message. No commitment, no sales pressure.

---

## SECTION 2: PRIMARY PATH — BOOK A DISCOVERY CALL
*(High-intent path — Calendly embed)*

**Heading:** Book a Discovery Call

A 30-minute call is enough to understand your current environment, your exposure, and what a managed service engagement would look like for your business.

**Calendly embed here** *(inline, 30-minute B2B discovery call event type)*

---

## SECTION 3: SECONDARY PATH — SEND A MESSAGE
*(Lower-intent path — CF7 contact form)*

**Heading:** Not ready to book? Send us a message.

*(Contact Form 7 fields:)*
- **Name** *(required)*
- **Company** *(required)*
- **Email** *(required)*
- **Country** *(required — for GDPR routing logic — dropdown: United States / Germany / EU (other) / Other)*
- **Message** *(required — minimum 20 characters)*
- **Consent checkbox** *(required)*: I agree to Klaravex processing my contact information to respond to this inquiry. See our [Privacy Policy](/privacy/).

**Submit button:** Send Message

**After submit:** Redirect to `/thank-you/`

---

## SECTION 4: CONSUMER REDIRECT NOTE
*(Brief, friendly)*

Looking for personal IT help? Our [Personal IT Support](/personal/) page is the right place to start.

---

## SECTION 5: CONTACT DETAILS

**Email:** hello@klaravex.com
**Response time:** We aim to respond to all messages within one business day.

---

## BREADCRUMB
Home → Business → Contact

---

### Calendly Intake Questions (configure in Calendly — not on WP page)
1. Company name and primary industry
2. Approximate employee count
3. Cloud platforms in use (M365/Azure / Google Workspace / AWS / Other)
4. Regulatory context (HIPAA / NIS2 / DORA / ISO 27001 / GDPR / SOC 2 / Other / Unsure)
5. Primary concern (security posture / upcoming audit / readiness program / incident / general inquiry)
6. How did you find Klaravex?

### Form Routing Notes
- CF7 → hello@klaravex.com via M365 SMTP relay
- Auto-confirmation email to submitter (plain text)
- Anti-spam: Cloudflare Turnstile preferred (no Google reCAPTCHA visual friction)
