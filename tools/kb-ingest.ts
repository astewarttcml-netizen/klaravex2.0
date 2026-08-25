/**
 * Klaravex KB ingestion tool — T6.0.3
 *
 * Pulls every published page under /knowledge-base/* from the WP REST API,
 * chunks content into ~500-token segments, generates a 1-sentence summary per
 * chunk using Claude Haiku, and upserts into klaravex_kb_chunks.
 *
 * Usage:
 *   bun tools/kb-ingest.ts
 *
 * Required env vars (auto-loaded from .env by Bun):
 *   DATABASE_URL          Postgres connection string
 *   ANTHROPIC_API_KEY     Anthropic API key
 *   WP_BASE_URL           WordPress site base URL (default: https://klaravex.com)
 *
 * WP auth: reads /tmp/klaravex_session_keys/wp_app_pass (username astewarttcml_iw04eh9p)
 */

import Anthropic from "@anthropic-ai/sdk";
import { createHash } from "crypto";

// ── Config ────────────────────────────────────────────────────────────────────

const WP_BASE_URL = process.env.WP_BASE_URL ?? "https://klaravex.com";
const WP_API = `${WP_BASE_URL}/wp-json/wp/v2`;
const WP_USER = "astewarttcml_iw04eh9p";
const WP_APP_PASS_FILE = "/tmp/klaravex_session_keys/wp_app_pass";
const CHUNK_TOKEN_TARGET = 500;
const HAIKU_MODEL = "claude-haiku-4-5-20251001";

// ── Types ─────────────────────────────────────────────────────────────────────

interface WpPage {
  id: number;
  slug: string;
  link: string;
  title: { rendered: string };
  content: { rendered: string };
}

interface KbChunk {
  page_id: number;
  page_title: string;
  page_url: string;
  chunk_index: number;
  chunk_text: string;
  summary: string;
  source_hash: string;
}

// ── WP helpers ────────────────────────────────────────────────────────────────

async function getWpAuth(): Promise<string> {
  const pass = (await Bun.file(WP_APP_PASS_FILE).text()).trim();
  return Buffer.from(`${WP_USER}:${pass}`).toString("base64");
}

async function wpGet(path: string, auth: string): Promise<unknown> {
  const res = await fetch(`${WP_API}${path}`, {
    headers: { Authorization: `Basic ${auth}` },
  });
  if (!res.ok) {
    throw new Error(`WP API ${path} → ${res.status} ${await res.text()}`);
  }
  return res.json();
}

async function findKbParentId(auth: string): Promise<number> {
  const pages = (await wpGet(
    "/pages?per_page=100&slug=knowledge-base",
    auth
  )) as WpPage[];
  if (!pages.length) {
    throw new Error("Could not find a page with slug 'knowledge-base'");
  }
  return pages[0].id;
}

async function fetchKbPages(parentId: number, auth: string): Promise<WpPage[]> {
  const pages = (await wpGet(
    `/pages?per_page=100&parent=${parentId}&status=publish`,
    auth
  )) as WpPage[];
  return pages;
}

// ── HTML strip ────────────────────────────────────────────────────────────────

function stripHtml(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'")
    .replace(/\s{2,}/g, " ")
    .trim();
}

// ── Chunking (paragraph-based, ~500 tokens) ───────────────────────────────────
// Rough token estimate: 1 token ≈ 4 characters.

const CHARS_PER_TARGET = CHUNK_TOKEN_TARGET * 4;

function chunkText(text: string): string[] {
  const paragraphs = text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);

  const chunks: string[] = [];
  let current = "";

  for (const para of paragraphs) {
    if (current.length + para.length + 2 > CHARS_PER_TARGET && current.length > 0) {
      chunks.push(current.trim());
      current = para;
    } else {
      current = current ? `${current}\n\n${para}` : para;
    }
  }
  if (current.trim()) {
    chunks.push(current.trim());
  }
  return chunks.length ? chunks : [text.slice(0, CHARS_PER_TARGET)];
}

// ── Anthropic summary ─────────────────────────────────────────────────────────

async function summariseChunk(
  client: Anthropic,
  chunk: string
): Promise<string> {
  const msg = await client.messages.create({
    model: HAIKU_MODEL,
    max_tokens: 120,
    messages: [
      {
        role: "user",
        content: `Summarise the following text in exactly one sentence (≤25 words):\n\n${chunk.slice(0, 2000)}`,
      },
    ],
  });
  const block = msg.content[0];
  return block.type === "text" ? block.text.trim() : "";
}

// ── Postgres upsert ───────────────────────────────────────────────────────────

async function upsertChunks(chunks: KbChunk[]): Promise<void> {
  if (!chunks.length) return;

  const db = Bun.sql;

  for (const c of chunks) {
    await db`
      INSERT INTO klaravex_kb_chunks
        (page_id, page_title, page_url, chunk_index, chunk_text, summary, source_hash)
      VALUES
        (${c.page_id}, ${c.page_title}, ${c.page_url}, ${c.chunk_index},
         ${c.chunk_text}, ${c.summary}, ${c.source_hash})
      ON CONFLICT (source_hash) DO UPDATE SET
        page_title  = EXCLUDED.page_title,
        page_url    = EXCLUDED.page_url,
        chunk_text  = EXCLUDED.chunk_text,
        summary     = EXCLUDED.summary
    `;
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const auth = await getWpAuth();
  const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

  console.log("Finding knowledge-base parent page…");
  const parentId = await findKbParentId(auth);
  console.log(`KB parent page ID: ${parentId}`);

  const pages = await fetchKbPages(parentId, auth);
  console.log(`Found ${pages.length} published KB pages`);

  let totalChunks = 0;

  for (const page of pages) {
    const plainText = stripHtml(page.content.rendered);
    const textChunks = chunkText(plainText);
    const pageTitle = stripHtml(page.title.rendered);

    const kbChunks: KbChunk[] = [];

    for (let idx = 0; idx < textChunks.length; idx++) {
      const chunkText = textChunks[idx];
      const sourceHash = createHash("sha256")
        .update(`${page.id}:${idx}:${chunkText}`)
        .digest("hex");

      const summary = await summariseChunk(anthropic, chunkText);

      kbChunks.push({
        page_id: page.id,
        page_title: pageTitle,
        page_url: page.link,
        chunk_index: idx,
        chunk_text: chunkText,
        summary,
        source_hash: sourceHash,
      });
    }

    await upsertChunks(kbChunks);
    totalChunks += kbChunks.length;
    console.log(
      `  [${page.slug}] ${kbChunks.length} chunk(s) indexed (page ${page.id})`
    );
  }

  console.log(`\nIndexed ${pages.length} pages, ${totalChunks} chunks`);
}

main().catch((err) => {
  console.error("kb-ingest failed:", err);
  process.exit(1);
});
