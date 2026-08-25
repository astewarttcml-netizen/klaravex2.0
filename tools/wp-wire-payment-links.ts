#!/usr/bin/env bun
/**
 * Wire Stripe Payment Links into klaravex.com consumer pricing pages.
 *
 * Strategy: APPEND a clearly-marked Klaravex Checkout block to each target
 * page's content. The block is idempotent — re-running this tool replaces
 * an existing block (between BEGIN/END markers) rather than duplicating it.
 *
 * Idempotency markers: <!-- KLX-CHECKOUT-BEGIN sku=<sku> --> ... <!-- KLX-CHECKOUT-END -->
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const PROJECT_ROOT = resolve(import.meta.dir, "..");
const CONSUMER_MAP = resolve(PROJECT_ROOT, ".loki/stripe-products-consumer.json");
const EVIDENCE = resolve(PROJECT_ROOT, ".loki/evidence/wp-wire-consumer.json");

const WP_USER = "astewart.tcml@gmail.com";
const WP_PASS = readFileSync("/tmp/klaravex_session_keys/wp_app_pass", "utf8").trim();
const WP_BASE = "https://klaravex.com/wp-json/wp/v2";

const PAGE_TARGETS: { id: number; slug: string; skus: string[]; intro: string }[] = [
  { id: 25, slug: "personal/pricing", skus: ["essentials", "per-incident"], intro: "Ready to pay and start? Use the checkout links below — secure payment via Stripe." },
  { id: 142, slug: "personal/it-help", skus: ["per-incident"], intro: "Need help right now? Book a one-time 30-minute session via secure checkout." },
  { id: 143, slug: "personal/resume-job-search", skus: ["resume-basic", "resume-premium", "resume-executive"], intro: "Pick a resume tier and pay securely via Stripe." },
  { id: 167, slug: "personal/job-hunt-tech-kit", skus: ["tech-kit"], intro: "Get started — secure checkout." },
  { id: 169, slug: "personal/solo-business-launch-kit", skus: ["solo-launch"], intro: "Get started — secure checkout." },
  { id: 177, slug: "personal/ai-skills-coaching", skus: ["ai-coaching"], intro: "Book a single coaching session — secure checkout." },
  { id: 171, slug: "personal/identity-data-cleanup", skus: ["identity-privacy"], intro: "Lock down your identity — secure checkout." },
  { id: 175, slug: "personal/family-senior-tech", skus: ["family-senior"], intro: "Subscribe to family & senior tech protection — secure checkout." },
  { id: 173, slug: "personal/privacy", skus: ["identity-privacy"], intro: "Privacy hardening service — secure checkout." },
];

type Mapping = { sku: string; name: string; amount_cents: number; mode: string; payment_link_url: string };

function fmtPrice(cents: number, mode: string): string {
  const dollars = (cents / 100).toFixed(cents % 100 === 0 ? 0 : 2);
  return mode === "subscription" ? `$${dollars}/mo` : `$${dollars}`;
}

function buildBlock(intro: string, skus: string[], byMap: Map<string, Mapping>): string {
  const buttons = skus
    .map((sku) => {
      const m = byMap.get(sku);
      if (!m) return "";
      const price = fmtPrice(m.amount_cents, m.mode);
      return `<p><a class="wp-block-button__link wp-element-button" href="${m.payment_link_url}" target="_blank" rel="noopener" style="background-color:#0f3a5a;color:#ffffff;padding:14px 28px;text-decoration:none;border-radius:6px;display:inline-block;font-weight:600;margin:8px 8px 8px 0;">${m.name} — ${price}</a></p>`;
    })
    .filter(Boolean)
    .join("\n");

  return [
    `<!-- KLX-CHECKOUT-BEGIN sku=${skus.join(",")} -->`,
    `<div class="klx-checkout-block" style="margin:32px 0;padding:24px;border:1px solid #e5e7eb;border-radius:10px;background:#f9fafb;">`,
    `<h3 style="margin-top:0;">Pay & Start Now</h3>`,
    `<p>${intro}</p>`,
    buttons,
    `<p style="font-size:13px;color:#6b7280;margin-bottom:0;">Secure checkout via Stripe. Cancel subscriptions anytime from your account portal.</p>`,
    `</div>`,
    `<!-- KLX-CHECKOUT-END -->`,
  ].join("\n");
}

async function getPage(id: number): Promise<any> {
  const res = await fetch(`${WP_BASE}/pages/${id}?context=edit`, {
    headers: { Authorization: `Basic ${btoa(`${WP_USER}:${WP_PASS}`)}` },
  });
  if (!res.ok) throw new Error(`GET page ${id} → ${res.status}`);
  return res.json();
}

async function patchPage(id: number, content: string): Promise<any> {
  const res = await fetch(`${WP_BASE}/pages/${id}`, {
    method: "POST",
    headers: { Authorization: `Basic ${btoa(`${WP_USER}:${WP_PASS}`)}`, "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`PATCH page ${id} → ${res.status} ${t.slice(0, 300)}`);
  }
  return res.json();
}

function upsertBlock(existing: string, newBlock: string): string {
  const begin = /<!-- KLX-CHECKOUT-BEGIN[^>]*-->/;
  const end = /<!-- KLX-CHECKOUT-END -->/;
  if (begin.test(existing) && end.test(existing)) {
    return existing.replace(/<!-- KLX-CHECKOUT-BEGIN[\s\S]*?<!-- KLX-CHECKOUT-END -->/, newBlock);
  }
  return existing.trimEnd() + "\n\n" + newBlock + "\n";
}

async function main() {
  const mappings: Mapping[] = JSON.parse(readFileSync(CONSUMER_MAP, "utf8"));
  const byMap = new Map(mappings.map((m) => [m.sku, m]));

  const results: any[] = [];
  for (const t of PAGE_TARGETS) {
    try {
      const page = await getPage(t.id);
      const raw = page.content?.raw ?? page.content?.rendered ?? "";
      const block = buildBlock(t.intro, t.skus, byMap);
      const next = upsertBlock(raw, block);
      const action = raw === next ? "noop" : raw.includes("KLX-CHECKOUT-BEGIN") ? "replaced" : "appended";
      if (action !== "noop") {
        await patchPage(t.id, next);
      }
      const verifyRes = await fetch(`https://klaravex.com/?p=${t.id}`);
      const verifyHtml = await verifyRes.text();
      const hasLink = t.skus.every((sku) => {
        const m = byMap.get(sku);
        return m ? verifyHtml.includes(m.payment_link_url) : false;
      });
      results.push({ id: t.id, slug: t.slug, action, contains_links: hasLink });
      console.log(`${action.padEnd(10)} id=${t.id} ${t.slug} ${hasLink ? "✓" : "✗"}`);
    } catch (e: any) {
      results.push({ id: t.id, slug: t.slug, error: e.message });
      console.error(`! id=${t.id} ${t.slug}: ${e.message}`);
    }
  }

  mkdirSync(resolve(PROJECT_ROOT, ".loki/evidence"), { recursive: true });
  writeFileSync(EVIDENCE, JSON.stringify({ at: new Date().toISOString(), results }, null, 2));
  const ok = results.filter((r) => !r.error).length;
  console.log(`\nDone. ok=${ok} fail=${results.length - ok}`);
}

main();
