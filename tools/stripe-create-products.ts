#!/usr/bin/env bun
/**
 * Create all Klaravex Stripe products + prices + payment links.
 * Idempotent: searches existing products by metadata.sku before creating.
 * Writes mappings to .loki/stripe-products-{consumer,b2b}.json incrementally.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

const STRIPE_KEY = readFileSync("/tmp/klaravex_session_keys/stripe_key", "utf8").trim();
if (!STRIPE_KEY.startsWith("sk_")) throw new Error("Stripe key invalid");

const STRIPE_BASE = "https://api.stripe.com/v1";
const PROJECT_ROOT = resolve(import.meta.dir, "..");
const CONSUMER_OUT = resolve(PROJECT_ROOT, ".loki/stripe-products-consumer.json");
const B2B_OUT = resolve(PROJECT_ROOT, ".loki/stripe-products-b2b.json");

type Mode = "subscription" | "one_time";
type Product = {
  sku: string;
  name: string;
  description: string;
  amount_cents: number;
  mode: Mode;
  per_unit?: boolean;
  segment: "consumer" | "b2b";
};

const PRODUCTS: Product[] = [
  // Consumer subscriptions
  { sku: "essentials", name: "Klaravex Essentials", description: "Unlimited Loki AI support + unlimited remote expert sessions. Cancel anytime.", amount_cents: 2400, mode: "subscription", segment: "consumer" },
  { sku: "family-senior", name: "Family & Senior Tech", description: "Proactive protection + 24/7 'is this a scam?' line for older parents.", amount_cents: 1900, mode: "subscription", segment: "consumer" },
  { sku: "home-membership", name: "Home Membership", description: "Essentials + family device coverage (up to 6 devices) + priority routing.", amount_cents: 3900, mode: "subscription", segment: "consumer" },
  // Consumer one-time
  { sku: "per-incident", name: "Per-Incident IT Session", description: "One 30-minute remote session with a real expert.", amount_cents: 7900, mode: "one_time", segment: "consumer" },
  { sku: "resume-basic", name: "Resume Writing (Basic)", description: "60-day guarantee. AI volume + human strategy. Basic tier.", amount_cents: 19900, mode: "one_time", segment: "consumer" },
  { sku: "resume-premium", name: "Resume Writing (Premium)", description: "60-day guarantee. AI volume + human strategy. Premium tier.", amount_cents: 49900, mode: "one_time", segment: "consumer" },
  { sku: "resume-executive", name: "Resume Writing (Executive)", description: "60-day guarantee. Executive resume + LinkedIn + cover letters.", amount_cents: 79900, mode: "one_time", segment: "consumer" },
  { sku: "tech-kit", name: "Job-Hunt Tech Kit", description: "Domain, pro email, portfolio site, LinkedIn, camera setup.", amount_cents: 29900, mode: "one_time", segment: "consumer" },
  { sku: "solo-launch", name: "Solo-Business Launch Kit", description: "Online + secure + invoicing-ready in a weekend.", amount_cents: 39900, mode: "one_time", segment: "consumer" },
  { sku: "ai-coaching", name: "AI Skills Coaching", description: "Hands-on AI session for job search / writing / admin.", amount_cents: 7500, mode: "one_time", segment: "consumer" },
  { sku: "identity-privacy", name: "Identity & Privacy Hardening", description: "Post-breach lockdown + data broker removal.", amount_cents: 17900, mode: "one_time", segment: "consumer" },

  // B2B subscriptions (per_unit = user count)
  { sku: "foundation", name: "Foundation", description: "Loki AI helpdesk 24/7 + M365/GWS/AWS user mgmt + UniFi + Intune + MFA baseline + monthly ops report.", amount_cents: 10000, mode: "subscription", per_unit: true, segment: "b2b" },
  { sku: "assurance", name: "Assurance", description: "Foundation + proactive monitoring + managed EDR + Huntress MDR + SAT + vuln mgmt + IR support + quarterly posture review + immutable backup.", amount_cents: 16500, mode: "subscription", per_unit: true, segment: "b2b" },
  { sku: "directive", name: "Directive", description: "Assurance + vCISO + full MDR + readiness program (HIPAA/SOC2/ISO27001) + policy dev + IR planning + board reporting.", amount_cents: 29500, mode: "subscription", per_unit: true, segment: "b2b" },
  { sku: "co-managed-foundation", name: "Co-Managed Foundation", description: "Foundation tier, 25% discount for clients with internal IT.", amount_cents: 7500, mode: "subscription", per_unit: true, segment: "b2b" },
  { sku: "co-managed-assurance", name: "Co-Managed Assurance", description: "Assurance tier, 25% discount for clients with internal IT.", amount_cents: 12400, mode: "subscription", per_unit: true, segment: "b2b" },
  { sku: "co-managed-directive", name: "Co-Managed Directive", description: "Directive tier, 25% discount for clients with internal IT.", amount_cents: 22100, mode: "subscription", per_unit: true, segment: "b2b" },
  { sku: "sat", name: "Security Awareness Training", description: "Monthly micro-training + phishing simulation + insurer-ready reports.", amount_cents: 400, mode: "subscription", per_unit: true, segment: "b2b" },
  { sku: "email-security", name: "Email Security Add-on", description: "Beyond M365/GWS default — anti-phishing layer.", amount_cents: 500, mode: "subscription", per_unit: true, segment: "b2b" },
  { sku: "managed-edr", name: "Managed EDR (Standalone)", description: "Endpoint detection & response layer only, no MDR.", amount_cents: 800, mode: "subscription", per_unit: true, segment: "b2b" },
  { sku: "loki-concierge", name: "Loki Chat Concierge", description: "Dedicated trained Loki configuration for the client's stack.", amount_cents: 2500, mode: "subscription", per_unit: true, segment: "b2b" },

  // B2B one-time
  { sku: "cir-small", name: "Cyber-Insurance Readiness (1–25 employees)", description: "Gap report against insurer questionnaire + remediation plan. Small org.", amount_cents: 150000, mode: "one_time", segment: "b2b" },
  { sku: "cir-medium", name: "Cyber-Insurance Readiness (26–75 employees)", description: "Gap report against insurer questionnaire + remediation plan. Mid org.", amount_cents: 250000, mode: "one_time", segment: "b2b" },
  { sku: "cir-large", name: "Cyber-Insurance Readiness (76–150 employees)", description: "Gap report against insurer questionnaire + remediation plan. Large org.", amount_cents: 350000, mode: "one_time", segment: "b2b" },
  { sku: "it-audit", name: "IT Security Audit", description: "Structured infrastructure + posture review with prioritized findings.", amount_cents: 350000, mode: "one_time", segment: "b2b" },
  { sku: "hipaa-gap", name: "HIPAA Gap Analysis", description: "Risk analysis aligned to Security Rule + remediation roadmap.", amount_cents: 500000, mode: "one_time", segment: "b2b" },
  { sku: "m365-migration", name: "M365 Migration", description: "Zero-downtime cutover from on-prem Exchange or GSuite. Per user.", amount_cents: 20000, mode: "one_time", per_unit: true, segment: "b2b" },
  { sku: "m365-setup", name: "M365 Setup (Standalone)", description: "New M365 tenant build + baseline hardening.", amount_cents: 150000, mode: "one_time", segment: "b2b" },
  { sku: "azure-review", name: "Azure Architecture Review", description: "Cost optimization + security posture review.", amount_cents: 350000, mode: "one_time", segment: "b2b" },
  { sku: "azure-project", name: "Azure Project (Scoped)", description: "Scoped Azure build or migration engagement.", amount_cents: 500000, mode: "one_time", segment: "b2b" },
  { sku: "intune-rollout", name: "Intune Rollout", description: "Endpoint management policy build + device enrollment.", amount_cents: 250000, mode: "one_time", segment: "b2b" },
  { sku: "windows-server-project", name: "Windows Server / AD Project", description: "On-prem Windows Server or Active Directory build/upgrade.", amount_cents: 350000, mode: "one_time", segment: "b2b" },
  { sku: "backup-dr-setup", name: "Backup + DR Build", description: "Immutable backup + disaster recovery runbook.", amount_cents: 250000, mode: "one_time", segment: "b2b" },
  { sku: "powershell-project", name: "PowerShell Automation Project", description: "Custom scripts for repeated ops or reporting.", amount_cents: 150000, mode: "one_time", segment: "b2b" },
  { sku: "remote-block-10hr", name: "Block-Hour Remote Support (10 hrs)", description: "Prepaid 10-hour block of remote support time.", amount_cents: 125000, mode: "one_time", segment: "b2b" },
  { sku: "remote-block-25hr", name: "Block-Hour Remote Support (25 hrs)", description: "Prepaid 25-hour block of remote support time.", amount_cents: 275000, mode: "one_time", segment: "b2b" },
  { sku: "monitoring-setup", name: "Monitoring Deployment", description: "RMM agents + alert routing + dashboards.", amount_cents: 150000, mode: "one_time", segment: "b2b" },
  { sku: "firewall-deploy", name: "Firewall Deployment", description: "UniFi or equivalent firewall + segmentation policy.", amount_cents: 250000, mode: "one_time", segment: "b2b" },
  { sku: "procurement-flat", name: "IT Procurement Engagement", description: "Hardware/software procurement coordination.", amount_cents: 75000, mode: "one_time", segment: "b2b" },
  { sku: "ai-automation-project", name: "AI Automation Consulting Project", description: "Scoped AI-driven workflow automation engagement.", amount_cents: 350000, mode: "one_time", segment: "b2b" },
  { sku: "onboarding-fee", name: "Managed Plan Onboarding Fee", description: "Initial onboarding for new managed clients (variable).", amount_cents: 150000, mode: "one_time", segment: "b2b" },
  { sku: "attestation-prep", name: "Compliance Attestation Prep", description: "Documentation + control mapping prep for attestation engagement.", amount_cents: 500000, mode: "one_time", segment: "b2b" },
  { sku: "office-it-relocation", name: "Office IT Relocation", description: "Coordinated IT move including network + endpoints.", amount_cents: 250000, mode: "one_time", segment: "b2b" },
  { sku: "pentest", name: "Penetration Test (Scoped)", description: "Authorized testing scoped by environment.", amount_cents: 750000, mode: "one_time", segment: "b2b" },
  { sku: "iso27001-readiness", name: "ISO 27001 Readiness Program", description: "ISMS scope + documentation + controls + internal audit support.", amount_cents: 1500000, mode: "one_time", segment: "b2b" },

  // B2B flat-fee recurring
  { sku: "vcio-standalone", name: "vCIO Standalone", description: "Fractional CIO advisory, flat monthly.", amount_cents: 150000, mode: "subscription", segment: "b2b" },
  { sku: "vciso-standalone", name: "vCISO Standalone", description: "Fractional CISO advisory + risk program leadership, flat monthly.", amount_cents: 250000, mode: "subscription", segment: "b2b" },
  { sku: "ir-retainer", name: "Incident Response Retainer", description: "Reserved IR hours + 24/7 declared-incident access.", amount_cents: 75000, mode: "subscription", segment: "b2b" },
];

const headers = { Authorization: `Basic ${btoa(STRIPE_KEY + ":")}` };

async function postForm(path: string, body: Record<string, string>): Promise<any> {
  const form = new URLSearchParams(body);
  const res = await fetch(`${STRIPE_BASE}${path}`, { method: "POST", headers: { ...headers, "Content-Type": "application/x-www-form-urlencoded" }, body: form });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Stripe ${path} ${res.status}: ${text.slice(0, 400)}`);
  }
  return res.json();
}

async function getJson(path: string): Promise<any> {
  const res = await fetch(`${STRIPE_BASE}${path}`, { headers });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Stripe GET ${path} ${res.status}: ${text.slice(0, 400)}`);
  }
  return res.json();
}

async function findExistingBySku(sku: string): Promise<{ product?: any; price?: any; link?: any }> {
  // Search products by metadata.sku — uses Stripe Search API
  const q = `metadata['sku']:'${sku}'`;
  const products = await getJson(`/products/search?query=${encodeURIComponent(q)}&limit=1`);
  const product = products.data?.[0];
  if (!product) return {};
  const prices = await getJson(`/prices?product=${product.id}&active=true&limit=10`);
  const price = prices.data?.[0];
  let link;
  if (price) {
    const links = await getJson(`/payment_links?limit=100&active=true`);
    link = links.data?.find((l: any) => l.line_items?.data?.[0]?.price === price.id) || links.data?.find((l: any) => l.metadata?.sku === sku);
  }
  return { product, price, link };
}

function loadJson(p: string): any[] {
  if (!existsSync(p)) return [];
  try { return JSON.parse(readFileSync(p, "utf8")); } catch { return []; }
}

function saveJson(p: string, data: any[]) {
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, JSON.stringify(data, null, 2));
}

function upsertMapping(p: string, entry: any) {
  const list = loadJson(p);
  const idx = list.findIndex((x) => x.sku === entry.sku);
  if (idx >= 0) list[idx] = entry;
  else list.push(entry);
  saveJson(p, list);
}

async function ensureProduct(p: Product) {
  const existing = await findExistingBySku(p.sku);
  let product = existing.product;
  let price = existing.price;
  let link = existing.link;

  if (!product) {
    product = await postForm("/products", {
      name: p.name,
      description: p.description,
      "metadata[sku]": p.sku,
      "metadata[segment]": p.segment,
    });
    console.log(`+ product ${p.sku} → ${product.id}`);
  } else {
    console.log(`= product ${p.sku} → ${product.id} (exists)`);
  }

  if (!price) {
    const body: Record<string, string> = {
      product: product.id,
      unit_amount: String(p.amount_cents),
      currency: "usd",
      "metadata[sku]": p.sku,
    };
    if (p.mode === "subscription") body["recurring[interval]"] = "month";
    price = await postForm("/prices", body);
    console.log(`+ price   ${p.sku} → ${price.id}`);
  } else {
    console.log(`= price   ${p.sku} → ${price.id} (exists)`);
  }

  if (!link) {
    const body: Record<string, string> = {
      "line_items[0][price]": price.id,
      "line_items[0][quantity]": "1",
      "metadata[sku]": p.sku,
    };
    if (p.per_unit) {
      body["line_items[0][adjustable_quantity][enabled]"] = "true";
      body["line_items[0][adjustable_quantity][minimum]"] = "1";
      body["line_items[0][adjustable_quantity][maximum]"] = "500";
    }
    link = await postForm("/payment_links", body);
    console.log(`+ link    ${p.sku} → ${link.url}`);
  } else {
    console.log(`= link    ${p.sku} → ${link.url} (exists)`);
  }

  const entry = {
    sku: p.sku,
    name: p.name,
    segment: p.segment,
    mode: p.mode,
    per_unit: !!p.per_unit,
    amount_cents: p.amount_cents,
    product_id: product.id,
    price_id: price.id,
    payment_link_id: link.id,
    payment_link_url: link.url,
  };

  upsertMapping(p.segment === "consumer" ? CONSUMER_OUT : B2B_OUT, entry);
  return entry;
}

async function main() {
  const onlySegment = process.argv[2] as "consumer" | "b2b" | undefined;
  const work = onlySegment ? PRODUCTS.filter((p) => p.segment === onlySegment) : PRODUCTS;
  console.log(`Creating/verifying ${work.length} products${onlySegment ? ` (segment=${onlySegment})` : ""}…`);
  let ok = 0, fail = 0;
  for (const p of work) {
    try {
      await ensureProduct(p);
      ok++;
    } catch (e: any) {
      console.error(`! ${p.sku} failed: ${e.message}`);
      fail++;
    }
  }
  console.log(`\nDone. ok=${ok} fail=${fail}`);
  if (fail > 0) process.exit(1);
}

main();
