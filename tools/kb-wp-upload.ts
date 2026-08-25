#!/usr/bin/env bun
// Usage: WP_USER=astewart.tcml@gmail.com WP_APP_PASS="xxxx xxxx xxxx xxxx xxxx xxxx" bun tools/kb-wp-upload.ts [--update]

import { join } from "node:path";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const WP_USER = process.env.WP_USER;
const WP_APP_PASS = process.env.WP_APP_PASS;
const WP_REST_BASE =
  process.env.WP_REST_BASE ?? "https://klaravex.com/wp-json/wp/v2";
const UPDATE_MODE = process.argv.includes("--update");
const PROJECT_ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const KB_DIR = join(PROJECT_ROOT, "content/knowledge-base");

if (!WP_USER || !WP_APP_PASS) {
  console.error(
    "ERROR: WP_USER and WP_APP_PASS environment variables are required."
  );
  console.error(
    "  Usage: WP_USER=you@example.com WP_APP_PASS=\"xxxx xxxx xxxx xxxx xxxx xxxx\" bun tools/kb-wp-upload.ts [--update]"
  );
  process.exit(1);
}

const AUTH_HEADER = "Basic " + Buffer.from(`${WP_USER}:${WP_APP_PASS}`).toString("base64");
const JSON_HEADERS = {
  Authorization: AUTH_HEADER,
  "Content-Type": "application/json",
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FrontMatter {
  slug: string;
  title: string;
  parent_slug?: string;
  status?: string;
}

interface WpPage {
  id: number;
  slug: string;
  link: string;
}

// ---------------------------------------------------------------------------
// Front-matter parser
// ---------------------------------------------------------------------------

function parseFrontMatter(raw: string): { fm: FrontMatter; body: string } {
  const parts = raw.split(/^---\s*$/m);
  // parts[0] = "" (before first ---), parts[1] = YAML block, parts[2+] = body
  if (parts.length < 3) {
    throw new Error("No YAML front-matter block found (expected --- delimiters).");
  }

  const yamlBlock = parts[1];
  const body = parts.slice(2).join("---").trim();

  const fm: Partial<FrontMatter> = {};
  for (const line of yamlBlock.split("\n")) {
    const match = line.match(/^(\w+)\s*:\s*(.+)$/);
    if (match) {
      const key = match[1].trim();
      const value = match[2].trim().replace(/^["']|["']$/g, "");
      (fm as Record<string, string>)[key] = value;
    }
  }

  if (!fm.slug) throw new Error("Front-matter missing required field: slug");
  if (!fm.title) throw new Error("Front-matter missing required field: title");

  return { fm: fm as FrontMatter, body };
}

// ---------------------------------------------------------------------------
// WP REST helpers
// ---------------------------------------------------------------------------

async function getPageBySlug(slug: string): Promise<WpPage | null> {
  const url = `${WP_REST_BASE}/pages?slug=${encodeURIComponent(slug)}&status=any`;
  const res = await fetch(url, { headers: { Authorization: AUTH_HEADER } });
  if (!res.ok) {
    throw new Error(`GET /pages?slug=${slug} → HTTP ${res.status}: ${await res.text()}`);
  }
  const pages: WpPage[] = await res.json();
  return pages.length > 0 ? pages[0] : null;
}

async function getParentId(parentSlug: string): Promise<number> {
  if (!parentSlug) return 0;
  const page = await getPageBySlug(parentSlug);
  if (!page) {
    console.warn(`  WARN: parent page "${parentSlug}" not found — will create with parent=0`);
    return 0;
  }
  return page.id;
}

async function createPage(payload: object): Promise<WpPage> {
  const res = await fetch(`${WP_REST_BASE}/pages`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`POST /pages → HTTP ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

async function updatePage(id: number, payload: object): Promise<WpPage> {
  const res = await fetch(`${WP_REST_BASE}/pages/${id}`, {
    method: "POST", // WP REST accepts POST for updates (same as PUT)
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`POST /pages/${id} → HTTP ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const glob = new Bun.Glob("*.md");
  const files = Array.from(glob.scanSync(KB_DIR)).sort();

  if (files.length === 0) {
    console.log("No .md files found in", KB_DIR);
    return;
  }

  console.log(`Found ${files.length} KB article(s) in ${KB_DIR}`);
  console.log(`Mode: ${UPDATE_MODE ? "CREATE + UPDATE" : "CREATE only (pass --update to also update existing)"}\n`);

  // Parent ID cache to avoid redundant lookups
  const parentIdCache = new Map<string, number>();

  let created = 0;
  let updated = 0;
  let skipped = 0;
  let failed = 0;

  for (const file of files) {
    const filePath = join(KB_DIR, file);
    const raw = await Bun.file(filePath).text();

    let fm: FrontMatter;
    let body: string;

    try {
      ({ fm, body } = parseFrontMatter(raw));
    } catch (err) {
      console.error(`[FAIL] ${file} — front-matter parse error: ${(err as Error).message}`);
      failed++;
      continue;
    }

    try {
      // Resolve parent ID (cached)
      let parentId = 0;
      if (fm.parent_slug) {
        if (parentIdCache.has(fm.parent_slug)) {
          parentId = parentIdCache.get(fm.parent_slug)!;
        } else {
          parentId = await getParentId(fm.parent_slug);
          parentIdCache.set(fm.parent_slug, parentId);
        }
      }

      // Check if page already exists
      const existing = await getPageBySlug(fm.slug);

      const payload = {
        title: fm.title,
        content: body,
        slug: fm.slug,
        status: fm.status ?? "publish",
        parent: parentId,
      };

      if (existing) {
        if (UPDATE_MODE) {
          const updated_page = await updatePage(existing.id, payload);
          console.log(`[UPDATE] ${fm.slug} → page_id ${updated_page.id}`);
          updated++;
        } else {
          console.log(`[SKIP]   ${fm.slug} → page_id ${existing.id} (already exists, skipping)`);
          skipped++;
        }
      } else {
        const created_page = await createPage(payload);
        console.log(`[CREATE] ${fm.slug} → page_id ${created_page.id}`);
        created++;
      }
    } catch (err) {
      console.error(`[FAIL]   ${fm.slug} — ${(err as Error).message}`);
      failed++;
    }
  }

  console.log(`\n--- Summary ---`);
  console.log(`  Created: ${created}`);
  console.log(`  Updated: ${updated}`);
  console.log(`  Skipped: ${skipped}`);
  console.log(`  Failed:  ${failed}`);
  console.log(`  Total:   ${files.length}`);

  if (failed > 0) process.exit(1);
}

main();
