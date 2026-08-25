# USAGE — RFP visitBerlin Knowledge Manager

This is a documentation bundle (proposal + architecture + compliance + mockup + pitch deck). There is no code to build or server to run. Everything is plain Markdown and static HTML.

## Prerequisites

- A modern browser (Chromium ≥120, Safari ≥17, Firefox ≥120) to view the HTML mockup and pitch deck.
- Any Markdown viewer for the text artifacts (GitHub web, VS Code preview, Obsidian, etc.).
- No installation. No package manager. No services.

## View the artifacts

### Mockup (interactive demo)

```
open mockup/index.html
```

Persona switcher in the top-right toggles between Hannah (employee view) and Konrad (admin view). Side nav switches screens. All data is hard-coded — no backend.

### Pitch deck

```
open pitch-deck/deck.html
```

Keyboard shortcuts inside the deck:
- `← →` / `space` — navigate slides
- `home` / `end` — first / last slide
- type `1`–`16` — jump to slide
- `o` — overview grid (click thumbnail to jump)
- `?` — keyboard help
- `p` — print (browser dialogue exports to PDF as one slide per landscape page)

### Read documents

```
open proposal/proposal.md
open architecture/architecture.md
open architecture/data-flow.md
open compliance/dpia.md
open compliance/gdpr-dossier.md
open compliance/nis2.md
open compliance/bsi-c5.md
open compliance/data-residency.md
```

ADRs are under `architecture/adr/` numbered `adr-0001-` through `adr-0009-`.

## Verify it works

```
# 1. Confirm every deliverable exists and has non-trivial content
ls -la proposal/ architecture/ architecture/adr/ compliance/ mockup/ pitch-deck/

# 2. Open the mockup in a browser and click through 7 screens (Home, Ask the bot,
#    Browse, Detail, Profile, Re-submission queue, Admin console). Switch persona
#    in the top-right to flip between Hannah and Konrad.
open mockup/index.html

# 3. Open the pitch deck and arrow-key through all 16 slides; press 'o' to see
#    the overview grid; press 'p' to verify the print export looks right.
open pitch-deck/deck.html
```

Expected: all six folders contain non-empty files; the mockup renders with a calm German-public-sector aesthetic and the persona switcher works; the pitch deck advances through 16 slides with keyboard navigation.

## Stop

Nothing to stop — there are no running processes.
