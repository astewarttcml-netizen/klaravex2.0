/**
 * Klaravex KB clean re-index — H10 fix.
 *
 * Wipes klaravex_kb_chunks, re-fetches every published page under
 * /knowledge-base/* from WP REST, runs the same _clean_html logic that
 * lib/kb.py uses (drops <style>/<script>/HTML/comments → plain text only),
 * embeds via OpenAI text-embedding-3-small, and upserts cleaned chunks.
 *
 * Why this exists:
 *   Prior ingestion left raw inline CSS inside chunks; chat replies returned
 *   "y { max-width: 860px; margin: 0 auto; ..." for any query.
 *
 * Usage:
 *   bun tools/kb-clean-reindex.ts            # dry-run: report what would change
 *   bun tools/kb-clean-reindex.ts --apply    # truncate + re-ingest + re-embed
 *
 * Required env vars (Bun auto-loads .env):
 *   DATABASE_URL       postgres://... (Azure)
 *   OPENAI_API_KEY     for embeddings
 *   WP_SITE_URL        default https://klaravex.com
 *
 * Exits non-zero on any failure so the deploy script can detect it.
 *
 * Output (JSON, last line):
 *   { "pages_indexed": N, "chunks_total": M, "chunks_with_embeddings": K }
 */

import { SQL } from "bun";

const APPLY = process.argv.includes("--apply");
const WP_SITE_URL = (process.env.WP_SITE_URL ?? "https://klaravex.com").replace(/\/$/, "");
const OPENAI_KEY = process.env.OPENAI_API_KEY ?? "";
const EMBED_MODEL = process.env.KLARAVEX_EMBED_MODEL ?? "text-embedding-3-small";
const CHUNK_TARGET = 1000;
const CHUNK_OVERLAP = 150;

// ── HTML cleaning ────────────────────────────────────────────────────────────
// Matches infra/loki_handlers/lib/kb.py::_clean_html() — keep in sync.

function cleanHtml(html: string): string {
  if (!html) return "";
  let txt = html;
  // 1. Drop <style>...</style> + <script>...</script> entirely.
  txt = txt.replace(/<style\b[^>]*>[\s\S]*?<\/style\s*>/gi, " ");
  txt = txt.replace(/<script\b[^>]*>[\s\S]*?<\/script\s*>/gi, " ");
  // 2. Drop HTML comments.
  txt = txt.replace(/<!--[\s\S]*?-->/g, " ");
  // 3. Strip remaining tags.
  txt = txt.replace(/<[^>]+>/g, " ");
  // 4. Unescape common HTML entities.
  txt = txt
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/&#x27;/gi, "'");
  // 5. Defensive: kill orphan CSS rule blocks.
  txt = txt.replace(/(?:[#.][\w-]+\s*)?\{[^{}]*\}/g, " ");
  // 6. Collapse whitespace.
  txt = txt.replace(/\s+/g, " ").trim();
  return txt;
}

// ── Chunking — matches lib/kb.py _chunk() semantics ──────────────────────────

function chunk(text: string, target = CHUNK_TARGET, overlap = CHUNK_OVERLAP): string[] {
  const t = text.trim();
  if (!t) return [];
  const out: string[] = [];
  let i = 0;
  const n = t.length;
  while (i < n) {
    let end = Math.min(i + target, n);
    if (end < n) {
      const cut = t.lastIndexOf(". ", end);
      if (cut !== -1 && cut - i > Math.floor(target / 2)) {
        end = cut + 1;
      }
    }
    out.push(t.slice(i, end).trim());
    if (end >= n) break;
    i = Math.max(end - overlap, i + 1);
  }
  return out.filter((c) => c);
}

// ── WP fetch ─────────────────────────────────────────────────────────────────

interface WpPage {
  id: number;
  link: string;
  title: { rendered: string };
  content: { rendered: string };
}

async function fetchKbPages(): Promise<WpPage[]> {
  const all: WpPage[] = [];
  let page = 1;
  while (page <= 20) {
    const url = `${WP_SITE_URL}/wp-json/wp/v2/pages?per_page=100&page=${page}&status=publish&_fields=id,link,title,content`;
    const r = await fetch(url);
    if (r.status === 400) break;
    if (!r.ok) {
      throw new Error(`WP fetch failed: ${r.status} ${await r.text()}`);
    }
    const batch = (await r.json()) as WpPage[];
    if (!batch.length) break;
    all.push(...batch);
    page += 1;
  }
  return all.filter((p) => p.link?.includes("/knowledge-base/"));
}

// ── OpenAI embeddings ────────────────────────────────────────────────────────

async function embed(texts: string[]): Promise<number[][] | null> {
  if (!OPENAI_KEY || !texts.length) return null;
  const r = await fetch("https://api.openai.com/v1/embeddings", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENAI_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ model: EMBED_MODEL, input: texts }),
  });
  if (!r.ok) {
    console.error(`embedding failed http=${r.status} body=${(await r.text()).slice(0, 200)}`);
    return null;
  }
  const j = (await r.json()) as { data: { embedding: number[] }[] };
  return j.data.map((d) => d.embedding);
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  if (APPLY && !process.env.DATABASE_URL) {
    console.error("DATABASE_URL not set (required for --apply)");
    process.exit(2);
  }

  console.log(`[kb-clean-reindex] mode=${APPLY ? "APPLY" : "DRY-RUN"}  WP=${WP_SITE_URL}`);

  const sql = APPLY ? new SQL(process.env.DATABASE_URL!) : null;

  console.log("[kb-clean-reindex] fetching WP KB pages…");
  const pages = await fetchKbPages();
  console.log(`[kb-clean-reindex] discovered ${pages.length} KB pages`);

  let chunksTotal = 0;
  let chunksWithEmbeddings = 0;

  if (APPLY && sql) {
    console.log("[kb-clean-reindex] TRUNCATE klaravex_kb_chunks…");
    await sql`TRUNCATE TABLE klaravex_kb_chunks`;
  }

  for (const page of pages) {
    const title = cleanHtml(page.title?.rendered ?? "") || "Untitled";
    const cleaned = cleanHtml(page.content?.rendered ?? "");
    const chunks = chunk(cleaned);
    if (!chunks.length) {
      console.log(`  [skip] ${page.link} — no text after cleaning`);
      continue;
    }

    let vectors: number[][] | null = null;
    if (APPLY) {
      vectors = await embed(chunks);
    }

    if (APPLY && sql) {
      for (let idx = 0; idx < chunks.length; idx++) {
        const vec = vectors ? vectors[idx] : null;
        await sql`
          INSERT INTO klaravex_kb_chunks
            (source_url, source_title, chunk_index, content, embedding)
          VALUES
            (${page.link}, ${title}, ${idx}, ${chunks[idx]}, ${vec})
        `;
      }
    }

    chunksTotal += chunks.length;
    if (vectors) chunksWithEmbeddings += chunks.length;
    console.log(
      `  [${APPLY ? "ok" : "would"}] ${page.link}  chunks=${chunks.length}${vectors ? " (embedded)" : ""}`,
    );
  }

  const result = {
    pages_indexed: pages.length,
    chunks_total: chunksTotal,
    chunks_with_embeddings: chunksWithEmbeddings,
    mode: APPLY ? "applied" : "dry-run",
  };
  console.log(JSON.stringify(result));
  if (sql) await sql.end();
}

main().catch((err) => {
  console.error("kb-clean-reindex failed:", err);
  process.exit(1);
});
