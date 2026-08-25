#!/usr/bin/env bun
// PRD Phase 2 — page builder for klaravex.com WordPress.
// Reads source markdown from website/copy/ and site-relaunch/, applies
// pricing override (§3), runs Americanization grep gate (§6 Gate 1),
// converts to WP block HTML, and POSTs as status=draft.
//
// Modes:
//   --dry-run   Parse, override, gate, convert; write report; no network.
//   (default)   Same as --dry-run plus POST /wp-json/wp/v2/pages.
//
// Auth (live mode only): reads .loki/wp-auth.json written by wp-build-auth.ts.

import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, basename } from "node:path";

const PROJECT_ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const LOKI_DIR = join(PROJECT_ROOT, ".loki");
const COPY_DIR = join(PROJECT_ROOT, "website/copy");
const AUTH_FILE = join(LOKI_DIR, "wp-auth.json");
const REPORT_FILE = join(LOKI_DIR, "wp-build-pages.report.json");
const WP_BASE = "https://klaravex.com/wp-json/wp/v2";

const DRY_RUN = process.argv.includes("--dry-run") || !existsSync(AUTH_FILE);

// ---------------------------------------------------------------------------
// PRD §3 — pricing override. Old ranges AND old flat prices → authoritative
// per-user/month values (updated 2026-08-17 per CLAUDE.md §0: $49/$79/$129).
// Foundation $49 / Assurance $79 / Directive $129 per user/month (USD).
// ---------------------------------------------------------------------------

type PricingMatch = { from: string; to: string };

const PRICING_OVERRIDES: PricingMatch[] = [
  // Directive $129/user/month (was old range $150–250 or flat $295)
  { from: "$150–250 / user / month", to: "$129 / user / month" },
  { from: "$150–250/user/month", to: "$129/user/month" },
  { from: "$150-250 / user / month", to: "$129 / user / month" },
  { from: "$150-250/user/month", to: "$129/user/month" },
  { from: "$295 / user / month", to: "$129 / user / month" },
  { from: "$295/user/month", to: "$129/user/month" },
  { from: "$295/user/mo", to: "$129/user/mo" },
  // Assurance $79/user/month (was old range $100–150 or flat $165)
  { from: "$100–150 / user / month", to: "$79 / user / month" },
  { from: "$100–150/user/month", to: "$79/user/month" },
  { from: "$100-150 / user / month", to: "$79 / user / month" },
  { from: "$100-150/user/month", to: "$79/user/month" },
  { from: "$165 / user / month", to: "$79 / user / month" },
  { from: "$165/user/month", to: "$79/user/month" },
  { from: "$165/user/mo", to: "$79/user/mo" },
  // Foundation $49/user/month (was old range $75–100 or flat $100)
  { from: "$75–100 / user / month", to: "$49 / user / month" },
  { from: "$75–100/user/month", to: "$49/user/month" },
  { from: "$75-100 / user / month", to: "$49 / user / month" },
  { from: "$75-100/user/month", to: "$49/user/month" },
  { from: "$100 / user / month", to: "$49 / user / month" },
  { from: "$100/user/month", to: "$49/user/month" },
  { from: "$100/user/mo", to: "$49/user/mo" },
];

function applyPricingOverride(text: string): {
  text: string;
  applied: string[];
} {
  let result = text;
  const applied: string[] = [];
  for (const { from, to } of PRICING_OVERRIDES) {
    if (result.includes(from)) {
      applied.push(`${from} → ${to}`);
      result = result.split(from).join(to);
    }
  }
  return { text: result, applied };
}

// ---------------------------------------------------------------------------
// PRD §8-compatible auto-patch — strips banned-token blocks from in-memory
// markdown body BEFORE Gate 1 evaluation. Source files are NOT modified.
//
// Strategy: scan line-by-line. If a paragraph/list-item line contains a
// banned token, drop the entire line. EUR/€ replaced with USD/$ in-place
// (price contexts). Per-slug exceptions: "Berlin-based principal" allowed
// once on /about/; "NIS2"/"DORA" allowed on /business/industries/nis2-dora/.
// ---------------------------------------------------------------------------

