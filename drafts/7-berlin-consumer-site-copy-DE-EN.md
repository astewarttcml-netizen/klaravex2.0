# personal.klaravex.com — Bilingual Consumer Site Copy
**Berlin-adapted. German default + English toggle. Remote-only. Phase-1 AI-assist disclosure. Klara localized.**

**Status:** Draft copy for review. Nothing deployed. Replaces the US-framed copy on personal.klaravex.com (which says "across the US" / "in-person" — both removed here for a Berlin-remote operator).
**Pricing:** placeholders use the corrected proposed tiers (€). Confirm before publishing.
**Klara:** client-facing assistant name in both languages; responds in the page language.

---

## A. ENGLISH (for Berlin expats — the `en` toggle)

### Hero
**Tech help in Berlin — in plain English.**
Slow computer, Wi-Fi that won't behave, printer, email, accounts, online privacy, or finally getting comfortable with AI tools. We help remotely, around the clock — clearly explained, no jargon, no judgment.
[Get help today] [See what we help with]

*Built for Berlin's international community — full support in English.*

### AI-assist disclosure (Phase 1 — visible, above the fold)
> We use AI tools (our assistant, **Klara**) to work faster — but a real, certified expert personally handles and checks your request, every time. You're never handed off to a bot.

### What we help with
- **IT help & repairs** — slow PC, Wi-Fi, printers, email, crashes. Fixed fast, explained simply.
- **Family & senior tech** — patient, kind help with phones, tablets, video calls, scam protection.
- **Privacy & security** — passwords, two-factor, identity cleanup, privacy settings across your devices.
- **AI skills coaching** — learn ChatGPT, Claude and AI tools for everyday life. No tech background needed.
- **Newcomer tech setup** — new to Berlin? Get your devices, accounts, and connectivity sorted in English.

### How it works
1. **Tell us what's wrong** — message us or chat with Klara. No ticket forms, no hold music.
2. **We solve it — AI-fast, human-checked** — Klara starts immediately; a certified expert handles and approves anything that needs judgment. Remote screen-share, always with your permission.
3. **You feel confident** — we explain what happened and send a written summary after every session.

### Who we help
Busy professionals · Parents & seniors · Students & job-seekers · Expats new to Germany · Solo entrepreneurs.

### Pricing (confirm numbers)
- **AI Chat** — €19/mo · 24/7 assistant, certified-human escalation. The everyone-can-afford on-ramp.
- **Essential** — €59/mo · priority response, sessions included, written summaries.
- **Family** — €99/mo · up to 4 people, senior-friendly.
- **One-time session** — €99 · no commitment.
- *Founding rate: first 50 clients get Essential at €39/mo for 6 months.*

### CTA
**Ready to stop fighting with your tech?** [Get help today]

### Footer
Remote tech help for people in Berlin — in English and German. Plain language, no jargon, no judgment.
Impressum · Datenschutz · [working phone] · hello@klaravex.com

---

## B. DEUTSCH (Standardsprache — der `de` Toggle)

### Hero
**Computerhilfe in Berlin — verständlich erklärt.**
Langsamer Computer, WLAN-Probleme, Drucker, E-Mail, Konten, Datenschutz — oder endlich sicher im Umgang mit KI-Tools. Wir helfen remote, rund um die Uhr — klar erklärt, ohne Fachchinesisch, ohne Urteil.
[Jetzt Hilfe holen] [Womit wir helfen]

*Auf Deutsch und Englisch — ideal für Berlins internationale Community.*

### KI-Hinweis (Phase 1 — sichtbar, oben)
> Wir nutzen KI-Tools (unsere Assistentin **Klara**), um schneller zu arbeiten — aber eine echte, zertifizierte Fachkraft bearbeitet und prüft Ihr Anliegen persönlich. Sie werden nie an einen Bot abgegeben.

### Womit wir helfen
- **IT-Hilfe & Reparaturen** — langsamer PC, WLAN, Drucker, E-Mail, Abstürze. Schnell behoben, verständlich erklärt.
- **Technik für Familie & Senioren** — geduldige, freundliche Hilfe mit Handy, Tablet, Videoanrufen, Schutz vor Betrug.
- **Datenschutz & Sicherheit** — Passwörter, Zwei-Faktor, Identitätsbereinigung, Privatsphäre-Einstellungen.
- **KI-Coaching** — ChatGPT, Claude & KI-Tools für den Alltag lernen. Keine Vorkenntnisse nötig.
- **Technik-Einrichtung für Neuankömmlinge** — neu in Berlin? Geräte, Konten und Internet eingerichtet.

### So funktioniert's
1. **Sagen Sie, was los ist** — schreiben Sie uns oder chatten Sie mit Klara. Keine Ticket-Formulare.
2. **Wir lösen es — KI-schnell, menschlich geprüft** — Klara beginnt sofort; eine zertifizierte Fachkraft übernimmt und prüft alles, was Urteilsvermögen erfordert. Remote-Sitzung, immer mit Ihrer Erlaubnis.
3. **Sie fühlen sich sicher** — wir erklären, was passiert ist, und senden nach jeder Sitzung eine schriftliche Zusammenfassung.

### Für wen
Berufstätige · Familien & Senioren · Studierende & Jobsuchende · Expats · Selbstständige.

### Preise (Zahlen bestätigen)
- **KI-Chat** — 19 €/Monat · Assistentin rund um die Uhr, Eskalation an zertifizierte Fachkraft.
- **Essential** — 59 €/Monat · bevorzugte Reaktion, Sitzungen inklusive, schriftliche Zusammenfassungen.
- **Familie** — 99 €/Monat · bis zu 4 Personen, seniorenfreundlich.
- **Einzelsitzung** — 99 € · ohne Verpflichtung.
- *Gründungstarif: die ersten 50 Kund:innen erhalten Essential für 6 Monate zu 39 €/Monat.*

### CTA
**Schluss mit dem Kampf gegen die Technik?** [Jetzt Hilfe holen]

### Footer
Remote-Computerhilfe für Menschen in Berlin — auf Deutsch und Englisch. Klare Sprache, kein Fachchinesisch.
Impressum · Datenschutz · [Telefonnummer] · hello@klaravex.com

---

## C. Language architecture (for the build)

- **Default:** German (`de-DE`) on personal.klaravex.com; visible **EN toggle** in the header (mirror klaravex.com's existing pattern).
- **hreflang tags** on every page:
  - `<link rel="alternate" hreflang="de" href="https://personal.klaravex.com/..." />`
  - `<link rel="alternate" hreflang="en" href="https://personal.klaravex.com/en/..." />`
  - `<link rel="alternate" hreflang="x-default" href="https://personal.klaravex.com/" />`
- **personal.klaravex.com decision (open):** either repurpose as the **US** consumer site (separate market, later) OR `hreflang`-link/redirect it to the .de English version so the two English pages don't compete. Recommend: park .com → point at .de EN until a real US push.
- **Klara** loads with the page locale and responds in that language; honors the visitor's toggle (see Loki/Klara brief).
- **Remove from all consumer copy:** "across the US," "in-person" (Berlin-remote only). In-person can return later as a paid Berlin add-on.

## What I did NOT do
No site deployed, no content published. Paste-ready bilingual draft for your review.
