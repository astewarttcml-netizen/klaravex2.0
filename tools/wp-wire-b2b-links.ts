#!/usr/bin/env bun
/**
 * Wire B2B Stripe Payment Links into klaravex.com business service pages.
 * Same KLX-CHECKOUT-BEGIN/END idempotent marker pattern as the consumer tool.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const PROJECT_ROOT = resolve(import.meta.dir, "..");
const B2B_MAP = resolve(PROJECT_ROOT, ".loki/stripe-products-b2b.json");
const EVIDENCE = resolve(PROJECT_ROOT, ".loki/evidence/wp-wire-b2b.json");

const WP_USER = "astewart.tcml@gmail.com";
const WP_PASS = readFileSync("/tmp/klaravex_session_keys/wp_app_pass", "utf8").trim();
const WP_BASE = "https://klaravex.com/wp-json/wp/v2";

const PAGE_TARGETS: { id: number; slug: string; skus: string[]; intro: string }[] = [
  { id: 18, slug: "business/services/foundation", skus: ["foundation"], intro: "Subscribe to Foundation now — quantity = number of seats. Secure checkout via Stripe." },
  { id: 17, slug: "business/services/assurance", skus: ["assurance"], intro: "Subscribe to Assurance now — quantity = number of seats. Secure checkout via Stripe." },
  { id: 16, slug: "business/services/directive", skus: ["directive"], intro: "Subscribe to Directive now — quantity = number of seats. Secure checkout via Stripe." },
  { id: 106, slug: "managed-it-support-plans", skus: ["foundation", "assurance", "directive"], intro: "Pick a tier and subscribe. Quantity = seat count. Secure checkout via Stripe." },
  { id: 180, slug: "business/services/cyber-insurance-readiness", skus: ["cir-small", "cir-medium", "cir-large"], intro: "Pick your company-size bracket to purchase the Cyber-Insurance Readiness Assessment." },
  { id: 109, slug: "business/services/it-security-audit", skus: ["it-audit"], intro: "Purchase a structured IT Security Audit. Secure checkout via Stripe." },
  { id: 86, slug: "business/services/microsoft-365", skus: ["m365-setup", "m365-migration"], intro: "M365 setup is fixed-fee. Migration is per-user (set quantity at checkout)." },
  { id: 85, slug: "business/services/microsoft-azure", skus: ["azure-review", "azure-project"], intro: "Azure architecture review is fixed-fee. Project work is starting price; final per SOW." },
  { id: 88, slug: "business/services/intune-endpoint-management", skus: ["intune-rollout"], intro: "Intune endpoint rollout — fixed-fee build." },
  { id: 93, slug: "business/services/windows-server-infrastructure", skus: ["windows-server-project"], intro: "Windows Server / Active Directory project — secure checkout." },
  { id: 94, slug: "business/services/backup-disaster-recovery", skus: ["backup-dr-setup"], intro: "Backup + DR build — secure checkout." },
  { id: 95, slug: "business/services/powershell-automation", skus: ["powershell-project"], intro: "PowerShell automation project — secure checkout." },
  { id: 96, slug: "business/services/remote-it-support", skus: ["remote-block-10hr", "remote-block-25hr"], intro: "Buy a prepaid block of remote support hours. Pick a bundle below." },
  { id: 97, slug: "business/services/network-monitoring", skus: ["monitoring-setup"], intro: "Monitoring deployment — secure checkout." },
  { id: 108, slug: "business/services/firewall-network-security", skus: ["firewall-deploy"], intro: "Firewall deployment — secure checkout." },
  { id: 103, slug: "business/services/it-strategy-vcio", skus: ["vcio-standalone"], intro: "vCIO Standalone — fractional CIO advisory, flat monthly." },
  { id: 105, slug: "business/services/it-procurement", skus: ["procurement-flat"], intro: "IT Procurement Engagement — fixed-fee." },
  { id: 104, slug: "business/services/ai-automation", skus: ["ai-automation-project"], intro: "AI Automation Consulting Project — starting price; final per SOW." },
  { id: 128, slug: "business/services/ai-workflow-automation", skus: ["ai-automation-project"], intro: "AI Workflow Automation — same secure checkout as AI Automation Consulting." },
];

type Mapping = { sku: string; name: string; amount_cents: number; mode: string; payment_link_url: string; per_unit?: boolean };

function fmtPrice(m: Mapping): string {
  const dollars = (m.amount_cents / 100).toFixed(m.amount_cents % 100 === 0 ? 0 : 2);
  if (m.mode === "subscription") return m.per_unit ? `$${dollars}/user/mo` : `$${dollars}/mo`;
  return m.per_unit ? `$${dollars}/user` : `$${dollars}`;
}

function buildBlock(intro: string, skus: string[], byMap: Map<string, Mapping>): string {
  const buttons = skus
    .map((sku) => {
      const m = byMap.get(sku);
      if (!m) return "";
      return `<p><a class="wp-block-button__link wp-element-button" href="${m.payment_link_url}" target="_blank" rel="noopener" style="background-color:#0f3a5a;color:#ffffff;padding:14px 28px;text-decoration:none;border-radius:6px;display:inline-block;font-weight:600;margin:8px 8px 8px 0;">${m.name} — ${fmtPrice(m)}</a></p>`;
    })
    .filter(Boolean)
    .join("\n");

  return [
    `<!-- KLX-CHECKOUT-BEGIN sku=${skus.join(",")} -->`,
    `<div class="klx-checkout-block" style="margin:32px 0;padding:24px;border:1px solid #e5e7eb;border-radius:10px;background:#f9fafb;">`,
    `<h3 style="margin-top:0;">Buy or Subscribe</h3>`,
    `<p>${intro}</p>`,
    buttons,
    `<p style="font-size:13px;color:#6b7280;margin-bottom:0;">Secure checkout via Stripe. Need help scoping or a contract first? <a href="/business/contact/">Talk to us →</a></p>`,
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
  if (/<!-- KLX-CHECKOUT-BEGIN[^>]*-->/.test(existing) && /<!-- KLX-CHECKOUT-END -->/.test(existing)) {
    return existing.replace(/<!-- KLX-CHECKOUT-BEGIN[\s\S]*?<!-- KLX-CHECKOUT-END -->/, newBlock);
  }
  return existing.trimEnd() + "\n\n" + newBlock + "\n";
}

async function main() {
  const mappings: Mapping[] = JSON.parse(readFileSync(B2B_MAP, "utf8"));
  const byMap = new Map(mappings.map((m) => [m.sku, m]));

  const results: any[] = [];
  for (const t of PAGE_TARGETS) {
    try {
      const page = await getPage(t.id);
      const raw = page.content?.raw ?? page.content?.rendered ?? "";
      const block = buildBlock(t.intro, t.skus, byMap);
      const next = upsertBlock(raw, block);
      const action = raw === next ? "noop" : raw.includes("KLX-CHECKOUT-BEGIN") ? "replaced" : "appended";
      if (action !== "noop") await patchPage(t.id, next);
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
  const ok = results.filter((r) => !r.error && r.contains_links).length;
  console.log(`\nDone. verified=${ok} total=${results.length}`);
}

main();