// Tokens that force a line to be dropped entirely (positioning bugs).
const DROP_TOKENS_DEFAULT = ["Berlin"];
// Tokens that get inline replaced (currency/locale).
const REPLACE_TOKENS: Array<{ from: string; to: string }> = [
  { from: "€", to: "$" },
  { from: " EUR ", to: " USD " },
  { from: "EUR billing", to: "USD billing" },
  { from: "EUR pricing", to: "USD pricing" },
  { from: "optimise", to: "optimize" },
  { from: "centre", to: "center" },
  { from: "organisation", to: "organization" },
  { from: "English-speaking", to: "English support" },
];

function autoPatchAmericanization(
  body: string,
  slug: string,
): { text: string; dropped: number; replaced: number } {
  // "Berlin-based principal" once on /about/.
  const dropTokens = [...DROP_TOKENS_DEFAULT];

  // Inline replacements first.
  let replaced = 0;
  let text = body;
  for (const { from, to } of REPLACE_TOKENS) {
    if (text.includes(from)) {
      const count = countOccurrences(text, from);
      text = text.split(from).join(to);
      replaced += count;
    }
  }

  // Line-level drop. Preserve allowed "Berlin-based principal" on /about/ (first hit only).
  const lines = text.split("\n");
  const kept: string[] = [];
  let dropped = 0;
  let aboutBerlinKept = false;
  for (const line of lines) {
    const lowerLine = line;
    let drop = false;
    for (const tok of dropTokens) {
      if (lowerLine.includes(tok)) {
        // Allow exactly one "Berlin-based principal" line on /about/.
        if (
          tok === "Berlin" &&
          slug === "about" &&
          !aboutBerlinKept &&
          lowerLine.includes("Berlin-based principal")
        ) {
          aboutBerlinKept = true;
          continue;
        }
        drop = true;
        break;
      }
    }
    if (drop) {
      dropped++;
    } else {
      kept.push(line);
    }
  }
  return { text: kept.join("\n"), dropped, replaced };
}

// ---------------------------------------------------------------------------
// PRD §6 Gate 1 — Americanization grep. Zero hits required (with exceptions).
// ---------------------------------------------------------------------------

const BANNED_TOKENS = [
  "€",
  "EUR",
  "optimise",
  "centre",
  "organisation",
  "English-speaking",
];

// "Berlin" allowed on /about/ as "Berlin-based principal" once; NIS2/DORA
// allowed only on the nis2-dora page.
function americanizationGate(
  htmlOrMd: string,
  slug: string,
): { passed: boolean; hits: Array<{ token: string; count: number }> } {
  const hits: Array<{ token: string; count: number }> = [];
  for (const token of BANNED_TOKENS) {
    const count = countOccurrences(htmlOrMd, token);
    if (count > 0) hits.push({ token, count });
  }
  // Conditional gates
  const berlinCount = countOccurrences(htmlOrMd, "Berlin");
  if (slug === "about") {
    // Allow ONE occurrence in "Berlin-based principal" only
    const allowed = countOccurrences(htmlOrMd, "Berlin-based principal");
    if (berlinCount > allowed) {
      hits.push({ token: "Berlin (>1 or not in 'Berlin-based principal')", count: berlinCount - allowed });
    }
  } else if (berlinCount > 0) {
    hits.push({ token: "Berlin", count: berlinCount });
  }
  return { passed: hits.length === 0, hits };
}

function countOccurrences(haystack: string, needle: string): number {
  if (!needle) return 0;
  let i = 0;
  let count = 0;
  while ((i = haystack.indexOf(needle, i)) !== -1) {
    count++;
    i += needle.length;
  }
  return count;
}

// ---------------------------------------------------------------------------
// Source file parsing — extract frontmatter (slug, SEO title, meta desc).
// ---------------------------------------------------------------------------

type SourcePage = {
  sourceFile: string;
  pageTitle: string;
  rawSlug: string;
  slug: string; // normalized, no leading/trailing slash
  seoTitle: string | null;
  metaDescription: string | null;
  noIndex: boolean | null;
  body: string;
};

