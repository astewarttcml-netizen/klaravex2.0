# TESTING

Testing strategy for the **rfp-visitberlin-knowledge-manager** deliverable bundle.

This repository is a **proposal/RFP artifact**, not a production code base. There are no runtime source files and therefore no traditional unit, integration, or end-to-end test suites. Quality assurance here focuses on validating that the proposal, architecture, compliance dossiers, mockup, and pitch deck are **internally consistent, factually grounded, accessible, and verifiable** against the source concept (`_source/visitberlin-concept-v0.1.md`).

---

## 1. Test strategy

The goal of testing in this repository is to guarantee that:

1. Every claim in the proposal is traceable to either an ADR, a compliance dossier, or the source concept.
2. The 9 architectural decisions (ADR-0001 through ADR-0010) are referenced consistently across `architecture/`, `proposal/`, `compliance/`, and the deck.
3. The interactive mockup (`mockup/index.html`) renders, navigates, and survives a basic accessibility pass.
4. The pitch deck (`pitch-deck/deck.html`) prints to PDF cleanly and supports keyboard navigation.
5. Compliance dossiers (GDPR, NIS2, BSI C5, DPIA, data-residency) align with each other and with the routing rule for `klaravex.com` (DE surface, Azure Germany region, Cloud86 audit store).
6. No personally identifiable information (PII) or internal-only material leaks into client-facing artifacts.

Testing is **manual-first, automation-light** — appropriate for an RFP cycle measured in days, not sprints. Where automation pays off (link checking, HTML validation, spell check), it runs locally and in CI.

---

## 2. Test types

### 2.1 Content consistency tests (manual review)

| Check                         | What it verifies                                                                 | Owner            |
| ----------------------------- | -------------------------------------------------------------------------------- | ---------------- |
| ADR cross-reference           | Every decision in `proposal/proposal.md` resolves to a numbered ADR file         | Proposal lead    |
| Source-concept traceability   | Every requirement in `_source/visitberlin-concept-v0.1.md` is addressed or noted | Proposal lead    |
| Contradiction resolution      | All 8 specification contradictions identified in the grill report are resolved  | Architect        |
| Routing-rule alignment        | German artifacts reference Cloud86 / Azure Germany only, never US infra         | Compliance lead  |
| ADR numbering & status        | ADRs are sequential, dated, and carry a status header (Proposed/Accepted)       | Architect        |

### 2.2 Compliance dossier tests (manual review)

| Dossier                  | Validation                                                                            |
| ------------------------ | ------------------------------------------------------------------------------------- |
| `compliance/gdpr-dossier.md` | Lawful-basis register, sub-processor map, and DSR mechanics are complete          |
| `compliance/dpia.md`     | Every processing activity from the architecture appears in the DPIA matrix             |
| `compliance/nis2.md`     | Klaravex supplier scope is stated; visitBerlin scope assumption is flagged             |
| `compliance/bsi-c5.md`   | All 17 BSI C5:2020 control domains are addressed with ISO 27001 cross-walk             |
| `compliance/data-residency.md` | At-rest in Germany; transit-only exceptions to Sweden/France are itemised         |

### 2.3 Mockup tests (browser, manual + automated)

The mockup is a single-file SPA at `mockup/index.html` with 7 screens and a persona switcher.

- **Render test:** open in Chrome, Firefox, Safari. All 7 screens load without console errors.
- **Navigation test:** persona switcher cycles through all roles; deep links to each screen work.
- **Keyboard test:** tab order is logical; all interactive controls are reachable without a mouse.
- **Accessibility smoke test:** run axe-core via the browser devtools extension or `bunx @axe-core/cli mockup/index.html`. Target: zero serious or critical violations.
- **No-network test:** open the file with the network panel set to offline. The mockup must render fully (no CDN dependencies that would fail at a tender desk).

### 2.4 Pitch deck tests (browser, manual)

- **Slide count:** 16 slides present and reachable.
- **Keyboard navigation:** arrow keys advance and reverse; `Esc` opens overview.
- **Print-to-PDF:** Chrome print preview produces 16 pages, one slide per page, no clipped content. Use A4 landscape.
- **Speaker-notes pass:** if notes are present, they are not visible in the rendered slide view.

### 2.5 Link and reference tests (automated)

- **Internal links:** all relative links between markdown files resolve (no 404s).
- **External links:** every `https://` link in the proposal returns 200 OK at build time.
- **Image references:** every embedded image in markdown and HTML exists in `assets/`.

### 2.6 Hygiene tests (automated)

- **Secret scan:** no API keys, passwords, or tokens committed.
- **PII scan:** no real client personnel names, internal IP ranges, or unredacted email addresses outside `_source/`.
- **Spell check:** German and English passes against a project glossary that whitelists technical terms (Bicep, Entra, RRF, BM25, etc.).

---

## 3. How to run tests

All commands assume Bun is installed and you are in the repository root.

### 3.1 Install dev dependencies

```sh
bun install
```

### 3.2 Mockup and deck render check

```sh
bun --hot serve mockup/
# open http://localhost:3000/index.html and step through manually
```

Or open the file directly:

```sh
open mockup/index.html
open pitch-deck/deck.html
```

### 3.3 Accessibility scan

```sh
bunx @axe-core/cli mockup/index.html
bunx @axe-core/cli pitch-deck/deck.html
```

### 3.4 Markdown link check

```sh
bunx markdown-link-check proposal/proposal.md
bunx markdown-link-check architecture/architecture.md
bunx markdown-link-check compliance/*.md
```

### 3.5 Spell check

```sh
bunx cspell "**/*.md" --config .cspell.json
```

### 3.6 Secret scan

```sh
bunx @secretlint/secretlint "**/*.md" "**/*.html"
```

### 3.7 Print pitch deck to PDF (headless)

```sh
bunx playwright-cli pdf --format=A4 --landscape \
  pitch-deck/deck.html dist/pitch-deck.pdf
```

---

## 4. Test configuration

| File                    | Purpose                                                          |
| ----------------------- | ---------------------------------------------------------------- |
| `.cspell.json`          | Spell-check dictionary and per-language overrides (en, de)        |
| `.markdown-link-check.json` | Timeouts, ignore patterns, retry policy for link checking      |
| `.secretlintrc.json`    | Secret-scan rule set                                              |
| `axe.config.json`       | Accessibility severity thresholds (block on serious + critical)   |
| `.github/workflows/qa.yml` | CI pipeline definition (see Section 6)                         |

A project glossary lives at `.cspell-glossary.txt` and must include:
- Product/brand names: Klaravex, visitBerlin, Entra, M365
- Technical terms: BM25, RRF, Bicep, Azure OpenAI, EUDB
- Compliance acronyms: GDPR, NIS2, BSI C5, DPIA, DSR, EUDB

---

## 5. Coverage goals

Because this is a documentation deliverable, coverage is measured in **artifact-traceability percentage**, not code lines.

| Metric                                                            | Target  | Source of truth                              |
| ----------------------------------------------------------------- | ------- | -------------------------------------------- |
| Requirements from concept doc addressed in proposal               | 100%    | `_source/visitberlin-concept-v0.1.md`        |
| Architectural decisions backed by an ADR                          | 100%    | `architecture/adr/`                          |
| Contradictions from devil's-advocate review resolved              | 100%    | `.loki/grill/report.md`                      |
| Compliance domains with a dedicated dossier                       | 5 of 5  | `compliance/` (GDPR, NIS2, BSI C5, DPIA, residency) |
| Mockup screens reachable from the navigation                       | 7 of 7  | `mockup/index.html`                          |
| Pitch deck slides reachable via keyboard                          | 16 of 16 | `pitch-deck/deck.html`                       |
| axe-core serious/critical violations on mockup                    | 0       | axe-core report                               |
| axe-core serious/critical violations on deck                      | 0       | axe-core report                               |
| Broken internal markdown links                                    | 0       | `markdown-link-check` report                  |
| Secret-scan findings                                              | 0       | `secretlint` report                           |

A submission is considered **ship-ready** only when all targets are met. Any deviation must be recorded in `BUILD-STATUS.md` with rationale and mitigation.

---

## 6. CI integration

The repository runs a lightweight CI pipeline on every push and pull request. The pipeline is defined in `.github/workflows/qa.yml` and executes the following stages in order:

1. **Setup** — install Bun, restore cache, install dev dependencies.
2. **Lint** — spell check (`cspell`) across all markdown.
3. **Secret scan** — `secretlint` across markdown and HTML.
4. **Link check** — `markdown-link-check` across `proposal/`, `architecture/`, and `compliance/`.
5. **Accessibility** — axe-core CLI against `mockup/index.html` and `pitch-deck/deck.html`; fail on any serious or critical violation.
6. **Render check** — headless Playwright load of both HTML artifacts; fail on console errors or unhandled rejections.
7. **PDF build** — render the pitch deck to PDF; upload as a workflow artifact for reviewer download.
8. **Bundle** — zip the client-facing artifacts (`proposal/`, `architecture/`, `compliance/`, `mockup/`, `pitch-deck/`, `README.md`) and upload as a workflow artifact named `rfp-bundle-<sha>.zip`.

### Failure policy

- Any stage failure blocks merge to `main`.
- The `BUILD-STATUS.md` file is updated automatically (via a post-step) with the latest CI status badge and a timestamp.
- Manual review stages (Section 2.1, 2.2) are tracked as required GitHub checklist items on the pull request; CI does not auto-approve them.

### Local pre-push hook

Contributors are encouraged to run the same stages locally before pushing:

```sh
bun run qa
```

This script (defined in `package.json`) chains the lint, secret-scan, link-check, and accessibility steps. It is the same set CI runs, minus the PDF and bundle output.

---

## 7. Out of scope

The following are explicitly **not tested** in this repository because no implementation exists yet:

- Azure infrastructure provisioning (covered post-award by Bicep templates in a separate repository).
- Retrieval pipeline correctness (BM25/vector/graph hybrid — tested in the engine repository).
- End-to-end Microsoft 365 / Teams bot flow.
- Performance, load, or chaos testing of the production system.

These will be addressed in the implementation repository once the RFP is awarded and the build phase begins.
