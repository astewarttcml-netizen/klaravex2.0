# SETUP

Setup guide for the `rfp-visitberlin-knowledge-manager` deliverable bundle.

This repository is a **documentation and design package** prepared in response to the visitBerlin Knowledge Manager concept v0.1. It does not contain a runnable backend service — it bundles a written proposal, architecture documents, ADRs, compliance dossiers, an interactive HTML mockup, and a pitch deck. Setup is therefore lightweight: you need only a working git client, a browser, and (optionally) a static file server to preview the HTML artifacts.

---

## 1. Prerequisites

| Tool          | Minimum version | Why it is needed                                                |
| ------------- | --------------- | --------------------------------------------------------------- |
| Git           | 2.40+           | Clone the repository and review history                          |
| Bun           | 1.1+            | Recommended static server runtime (workspace default per CLAUDE) |
| A modern browser | Chrome 120+, Firefox 120+, Safari 17+ | Render the mockup and pitch deck       |
| Node.js       | 20+ (optional)  | Alternative runtime if Bun is unavailable                        |
| Pandoc        | 3.x (optional)  | Convert the proposal markdown to PDF / DOCX                      |
| wkhtmltopdf or Chrome headless | latest (optional) | Print the pitch deck to PDF                  |

No database, no message broker, and no compiled language toolchain are required to consume the deliverables.

> The production platform described in `proposal/proposal.md` is built on Azure Germany, Azure AI Search, Azure OpenAI (Sweden Central / France Central), Microsoft Entra ID, and Bicep-based IaC. None of those services are provisioned by this repository. The repository only contains the proposal **for** that platform.

---

## 2. Installation

```bash
# Clone the workspace (already nested inside the klaravex sales workspace)
git clone <your-fork-or-mirror-url> rfp-visitberlin-knowledge-manager
cd rfp-visitberlin-knowledge-manager

# Confirm the deliverable directories are present
ls -la
# expected: README.md  USAGE.md  BUILD-STATUS.md  proposal/  architecture/
#           compliance/  mockup/  pitch-deck/  _source/
```

There are no package dependencies to install. The optional tooling below can be installed on demand:

```bash
# Bun (preferred per workspace convention)
curl -fsSL https://bun.sh/install | bash

# Pandoc (macOS)
brew install pandoc

# Pandoc (Debian/Ubuntu)
sudo apt-get install -y pandoc
```

---

## 3. Environment variables

This repository ships no application code, so it has no required environment variables.

The following variables are **only** referenced by the proposed production platform and are documented here so reviewers understand what the live system would consume. They are not needed to read or preview the deliverables.

| Variable                          | Used by                       | Notes                                                  |
| --------------------------------- | ----------------------------- | ------------------------------------------------------ |
| `AZURE_TENANT_ID`                 | Production platform           | Entra ID tenant for the visitBerlin deployment         |
| `AZURE_SUBSCRIPTION_ID`           | Production platform           | Target subscription for Bicep deployment               |
| `AZURE_REGION`                    | Production platform           | Fixed to `germanywestcentral` per ADR-0001             |
| `AZURE_SEARCH_ENDPOINT`           | Production platform           | Azure AI Search service URI                            |
| `AZURE_OPENAI_ENDPOINT`           | Production platform           | Sweden Central / France Central deployment endpoint    |
| `AZURE_OPENAI_DEPLOYMENT`         | Production platform           | Chat / embedding deployment name                       |
| `TOURISM_DATA_HUB_BASE_URL`       | Production platform           | Read-only adapter, no copy (ADR-0003)                  |
| `AUDIT_LOG_HOT_RETENTION_DAYS`    | Production platform           | Default 90 (two-tier audit, ADR-0004)                  |
| `AUDIT_LOG_COLD_RETENTION_YEARS`  | Production platform           | Default 7 (two-tier audit, ADR-0004)                   |
| `MAILBOX_INGESTION_ENABLED`       | Production platform           | Default `false`, DPO-gated opt-in (ADR-0007)           |

When the production platform is built, copy the template to a local `.env` file and supply real values. Bun loads `.env` automatically.

```bash
cp .env.example .env   # template not shipped in this RFP bundle
```

---

## 4. Database setup

**Not applicable to this repository.**

The repository contains no database, no migrations, and no seed data. The proposed production platform uses:

- Azure AI Search (vector + BM25 hybrid index) as the primary retrieval store
- Azure Cosmos DB or Azure SQL (Germany region) for the action audit log (7-year retention)
- Azure Log Analytics for the read audit log (90-day hot retention)
- Azure Storage (Germany region) for tenant-isolated document blobs