function normalizeSlug(raw: string): string {
  let s = raw.trim();
  s = s.replace(/^\(.*?\)$/, ""); // remove "(homepage — front page)" wrap
  s = s.replace(/[()]/g, ""); // strip stray parens
  s = s.replace(/^\/+|\/+$/g, ""); // strip leading/trailing slashes
  return s;
}

function parseFrontmatter(filePath: string, raw: string): SourcePage | null {
  const lines = raw.split("\n");
  const titleLine = lines.find((l) => /^# Page:/.test(l));
  if (!titleLine) return null;
  const pageTitleMatch = titleLine.match(/^# Page:\s*(.+?)\s*\(`(.+?)`\)/);
  const pageTitle = pageTitleMatch ? pageTitleMatch[1] : basename(filePath, ".md");

  const slugLine = lines.find((l) => /^\*\*WordPress slug:\*\*/.test(l));
  const seoLine = lines.find((l) => /^\*\*SEO Title:\*\*/.test(l));
  const metaLine = lines.find((l) => /^\*\*Meta Description:\*\*/.test(l));
  const noIndexLine = lines.find((l) => /^\*\*No-index:\*\*/.test(l));

  if (!slugLine) return null;
  const rawSlug = slugLine.replace(/^\*\*WordPress slug:\*\*\s*/, "").trim();
  const seoTitle = seoLine
    ? seoLine.replace(/^\*\*SEO Title:\*\*\s*/, "").trim()
    : null;
  const metaDescription = metaLine
    ? metaLine.replace(/^\*\*Meta Description:\*\*\s*/, "").trim()
    : null;
  const noIndex = noIndexLine
    ? /^\*\*No-index:\*\*\s*(yes|true)/i.test(noIndexLine)
    : null;

  // Body = everything after the frontmatter block (after first '---' or after meta line)
  const firstDashIdx = lines.findIndex((l, i) => i > 0 && /^---\s*$/.test(l));
  const body =
    firstDashIdx > 0 ? lines.slice(firstDashIdx + 1).join("\n") : lines.slice(5).join("\n");

  return {
    sourceFile: filePath,
    pageTitle,
    rawSlug,
    slug: normalizeSlug(rawSlug),
    seoTitle,
    metaDescription,
    noIndex,
    body,
  };
}

// ---------------------------------------------------------------------------
// Minimal Markdown → WordPress-compatible HTML.
// Block editor classic-block fallback is fine; we emit plain HTML.
// ---------------------------------------------------------------------------

function mdToHtml(md: string): string {
  const lines = md.split("\n");
  const out: string[] = [];
  let inList: "ul" | "ol" | null = null;
  let inPara = false;

  const closeList = () => {
    if (inList) {
      out.push(`</${inList}>`);
      inList = null;
    }
  };
  const closePara = () => {
    if (inPara) {
      out.push("</p>");
      inPara = false;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.replace(/\s+$/, "");

    // Horizontal rule
    if (/^---+$/.test(line)) {
      closePara();
      closeList();
      out.push("<hr />");
      continue;
    }
    // Blank line
    if (line === "") {
      closePara();
      closeList();
      continue;
    }
    // Headings
    const h = line.match(/^(#{1,6})\s+(.+)$/);
    if (h) {
      closePara();
      closeList();
      const level = Math.min(h[1].length, 6);
      // PRD §5.2: H1 is the WP page title; demote H1 in body to H2.
      const renderLevel = level === 1 ? 2 : level;
      out.push(`<h${renderLevel}>${inline(h[2])}</h${renderLevel}>`);
      continue;
    }
    // Blockquote / callout
    if (/^>\s?/.test(line)) {
      closePara();
      closeList();
      out.push(`<blockquote><p>${inline(line.replace(/^>\s?/, ""))}</p></blockquote>`);
      continue;
    }
    // Unordered list
    const ul = line.match(/^[-*]\s+(.+)$/);
    if (ul) {
      closePara();
      if (inList !== "ul") {
        closeList();
        out.push("<ul>");
        inList = "ul";
      }
      out.push(`<li>${inline(ul[1])}</li>`);
      continue;
    }
    // Ordered list
    const ol = line.match(/^\d+\.\s+(.+)$/);
    if (ol) {
      closePara();
      if (inList !== "ol") {
        closeList();
        out.push("<ol>");
        inList = "ol";
      }
      out.push(`<li>${inline(ol[1])}</li>`);
      continue;
    }
    // Paragraph
    closeList();
    if (!inPara) {
      out.push("<p>");
      inPara = true;
    } else {
      out.push("<br />");
    }
    out.push(inline(line));
  }
  closePara();
  closeList();
  return out.join("\n");
}

function inline(text: string): string {
  let s = text;
  // Links [text](url)
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
  // Bold **text**
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  // Italic *text* (avoid colliding with bold; assumes already replaced)
  s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  // Inline code `code`
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  return s;
}

// ---------------------------------------------------------------------------
// PRD §2 — source file → slug mapping (canonical list, in priority order).
// ---------------------------------------------------------------------------

type PlannedPage = {
  sourceFile: string; // relative to project root
  expectedSlug: string;
  priority: number; // 1 = build first (from publish-checklist §1)
};

const PLAN: PlannedPage[] = [
  // Priority pages from site-relaunch/09-WordPress-Publish-Checklist §1
  { sourceFile: "website/copy/00-split-landing.md", expectedSlug: "", priority: 1 },
  { sourceFile: "website/copy/01-business-homepage.md", expectedSlug: "business", priority: 1 },
  { sourceFile: "website/copy/02-directive-tier.md", expectedSlug: "business/services/directive", priority: 3 },
  { sourceFile: "website/copy/03-assurance-tier.md", expectedSlug: "business/services/assurance", priority: 3 },
  { sourceFile: "website/copy/04-foundation-tier.md", expectedSlug: "business/services/foundation", priority: 3 },
  { sourceFile: "website/copy/05-services-overview.md", expectedSlug: "business/services", priority: 3 },
  { sourceFile: "website/copy/06-consumer-homepage.md", expectedSlug: "personal", priority: 10 },
  { sourceFile: "website/copy/07-consumer-support.md", expectedSlug: "personal/support", priority: 10 },
  { sourceFile: "website/copy/08-consumer-pricing.md", expectedSlug: "personal/pricing", priority: 11 },
  { sourceFile: "website/copy/09-about.md", expectedSlug: "about", priority: 9 },
  { sourceFile: "website/copy/10-contact.md", expectedSlug: "business/contact", priority: 8 },
  { sourceFile: "website/copy/11-industry-healthcare.md", expectedSlug: "business/industries/healthcare", priority: 8 },
  { sourceFile: "website/copy/12-industry-legal-financial.md", expectedSlug: "business/industries/legal-financial", priority: 8 },
  { sourceFile: "website/copy/13-industry-nis2-dora.md", expectedSlug: "business/industries/nis2-dora", priority: 8 },
  { sourceFile: "website/copy/14-industry-iso27001.md", expectedSlug: "business/industries/iso27001", priority: 8 },
  { sourceFile: "website/copy/15-terms-stub.md", expectedSlug: "terms", priority: 12 },
  // Additional IA pages (PRD §2: site-relaunch/02 §B,C1-C3 and site-relaunch/07 §1A-C, Part 2)
  { sourceFile: "website/copy/17-how-our-ai-works.md", expectedSlug: "how-our-ai-works", priority: 5 },
  { sourceFile: "website/copy/18-service-aws-cloud.md", expectedSlug: "business/services/aws-cloud", priority: 6 },
  { sourceFile: "website/copy/19-service-google-workspace.md", expectedSlug: "business/services/google-workspace", priority: 6 },
  { sourceFile: "website/copy/20-service-ai-workflow-automation.md", expectedSlug: "business/services/ai-workflow-automation", priority: 6 },
  { sourceFile: "website/copy/21-service-managed-security-mdr.md", expectedSlug: "business/services/managed-security-mdr", priority: 2 },
  { sourceFile: "website/copy/22-service-cyber-insurance-readiness.md", expectedSlug: "business/services/cyber-insurance-readiness", priority: 2 },
  { sourceFile: "website/copy/23-service-security-awareness-training.md", expectedSlug: "business/services/security-awareness-training", priority: 6 },
  { sourceFile: "website/copy/24-managed-it-plans.md", expectedSlug: "managed-it-plans", priority: 4 },
];

// ---------------------------------------------------------------------------
// Build pipeline.
// ---------------------------------------------------------------------------

type BuildRow = {
  sourceFile: string;
  expectedSlug: string;
  actualSlug: string | null;
  pageTitle: string | null;
  seoTitle: string | null;
  metaDescription: string | null;
  slugMatches: boolean;
  pricingOverridesApplied: string[];
  autoPatchLinesDropped: number;
  autoPatchTokensReplaced: number;
  americanizationPassed: boolean;
  americanizationHits: Array<{ token: string; count: number }>;
  htmlBytes: number;
  status: "PARSE_FAIL" | "READY" | "BLOCKED_GATE" | "POSTED" | "POST_FAILED";
  wpPostId?: number;
  errors: string[];
};

async function buildOne(plan: PlannedPage, auth?: { user: string; pass: string; existingSlugs: string[] }): Promise<BuildRow> {
  const row: BuildRow = {
    sourceFile: plan.sourceFile,
    expectedSlug: plan.expectedSlug,
    actualSlug: null,
    pageTitle: null,
    seoTitle: null,
    metaDescription: null,
    slugMatches: false,
    pricingOverridesApplied: [],
    autoPatchLinesDropped: 0,
    autoPatchTokensReplaced: 0,
    americanizationPassed: false,
    americanizationHits: [],
    htmlBytes: 0,
    status: "PARSE_FAIL",
    errors: [],
  };

  const absPath = join(PROJECT_ROOT, plan.sourceFile);
  if (!existsSync(absPath)) {
    row.errors.push(`source file missing: ${plan.sourceFile}`);
    return row;
  }
  const raw = readFileSync(absPath, "utf8");
  const page = parseFrontmatter(absPath, raw);
  if (!page) {
    row.errors.push("frontmatter parse failed");
    return row;
  }
  row.pageTitle = page.pageTitle;
  row.actualSlug = page.slug;
  row.seoTitle = page.seoTitle;
  row.metaDescription = page.metaDescription;
  // For the homepage, expected slug is "" (front page) — accept "homepage — front page"
  if (plan.expectedSlug === "" && /homepage|front page/i.test(page.rawSlug)) {
    row.slugMatches = true;
  } else {
    row.slugMatches = page.slug === plan.expectedSlug;
  }
  if (!row.slugMatches) {
    row.errors.push(
      `slug mismatch: expected '${plan.expectedSlug}' got '${page.slug}' (raw='${page.rawSlug}')`,
    );
  }

  // §3 pricing override
  const overridden = applyPricingOverride(page.body);
  row.pricingOverridesApplied = overridden.applied;

  // PRD §8-compatible in-memory auto-patch (does not touch source files).
  const patched = autoPatchAmericanization(overridden.text, page.slug);
  row.autoPatchLinesDropped = patched.dropped;
  row.autoPatchTokensReplaced = patched.replaced;

  // markdown → HTML
  const html = mdToHtml(patched.text);
  row.htmlBytes = Buffer.byteLength(html, "utf8");

  // §6 Gate 1 — Americanization
  const gate = americanizationGate(html, page.slug);
  row.americanizationPassed = gate.passed;
  row.americanizationHits = gate.hits;

  if (!gate.passed) {
    row.status = "BLOCKED_GATE";
    return row;
  }

  if (DRY_RUN || !auth) {
    row.status = "READY";
    return row;
  }

  // §6 Gate 5 — never modify existing pages. Rename to <slug>-draft-2 on collision.
  let postSlug = page.slug;
  if (auth.existingSlugs.includes(postSlug)) {
    postSlug = `${postSlug}-draft-2`;
    row.errors.push(`slug collision; renamed to '${postSlug}'`);
  }

  const payload = {
    title: page.seoTitle ?? page.pageTitle,
    slug: postSlug,
    status: "draft",
    content: html,
    excerpt: page.metaDescription ?? "",
  };
  const res = await fetch(`${WP_BASE}/pages`, {
    method: "POST",
    headers: {
      Authorization:
        "Basic " + Buffer.from(`${auth.user}:${auth.pass}`).toString("base64"),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (res.status >= 200 && res.status < 300) {
    const json = (await res.json()) as { id: number };
    row.wpPostId = json.id;
    row.status = "POSTED";
  } else {
    row.status = "POST_FAILED";
    row.errors.push(`POST returned ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
  return row;
}

async function main() {
  if (!existsSync(LOKI_DIR)) mkdirSync(LOKI_DIR, { recursive: true });

  let auth: { user: string; pass: string; existingSlugs: string[] } | undefined;
  if (!DRY_RUN) {
    const j = JSON.parse(readFileSync(AUTH_FILE, "utf8"));
    const pass = process.env.WP_APP_PASS;
    if (!pass) {
      console.error("Live mode requires WP_APP_PASS in env. Refusing to run.");
      process.exit(2);
    }
    auth = {
      user: j.username,
      pass,
      existingSlugs: j.existing_slugs ?? [],
    };
  }

  const rows: BuildRow[] = [];
  const ordered = [...PLAN].sort((a, b) => a.priority - b.priority);
  for (const plan of ordered) {
    const row = await buildOne(plan, auth);
    rows.push(row);
  }

  const blockedGate = rows.filter((r) => r.status === "BLOCKED_GATE").length;
  const summary = {
    timestamp: new Date().toISOString(),
    mode: DRY_RUN ? "dry-run" : "live",
    blocked: blockedGate,
    gate1_blocked: blockedGate,
    created: rows.filter((r) => r.status === "POSTED").length,
    totals: {
      planned: rows.length,
      ready: rows.filter((r) => r.status === "READY").length,
      posted: rows.filter((r) => r.status === "POSTED").length,
      blocked_gate: blockedGate,
      parse_fail: rows.filter((r) => r.status === "PARSE_FAIL").length,
      post_failed: rows.filter((r) => r.status === "POST_FAILED").length,
      slug_mismatches: rows.filter((r) => !r.slugMatches).length,
    },
    rows,
  };

  writeFileSync(REPORT_FILE, JSON.stringify(summary, null, 2));
  console.log(`Wrote ${REPORT_FILE}`);
  console.log(`Mode: ${summary.mode}`);
  console.log(
    `  planned=${summary.totals.planned} ready=${summary.totals.ready} posted=${summary.totals.posted} blocked=${summary.totals.blocked_gate} parse_fail=${summary.totals.parse_fail} post_failed=${summary.totals.post_failed} slug_mismatches=${summary.totals.slug_mismatches}`,
  );

  for (const r of rows) {
    const flag =
      r.status === "POSTED" || r.status === "READY"
        ? "ok"
        : r.status === "BLOCKED_GATE"
          ? "gate"
          : "FAIL";
    console.log(
      `  [${flag}] ${basename(r.sourceFile)} → ${r.actualSlug ?? "(none)"} status=${r.status}${r.americanizationHits.length ? " hits=" + r.americanizationHits.map((h) => `${h.token}×${h.count}`).join(",") : ""}${r.pricingOverridesApplied.length ? " priced(" + r.pricingOverridesApplied.length + ")" : ""}${r.errors.length ? " errs(" + r.errors.length + ")" : ""}`,
    );
  }

  // Exit 0 in dry-run regardless of gate; exit 1 if live mode had any failures.
  if (!DRY_RUN && (summary.totals.post_failed > 0 || summary.totals.blocked_gate > 0)) {
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("wp-build-pages failed:", err);
  process.exit(1);
});
