#!/usr/bin/env bun
/**
 * Klaravex Stripe SKU repricer
 * ────────────────────────────
 * Bulk-applies a price change to one or more Stripe SKUs:
 *   1. Creates a new Price object at the target amount.
 *   2. Creates a new Payment Link from that Price.
 *   3. Deactivates the OLD Price (preserves historical transactions).
 *   4. Writes the new ID triplet back into .loki/stripe-products-consumer.json
 *      (or stripe-products-b2b.json).
 *
 * Use after Anthony finalises the R/K/D decisions in
 *   .loki/state/price-drift-2026-06-10.md
 *
 * Usage:
 *   bun tools/reprice-stripe.ts --decisions ./reprice-decisions.json --dry-run
 *   bun tools/reprice-stripe.ts --decisions ./reprice-decisions.json --apply
 *
 * Decisions file shape:
 *   {
 *     "currency": "USD",
 *     "decisions": [
 *       { "sku": "per-incident",     "action": "R", "target_cents": 5900 },
 *       { "sku": "tech-kit",         "action": "R", "target_cents": 9900 },
 *       { "sku": "essentials",       "action": "K" },
 *       { "sku": "family-senior",    "action": "D" }
 *     ]
 *   }
 *
 * Hard rules:
 *   - --dry-run by default. --apply must be explicit.
 *   - K (keep) and D (defer) do nothing — only logged.
 *   - On any Stripe API error, the script ABORTS — partial state is bad here.
 *   - On success, JSON is overwritten with the new IDs. Old IDs are still in
 *     Stripe (just deactivated) so historical reporting is intact.
 *   - The old PAYMENT LINK URL stays live unless you also deactivate it via
 *     the dashboard — payment links are a separate object from prices.
 *     This script flags any old links that should be deactivated.
 *
 * Required env:
 *   STRIPE_SECRET_KEY=sk_live_…
 *
 * Optional env:
 *   STRIPE_API_BASE=https://api.stripe.com/v1 (default)
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

// ── Config ──────────────────────────────────────────────────────────────────
const PROJECT_ROOT = resolve(import.meta.dir, "..");
const CONSUMER_FILE = resolve(PROJECT_ROOT, ".loki/stripe-products-consumer.json");
const B2B_FILE = resolve(PROJECT_ROOT, ".loki/stripe-products-b2b.json");
const STRIPE_BASE = process.env.STRIPE_API_BASE || "https://api.stripe.com/v1";

// ── Types ───────────────────────────────────────────────────────────────────
interface Sku {
  sku: string;
  name: string;
  segment: "consumer" | "b2b";
  mode: "subscription" | "one_time" | string;
  per_unit?: boolean;
  amount_cents: number;
  product_id: string;
  price_id: string;
  payment_link_id?: string;
  payment_link_url?: string;
  [k: string]: unknown;
}

interface Decision {
  sku: string;
  action: "R" | "K" | "D";
  target_cents?: number;
}

interface DecisionsFile {
  currency?: string;
  decisions: Decision[];
}

// ── Args ────────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const argMap: Record<string, string> = {};
for (let i = 0; i < args.length; i++) {
  if (args[i].startsWith("--")) {
    const key = args[i].slice(2);
    const val = args[i + 1] && !args[i + 1].startsWith("--") ? args[++i] : "true";
    argMap[key] = val;
  }
}
const decisionsPath = argMap["decisions"];
const apply = argMap["apply"] === "true";
const verbose = argMap["verbose"] === "true";

if (!decisionsPath) {
  console.error("usage: bun tools/reprice-stripe.ts --decisions <file.json> [--apply] [--verbose]");
  process.exit(2);
}
if (!existsSync(decisionsPath)) {
  console.error(`decisions file not found: ${decisionsPath}`);
  process.exit(2);
}

const decisionsRaw = JSON.parse(readFileSync(decisionsPath, "utf-8")) as DecisionsFile;
const currency = (decisionsRaw.currency || "USD").toLowerCase();
const decisions = decisionsRaw.decisions || [];

const stripeKey = process.env.STRIPE_SECRET_KEY || "";
if (apply && !stripeKey) {
  console.error("STRIPE_SECRET_KEY is required for --apply");
  process.exit(2);
}

// ── Load catalogs ───────────────────────────────────────────────────────────
function loadCatalog(path: string): Sku[] {
  if (!existsSync(path)) return [];
  return JSON.parse(readFileSync(path, "utf-8")) as Sku[];
}
const consumer = loadCatalog(CONSUMER_FILE);
const b2b = loadCatalog(B2B_FILE);

function findSku(slug: string): { entry: Sku; file: string; catalog: Sku[] } | null {
  let hit = consumer.find((s) => s.sku === slug);
  if (hit) return { entry: hit, file: CONSUMER_FILE, catalog: consumer };
  hit = b2b.find((s) => s.sku === slug);
  if (hit) return { entry: hit, file: B2B_FILE, catalog: b2b };
  return null;
}

// ── Stripe API helpers (raw fetch — no SDK dep) ─────────────────────────────
async function stripe<T>(method: string, path: string, body?: Record<string, string>): Promise<T> {
  if (!apply) {
    if (verbose) console.error(`[dry-run] ${method} ${path}`, body || "");
    // In dry-run, return a synthetic shape good enough for plan output.
    if (path === "/prices") {
      return { id: "price_DRYRUN_" + Math.random().toString(36).slice(2, 10) } as unknown as T;
    }
    if (path === "/payment_links") {
      const id = "plink_DRYRUN_" + Math.random().toString(36).slice(2, 10);
      return { id, url: `https://buy.stripe.com/${id.slice(6, 14)}` } as unknown as T;
    }
    if (path.startsWith("/prices/")) return {} as T;
    return {} as T;
  }
  const url = `${STRIPE_BASE}${path}`;
  const init: RequestInit = {
    method,
    headers: {
      Authorization: `Bearer ${stripeKey}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
  };
  if (body) init.body = new URLSearchParams(body).toString();
  const r = await fetch(url, init);
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`Stripe ${method} ${path} → ${r.status} ${text.slice(0, 400)}`);
  }
  return (await r.json()) as T;
}

// ── Plan ────────────────────────────────────────────────────────────────────
interface PlanItem {
  sku: string;
  action: "R" | "K" | "D" | "ERR";
  reason?: string;
  current_cents?: number;
  target_cents?: number;
  product_id?: string;
  old_price_id?: string;
  new_price_id?: string;
  new_payment_link_id?: string;
  new_payment_link_url?: string;
  old_payment_link_url?: string;
}

const plan: PlanItem[] = [];

for (const d of decisions) {
  const found = findSku(d.sku);
  if (!found) {
    plan.push({ sku: d.sku, action: "ERR", reason: "sku not found in any catalog" });
    continue;
  }
  const cur = found.entry;
  if (d.action === "K") {
    plan.push({
      sku: d.sku,
      action: "K",
      reason: "keep Stripe — no API call",
      current_cents: cur.amount_cents,
    });
    continue;
  }
  if (d.action === "D") {
    plan.push({
      sku: d.sku,
      action: "D",
      reason: "deferred",
      current_cents: cur.amount_cents,
    });
    continue;
  }
  if (d.action === "R") {
    if (!d.target_cents || d.target_cents < 1) {
      plan.push({ sku: d.sku, action: "ERR", reason: "R action requires target_cents > 0" });
      continue;
    }
    plan.push({
      sku: d.sku,
      action: "R",
      current_cents: cur.amount_cents,
      target_cents: d.target_cents,
      product_id: cur.product_id,
      old_price_id: cur.price_id,
      old_payment_link_url: cur.payment_link_url,
    });
    continue;
  }
  plan.push({ sku: d.sku, action: "ERR", reason: `unknown action ${d.action}` });
}

// ── Print plan ──────────────────────────────────────────────────────────────
console.error(`\nplan (${apply ? "APPLY" : "DRY-RUN"}):`);
console.error(`  ${"sku".padEnd(20)} ${"act".padEnd(4)} ${"cur".padEnd(8)} ${"tgt".padEnd(8)} ${"notes"}`);
for (const p of plan) {
  console.error(
    `  ${p.sku.padEnd(20)} ${p.action.padEnd(4)} ` +
      `${(p.current_cents ? "$" + (p.current_cents / 100).toFixed(2) : "—").padEnd(8)} ` +
      `${(p.target_cents ? "$" + (p.target_cents / 100).toFixed(2) : "—").padEnd(8)} ` +
      `${p.reason || ""}`
  );
}
const errs = plan.filter((p) => p.action === "ERR");
if (errs.length) {
  console.error(`\n${errs.length} errors — aborting before any Stripe call.`);
  process.exit(3);
}

const rs = plan.filter((p) => p.action === "R");
if (rs.length === 0) {
  console.error("\nno R (reprice) actions — nothing to send.");
  console.error(JSON.stringify({ status: "noop", plan }, null, 2));
  process.exit(0);
}

// ── Execute R actions one at a time, abort on first error ──────────────────
for (const p of rs) {
  if (!p.product_id || !p.old_price_id || !p.target_cents) continue;

  console.error(`\n→ ${p.sku}: creating new price at $${(p.target_cents / 100).toFixed(2)}…`);

  const found = findSku(p.sku);
  if (!found) {
    throw new Error(`internal: sku ${p.sku} vanished between plan and execute`);
  }

  // 1. Create new Price
  const isRecurring = (found.entry.mode || "").startsWith("subscription");
  const priceBody: Record<string, string> = {
    product: p.product_id,
    unit_amount: String(p.target_cents),
    currency,
  };
  if (isRecurring) {
    priceBody["recurring[interval]"] = "month";
  }
  const newPrice = await stripe<{ id: string }>("POST", "/prices", priceBody);
  p.new_price_id = newPrice.id;

  // 2. Create new Payment Link
  const linkBody: Record<string, string> = {
    "line_items[0][price]": newPrice.id,
    "line_items[0][quantity]": "1",
  };
  const newLink = await stripe<{ id: string; url: string }>("POST", "/payment_links", linkBody);
  p.new_payment_link_id = newLink.id;
  p.new_payment_link_url = newLink.url;

  // 3. Deactivate OLD Price (active=false). Old payment links remain — flag for manual deactivation.
  await stripe("POST", `/prices/${p.old_price_id}`, { active: "false" });

  // 4. Patch the catalog entry
  found.entry.amount_cents = p.target_cents;
  found.entry.price_id = newPrice.id;
  found.entry.payment_link_id = newLink.id;
  found.entry.payment_link_url = newLink.url;

  console.error(
    `  ✓ ${p.sku}: price ${p.old_price_id} → ${newPrice.id}; link ${newLink.url}`
  );
}

// ── Write catalog back ──────────────────────────────────────────────────────
if (apply) {
  writeFileSync(CONSUMER_FILE, JSON.stringify(consumer, null, 2) + "\n");
  if (b2b.length) writeFileSync(B2B_FILE, JSON.stringify(b2b, null, 2) + "\n");
  console.error(`\n✓ catalog files updated`);
} else {
  console.error(`\n[dry-run] catalog files NOT written.`);
}

// ── Follow-ups Anthony must do manually ────────────────────────────────────
console.error(`\nManual follow-ups (NOT done by this script):`);
for (const p of rs) {
  if (!p.old_payment_link_url) continue;
  console.error(`  • Deactivate old payment link in Stripe dashboard: ${p.old_payment_link_url}`);
  console.error(`    (Stripe API can't deactivate payment links — must be done in the dashboard.)`);
  console.error(`  • Update WordPress pages that reference ${p.old_payment_link_url}`);
  console.error(`    → new URL: ${p.new_payment_link_url}`);
}
console.error(`\nDone. Re-run the product-catalog builder to refresh .loki/state/product-catalog.json.`);
console.log(JSON.stringify({ status: apply ? "applied" : "dry_run", plan }, null, 2));