Schema definitions for those stores live in the architecture documents (`architecture/architecture.md`, `architecture/data-flow.md`) and are not provisioned by this repository.

---

## 5. Running locally

### 5.1 Reading the written deliverables

The proposal, ADRs, and compliance dossiers are plain markdown. Open them with your editor of choice or render them on GitHub:

```bash
# Quick scan
less proposal/proposal.md
less architecture/architecture.md
ls architecture/adr/
ls compliance/
```

### 5.2 Previewing the interactive mockup

`mockup/index.html` is a self-contained single-file SPA with a persona switcher across seven screens.

```bash
# Preferred: Bun static server
bunx serve mockup

# Alternative: Python (already installed on macOS)
python3 -m http.server 4173 --directory mockup

# Then open
open http://localhost:4173
```

Opening the file directly with `file://` also works, but a local HTTP server is recommended so the browser does not block any relative asset loads.

### 5.3 Previewing the pitch deck

`pitch-deck/deck.html` is a 16-slide deck with keyboard navigation (arrow keys, `Space`) and print-to-PDF support.

```bash
bunx serve pitch-deck
open http://localhost:3000

# Print to PDF (headless Chrome)
chrome --headless --disable-gpu --print-to-pdf=deck.pdf http://localhost:3000
```

### 5.4 Building the proposal PDF (optional)

```bash
pandoc proposal/proposal.md \
  -o proposal/proposal.pdf \
  --from gfm \
  --pdf-engine=xelatex \
  --metadata title="visitBerlin Knowledge Manager — Klaravex Proposal"
```

---

## 6. Running in Docker

A Docker workflow is **not required** for this repository. If you want a reproducible preview environment, the following one-liner is sufficient:

```bash
docker run --rm -it -p 8080:80 \
  -v "$(pwd)/mockup:/usr/share/nginx/html:ro" \
  nginx:alpine

# Then open http://localhost:8080
```

Swap `mockup` for `pitch-deck` to preview the deck under the same setup. No `Dockerfile` is shipped because the artifacts are static.

---

## 7. Common troubleshooting

| Symptom                                                  | Likely cause                                                          | Fix                                                                                              |
| -------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Mockup loads but persona switcher is unresponsive        | Browser opened the file via `file://` and blocked an inline script    | Serve via `bunx serve mockup` or `python3 -m http.server` and reopen on `http://localhost`.       |
| Pitch deck keyboard navigation does nothing              | Focus is on an inner iframe or address bar                            | Click once inside the slide area, then use arrow keys / `Space`.                                  |
| `pandoc` fails with "xelatex not found"                  | LaTeX engine missing                                                  | Install BasicTeX (`brew install --cask basictex`) or use `--pdf-engine=wkhtmltopdf`.              |
| `bunx serve` exits with `EADDRINUSE`                     | Another process is bound to the chosen port                           | Pick a free port: `bunx serve mockup -l 5050`.                                                    |
| Markdown renders without diagrams on GitHub              | Mermaid is not enabled on private mirrors                             | Render locally with a Mermaid-aware viewer or export diagrams via `mmdc` to SVG.                  |
| Links between ADRs return 404 in the rendered HTML       | Static server is rooted at a sub-folder; relative links break out     | Serve from the repository root: `bunx serve .` and navigate from `architecture/adr/`.             |
| Loki state files appear modified after a clean checkout  | `.loki/` is a working scratch directory used by the Loki agent runner | Safe to ignore for review purposes; do not commit transient state under `.loki/queue/`, `.loki/state/`. |
| Pitch deck PDF export is missing the last slide          | Headless Chrome guessed the wrong page size                           | Add `--no-pdf-header-footer --paper-width=13.333 --paper-height=7.5` to match the 16:9 layout.    |
| Mockup fonts look wrong on Linux                         | System lacks the fallback sans font                                   | Install `fonts-inter` (Debian/Ubuntu) or accept the local system sans-serif fallback.            |

---

## 8. What this repository does **not** set up

To avoid confusion during review:

- It does **not** provision any Azure resources. See `architecture/adr/adr-0009-bicep-over-terraform.md` for the IaC strategy that **would** be used for the live system.
- It does **not** ingest visitBerlin content. The mockup uses synthetic placeholder data only.
- It does **not** call Azure OpenAI, Azure AI Search, the Tourism Data Hub, or any Microsoft 365 surface. All interactions in the mockup are client-side simulations.
- It does **not** contain personal data or secrets. The DPIA in `compliance/dpia.md` describes the personal data the **production** platform would process.

If you need the runnable platform rather than the proposal package, refer to the implementation roadmap in `proposal/proposal.md` and the ADRs in `architecture/adr/`.
