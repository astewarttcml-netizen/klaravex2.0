#!/usr/bin/env bun
// PRD Phase 5 — slug remediation for klaravex.com WordPress draft pages.
//
// For each of the 24 Loki-created drafts in .loki/wp-build-pages.report.json:
//   1. Resolve the desired leaf slug + nested parent chain from the IA table.
//   2. Find or create the parent hub page (business, services, industries).
//   3. PATCH /wp-json/wp/v2/pages/{id} with { slug, parent }.
//   4. Verify the resulting permalink via GET /pages/{id}?_fields=link.
//
// Collision rules (PRD §5): only 4 named slugs may DELETE-and-replace an
// existing page, and only when that existing page is "empty/template"
// (<200 chars text, OR title matches WP-defaults, OR author=1 never modified).
// All other collisions keep the Loki draft on its `-2` slug and emit a
// manual-follow-up row.
//
// Auth: reads WP_APP_PASS the same way wp-build-auth.ts does
// (env -> .loki/.wp_app_pass.scratch -> 1Password CLI). Username comes from
// .loki/wp-auth.json. Without a usable credential this exits with code 2.
//
// Modes:
//   --dry-run    Plan all PATCH/POST/DELETE ops; no network mutations.
//   (default)    Execute plan against live WordPress.

import {
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";

const PROJECT_ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const LOKI_DIR = join(PROJECT_ROOT, ".loki");
const AUTH_FILE = join(LOKI_DIR, "wp-auth.json");
const BUILD_REPORT = join(LOKI_DIR, "wp-build-pages.report.json");
const REMEDIATE_REPORT = join(LOKI_DIR, "wp-slug-remediate.report.json");
const SCRATCH = join(LOKI_DIR, ".wp_app_pass.scratch");
const WP_BASE = "https://klaravex.com/wp-json/wp/v2";

const DRY_RUN = process.argv.includes("--dry-run");

// ---------------------------------------------------------------------------
// IA target hierarchy (PRD §5). Maps source filename -> nested path segments.
// The last segment is the leaf slug; the chain before it forms the parent
// lookup. Hubs (business, services, industries) are created if missing.
// ---------------------------------------------------------------------------

type IATarget = {
  // Path segments from root, e.g. ["business", "services", "aws-cloud"].
  path: string[];
  // True for the 4 collision targets where DELETE-then-claim is permitted
  // if the existing page meets the empty/template heuristic.
  collisionEligibleForDelete?: boolean;
};

const IA: Record<string, IATarget> = {
  // top-level
  "website/copy/00-split-landing.md": { path: [] }, // front page — no parent, no slug change beyond what WP gave it
  "website/copy/01-business-homepage.md": { path: ["business"] },
  "website/copy/06-consumer-homepage.md": { path: ["personal"], collisionEligibleForDelete: true },
  "website/copy/09-about.md": { path: ["about"], collisionEligibleForDelete: true },
  "website/copy/15-terms-stub.md": { path: ["terms"], collisionEligibleForDelete: true },
  "site-relaunch/02-Content-Drafts.md#B": { path: ["how-our-ai-works"], collisionEligibleForDelete: true },

  // /business/...
  "website/copy/10-contact.md": { path: ["business", "contact"] },
  "website/copy/05-services-overview.md": { path: ["business", "services"] },

  // /business/services/*
  "website/copy/02-directive-tier.md": { path: ["business", "services", "directive"] },
  "website/copy/03-assurance-tier.md": { path: ["business", "services", "assurance"] },
  "website/copy/04-foundation-tier.md": { path: ["business", "services", "foundation"] },
  "website/copy/18-service-aws-cloud.md": { path: ["business", "services", "aws-cloud"] },
  "website/copy/19-service-google-workspace.md": { path: ["business", "services", "google-workspace"] },
  "website/copy/20-service-ai-workflow-automation.md": { path: ["business", "services", "ai-workflow-automation"] },
  "website/copy/21-service-managed-security-mdr.md": { path: ["business", "services", "managed-security-mdr"] },
  "website/copy/22-service-cyber-insurance-readiness.md": { path: ["business", "services", "cyber-insurance-readiness"] },
  "website/copy/23-service-security-awareness-training.md": { path: ["business", "services", "security-awareness-training"] },

  // /business/industries/*
  "website/copy/11-industry-healthcare.md": { path: ["business", "industries", "healthcare"] },
  "website/copy/12-industry-legal-financial.md": { path: ["business", "industries", "legal-financial"] },
  "website/copy/13-industry-nis2-dora.md": { path: ["business", "industries", "nis2-dora"] },
  "website/copy/14-industry-iso27001.md": { path: ["business", "industries", "iso27001"] },

  // /personal/*
  "website/copy/07-consumer-support.md": { path: ["personal", "support"] },
  "website/copy/08-consumer-pricing.md": { path: ["personal", "pricing"] },

  // flat (no parent)
  "website/copy/24-managed-it-plans.md": { path: ["managed-it-plans"] },
  "website/copy/17-how-our-ai-works.md": { path: ["how-our-ai-works"], collisionEligibleForDelete: true },
  "website/copy/16-utility-pages.md": { path: [] }, // covers thank-you/industries/how-it-works/legal/footer — no single page
};

// ---------------------------------------------------------------------------
// Types reflecting the source reports.
// ---------------------------------------------------------------------------

type BuildRow = {
  sourceFile: string;
  expectedSlug: string;
  actualSlug: string;
  pageTitle: string;
  wpPostId?: number;
  status: string;
};

type BuildReport = {
  timestamp: string;
  mode: string;
  rows: BuildRow[];
};

type AuthRecord = {
  status: string;
  username: string;
  rest_base: string;
  existing_slugs: { id: number; slug: string; status: string }[];
};

type WPPage = {
  id: number;
  slug: string;
  status: string;
  title: { rendered: string };
  content: { rendered: string };
  link: string;
  parent: number;
  author: number;
  date: string;
  modified: string;
};

type PlanOp =
  | { kind: "create_hub"; slug: string; parent: number; title: string }
  | { kind: "patch_child"; postId: number; slug: string; parent: number; title: string }
  | { kind: "delete_collider"; postId: number; reason: string }
  | { kind: "keep_collision"; postId: number; reason: string };

// ---------------------------------------------------------------------------
// Credential resolution (env -> scratch -> 1Password CLI).
// ---------------------------------------------------------------------------

async function fetchAppPassword(): Promise<string> {
  if (process.env.WP_APP_PASS) return process.env.WP_APP_PASS.trim();
  if (existsSync(SCRATCH)) {
    const pw = readFileSync(SCRATCH, "utf8").trim();
    rmSync(SCRATCH);
    return pw;
  }
  const proc = Bun.spawn(
    ["op", "item", "get", "2b2i27eib6v43bsogeaydmagbu", "--fields", "password", "--reveal"],
    { stdout: "pipe", stderr: "pipe" },
  );
  const code = await proc.exited;
  if (code !== 0) {
    const err = await new Response(proc.stderr).text();
    throw new Error(`op CLI failed (exit ${code}): ${err.trim()}`);
  }
  return (await new Response(proc.stdout).text()).trim();
}

function basicAuth(user: string, pass: string): string {
  return "Basic " + Buffer.from(`${user}:${pass}`).toString("base64");
}

// ---------------------------------------------------------------------------
// REST helpers.
// ---------------------------------------------------------------------------

type Auth = { header: string };

async function getPage(auth: Auth, id: number): Promise<WPPage> {
  const res = await fetch(
    `${WP_BASE}/pages/${id}?context=edit&_fields=id,slug,status,title,content,link,parent,author,date,modified`,
    { headers: { Authorization: auth.header } },
  );
  if (!res.ok) throw new Error(`GET /pages/${id} -> HTTP ${res.status}`);
  return (await res.json()) as WPPage;
}

async function getPageBySlug(
  auth: Auth,
  slug: string,
): Promise<WPPage | null> {
  const res = await fetch(
    `${WP_BASE}/pages?slug=${encodeURIComponent(slug)}&status=any&context=edit` +
      `&_fields=id,slug,status,title,content,link,parent,author,date,modified`,
    { headers: { Authorization: auth.header } },
  );
  if (!res.ok) throw new Error(`GET /pages?slug=${slug} -> HTTP ${res.status}`);
  const rows = (await res.json()) as WPPage[];
  return rows.length > 0 ? rows[0] : null;
}

async function createHub(
  auth: Auth,
  slug: string,
  title: string,
  parent: number,
): Promise<WPPage> {
  const body = {
    title,
    slug,
    status: "draft",
    parent,
    content: `<!-- wp:paragraph --><p>Coming soon — Klaravex ${title} hub. Placeholder created by Loki Phase 5 remediation.</p><!-- /wp:paragraph -->`,
  };
  const res = await fetch(`${WP_BASE}/pages`, {
    method: "POST",
    headers: {
      Authorization: auth.header,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST /pages (hub ${slug}) -> HTTP ${res.status}: ${text}`);
  }
  return (await res.json()) as WPPage;
}

async function patchPage(
  auth: Auth,
  id: number,
  patch: { slug?: string; parent?: number },
): Promise<WPPage> {
  const res = await fetch(`${WP_BASE}/pages/${id}`, {
    method: "POST", // WP REST accepts POST for updates as well as PATCH
    headers: {
      Authorization: auth.header,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PATCH /pages/${id} -> HTTP ${res.status}: ${text}`);
  }
  return (await res.json()) as WPPage;
}

async function deletePage(auth: Auth, id: number): Promise<void> {
  const res = await fetch(`${WP_BASE}/pages/${id}?force=true`, {
    method: "DELETE",
    headers: { Authorization: auth.header },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`DELETE /pages/${id} -> HTTP ${res.status}: ${text}`);
  }
}

// ---------------------------------------------------------------------------
// Empty/template heuristic (PRD §5 collision rules).
// ---------------------------------------------------------------------------

function isEmptyOrTemplate(page: WPPage): { yes: boolean; reason: string } {
  const text = page.content.rendered
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (text.length < 200) {
    return { yes: true, reason: `content text length ${text.length} < 200` };
  }
  const wpDefaults = ["Sample Page", "Privacy Policy"];
  if (wpDefaults.includes(page.title.rendered)) {
    return { yes: true, reason: `title is WP-default '${page.title.rendered}'` };
  }
  if (page.author === 1 && page.date === page.modified) {
    return {
      yes: true,
      reason: `author=1 and never modified (date == modified == ${page.date})`,
    };
  }
  return { yes: false, reason: `${text.length} chars, modified ${page.modified}` };
}

// ---------------------------------------------------------------------------
// Hub resolution: returns post_id, creating a draft placeholder if missing.
// In dry-run we still query; we just skip the POST and return -1.
// ---------------------------------------------------------------------------

async function resolveHub(
  auth: Auth,
  slug: string,
  title: string,
  parentId: number,
  plan: PlanOp[],
  existingSlugs: { id: number; slug: string; status: string }[],
): Promise<number> {
  // Cached path: if wp-auth.json already lists this slug, trust the id.
  const cached = existingSlugs.find((s) => s.slug === slug);
  if (cached) return cached.id;
  // Live lookup needs a real auth header.
  if (auth.header) {
    const existing = await getPageBySlug(auth, slug);
    if (existing) return existing.id;
  }
  plan.push({ kind: "create_hub", slug, parent: parentId, title });
  if (DRY_RUN) return -1;
  const created = await createHub(auth, slug, title, parentId);
  return created.id;
}

// ---------------------------------------------------------------------------
// Main.
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  if (!existsSync(LOKI_DIR)) mkdirSync(LOKI_DIR, { recursive: true });
  if (!existsSync(AUTH_FILE)) {
    console.error(`FATAL: missing ${AUTH_FILE}. Run wp-build-auth.ts first.`);
    process.exit(2);
  }
  if (!existsSync(BUILD_REPORT)) {
    console.error(`FATAL: missing ${BUILD_REPORT}. Run wp-build-pages.ts first.`);
    process.exit(2);
  }

  const auth = JSON.parse(readFileSync(AUTH_FILE, "utf8")) as AuthRecord;
  const buildReport = JSON.parse(readFileSync(BUILD_REPORT, "utf8")) as BuildReport;

  console.log(`Phase 5 — slug remediation (mode=${DRY_RUN ? "dry-run" : "live"})`);
  console.log(`  user: ${auth.username}`);
  console.log(`  drafts to consider: ${buildReport.rows.length}`);

  let appPass = "";
  let authHeader: Auth;
  try {
    appPass = await fetchAppPassword();
    authHeader = { header: basicAuth(auth.username, appPass) };
  } catch (e) {
    if (DRY_RUN) {
      console.warn(`  WARN: no App Password available — dry-run will plan from wp-auth.json only.`);
      console.warn(`  WARN: collision content inspection skipped; assumes all collisions are NON-empty.`);
      authHeader = { header: "" };
    } else {
      console.error("FATAL: could not fetch App Password.");
      console.error(String(e));
      process.exit(2);
    }
  }

  const plan: PlanOp[] = [];
  const verified: { postId: number; slug: string; link: string }[] = [];
  const failures: { postId: number; reason: string }[] = [];
  const followups: string[] = [];

  // -------------------------------------------------------------------------
  // Step 1: resolve hub IDs (business, business/services, business/industries).
  // -------------------------------------------------------------------------
  const businessId = await resolveHub(
    authHeader,
    "business",
    "Business",
    0,
    plan,
    auth.existing_slugs,
  );
  const servicesId = await resolveHub(
    authHeader,
    "services",
    "Services",
    businessId > 0 ? businessId : 0,
    plan,
    auth.existing_slugs,
  );
  const industriesId = await resolveHub(
    authHeader,
    "industries",
    "Industries",
    businessId > 0 ? businessId : 0,
    plan,
    auth.existing_slugs,
  );

  console.log(`  hubs: business=${businessId} services=${servicesId} industries=${industriesId}`);

  function parentIdFor(path: string[]): number {
    // The parent is the deepest ancestor segment that has a known post_id.
    // We only resolve the hubs above; for any other ancestor, fall back to 0.
    if (path.length <= 1) return 0;
    const ancestor = path.slice(0, -1).join("/");
    if (ancestor === "business") return businessId;
    if (ancestor === "business/services") return servicesId;
    if (ancestor === "business/industries") return industriesId;
    if (ancestor === "personal") {
      const personal = auth.existing_slugs.find((s) => s.slug === "personal");
      return personal?.id ?? 0;
    }
    return 0;
  }

  // -------------------------------------------------------------------------
  // Step 2: per-draft PATCH or collision resolution.
  // -------------------------------------------------------------------------
  for (const row of buildReport.rows) {
    if (row.status !== "POSTED" || !row.wpPostId) continue;
    const target = IA[row.sourceFile];
    if (!target || target.path.length === 0) {
      // No remediation needed (front-page candidate or utility-pages aggregator).
      continue;
    }
    const leafSlug = target.path[target.path.length - 1];
    const parentId = parentIdFor(target.path);

    // Collision check: is there an existing page (not our draft) at this slug?
    const existing = auth.existing_slugs.find(
      (s) => s.slug === leafSlug && s.id !== row.wpPostId,
    );

    if (existing && target.collisionEligibleForDelete) {
      // Eligible-for-delete path: inspect, then either DELETE+claim or keep `-2`.
      try {
        if (!authHeader.header) {
          // Dry-run without auth: assume NOT empty (conservative — kept as -2).
          plan.push({
            kind: "keep_collision",
            postId: row.wpPostId,
            reason: `dry-run without auth: cannot inspect existing id=${existing.id}; assume non-empty`,
          });
          followups.push(
            `(dry-run) Collision: leaf '${leafSlug}' eligible-for-delete but content inspection skipped (no auth).`,
          );
          continue;
        }
        const existingPage = await getPage(authHeader, existing.id);
        const verdict = isEmptyOrTemplate(existingPage);
        if (verdict.yes) {
          plan.push({
            kind: "delete_collider",
            postId: existing.id,
            reason: verdict.reason,
          });
          if (!DRY_RUN) await deletePage(authHeader, existing.id);
          plan.push({
            kind: "patch_child",
            postId: row.wpPostId,
            slug: leafSlug,
            parent: parentId,
            title: row.pageTitle,
          });
          if (!DRY_RUN) {
            const patched = await patchPage(authHeader, row.wpPostId, {
              slug: leafSlug,
              parent: parentId,
            });
            verified.push({
              postId: patched.id,
              slug: patched.slug,
              link: patched.link,
            });
          }
        } else {
          plan.push({
            kind: "keep_collision",
            postId: row.wpPostId,
            reason: `existing id=${existing.id} has real content: ${verdict.reason}`,
          });
          followups.push(
            `Collision: leaf '${leafSlug}' — existing id=${existing.id} (${existing.status}) has real content. ` +
              `Loki draft id=${row.wpPostId} kept on '-2' slug. Compare and choose keeper.`,
          );
          // Still set the parent so the draft sits in the right tree, even with -2 slug.
          if (!DRY_RUN && parentId > 0) {
            await patchPage(authHeader, row.wpPostId, { parent: parentId });
          }
        }
      } catch (e) {
        failures.push({ postId: row.wpPostId, reason: String(e) });
      }
      continue;
    }

    if (existing) {
      // Non-delete-eligible collision (Gate 5): keep `-2`, reparent only.
      plan.push({
        kind: "keep_collision",
        postId: row.wpPostId,
        reason: `existing id=${existing.id} (${existing.status}) at slug '${leafSlug}' — Gate 5 forbids deletion`,
      });
      followups.push(
        `Collision: leaf '${leafSlug}' — existing id=${existing.id} (${existing.status}). ` +
          `Loki draft id=${row.wpPostId} kept on its WP-sanitized slug. Manual reconciliation required.`,
      );
      if (!DRY_RUN && parentId > 0) {
        try {
          await patchPage(authHeader, row.wpPostId, { parent: parentId });
        } catch (e) {
          failures.push({ postId: row.wpPostId, reason: String(e) });
        }
      }
      continue;
    }

    // No collision: PATCH cleanly to leaf slug + parent.
    plan.push({
      kind: "patch_child",
      postId: row.wpPostId,
      slug: leafSlug,
      parent: parentId,
      title: row.pageTitle,
    });
    if (!DRY_RUN) {
      try {
        const patched = await patchPage(authHeader, row.wpPostId, {
          slug: leafSlug,
          parent: parentId,
        });
        verified.push({
          postId: patched.id,
          slug: patched.slug,
          link: patched.link,
        });
      } catch (e) {
        failures.push({ postId: row.wpPostId, reason: String(e) });
      }
    }
  }

  // -------------------------------------------------------------------------
  // Step 3: write report and exit.
  // -------------------------------------------------------------------------
  const report = {
    timestamp: new Date().toISOString(),
    mode: DRY_RUN ? "dry-run" : "live",
    hubs: { businessId, servicesId, industriesId },
    plan,
    verified,
    failures,
    followups,
  };
  writeFileSync(REMEDIATE_REPORT, JSON.stringify(report, null, 2));
  console.log(
    `  plan ops: ${plan.length}  verified: ${verified.length}  failures: ${failures.length}  followups: ${followups.length}`,
  );
  console.log(`  wrote ${REMEDIATE_REPORT}`);
  if (failures.length > 0) {
    console.error("Phase 5 completed WITH FAILURES — see report.");
    process.exit(5);
  }
  console.log("Phase 5 OK.");
}

main().catch((e) => {
  console.error("UNCAUGHT:", e);
  process.exit(1);
});
