#!/usr/bin/env bun
/**
 * Inject JSON-LD schema (Organization, Service, BreadcrumbList) into Klaravex pages.
 * Idempotent via KLX-SCHEMA-BEGIN/END markers.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const PROJECT_ROOT = resolve(import.meta.dir, "..");
const EVIDENCE = resolve(PROJECT_ROOT, ".loki/evidence/wp-inject-schema.json");

const WP_USER = "astewart.tcml@gmail.com";
const WP_PASS = readFileSync("/tmp/klaravex_session_keys/wp_app_pass", "utf8").trim();
const WP_BASE = "https://klaravex.com/wp-json/wp/v2";

const ORG = {
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": "https://klaravex.com/#organization",
  name: "Klaravex",
  legalName: "Klaravex LLC",
  url: "https://klaravex.com",
  logo: "https://klaravex.com/wp-content/uploads/2026/05/klaravex-logo.png",
  email: "hello@klaravex.com",
  description: "AI-powered managed security, IT, and readiness advisory for US SMBs.",
  foundingDate: "2026-05",
  founder: { "@type": "Person", name: "Anthony Stewart" },
  address: { "@type": "PostalAddress", addressCountry: "US", addressRegion: "WY" },
  sameAs: [
    "https://www.linkedin.com/company/klaravex",
    "https://x.com/klaravex",
  ],
};

type Target = { id: number; type: "homepage" | "service" | "generic"; service?: { name: string; sku: string; serviceType: string; areaServed: string[] } };

const TARGETS: Target[] = [
  { id: 10, type: "homepage" },
  { id: 18, type: "service", service: { name: "Foundation Managed IT & Security", sku: "foundation", serviceType: "Managed Security Service Provider", areaServed: ["US"] } },
  { id: 17, type: "service", service: { name: "Assurance Managed Security", sku: "assurance", serviceType: "Managed Detection and Response", areaServed: ["US"] } },
  { id: 16, type: "service", service: { name: "Directive vCISO + Readiness", sku: "directive", serviceType: "Virtual CISO and Compliance Readiness", areaServed: ["US"] } },
  { id: 180, type: "service", service: { name: "Cyber-Insurance Readiness Assessment", sku: "cir-medium", serviceType: "Cybersecurity Assessment", areaServed: ["US"] } },
  { id: 109, type: "service", service: { name: "IT Security Audit", sku: "it-audit", serviceType: "Cybersecurity Audit", areaServed: ["US"] } },
  { id: 86, type: "service", service: { name: "Microsoft 365 Setup & Migration", sku: "m365-setup", serviceType: "Cloud Migration Service", areaServed: ["US"] } },
  { id: 85, type: "service", service: { name: "Microsoft Azure Architecture & Projects", sku: "azure-review", serviceType: "Cloud Architecture Service", areaServed: ["US"] } },
  { id: 88, type: "service", service: { name: "Microsoft Intune Endpoint Management", sku: "intune-rollout", serviceType: "Endpoint Management Service", areaServed: ["US"] } },
  { id: 93, type: "service", service: { name: "Windows Server & Active Directory Projects", sku: "windows-server-project", serviceType: "Infrastructure Service", areaServed: ["US"] } },
  { id: 94, type: "service", service: { name: "Backup & Disaster Recovery", sku: "backup-dr-setup", serviceType: "Backup and Disaster Recovery Service", areaServed: ["US"] } },
  { id: 95, type: "service", service: { name: "PowerShell Automation", sku: "powershell-project", serviceType: "IT Automation Service", areaServed: ["US"] } },
  { id: 96, type: "service", service: { name: "Remote IT Support Block Hours", sku: "remote-block-10hr", serviceType: "Remote IT Support", areaServed: ["US"] } },
  { id: 97, type: "service", service: { name: "Network Monitoring Deployment", sku: "monitoring-setup", serviceType: "Network Monitoring Service", areaServed: ["US"] } },
  { id: 108, type: "service", service: { name: "Firewall & Network Security", sku: "firewall-deploy", serviceType: "Network Security Service", areaServed: ["US"] } },
  { id: 103, type: "service", service: { name: "vCIO Strategy & Advisory", sku: "vcio-standalone", serviceType: "Virtual CIO Advisory", areaServed: ["US"] } },
  { id: 105, type: "service", service: { name: "IT Procurement", sku: "procurement-flat", serviceType: "IT Procurement Service", areaServed: ["US"] } },
  { id: 104, type: "service", service: { name: "AI Automation Consulting", sku: "ai-automation-project", serviceType: "AI Consulting", areaServed: ["US"] } },
  { id: 106, type: "service", service: { name: "Managed IT Support Plans", sku: "foundation", serviceType: "Managed IT Service", areaServed: ["US"] } },
];

function serviceSchema(svc: NonNullable<Target["service"]>) {
  return {
    "@context": "https://schema.org",
    "@type": "Service",
    name: svc.name,
    provider: { "@id": "https://klaravex.com/#organization" },
    serviceType: svc.serviceType,
    areaServed: svc.areaServed.map((c) => ({ "@type": "Country", name: c })),
    additionalProperty: [{ "@type": "PropertyValue", name: "sku", value: svc.sku }],
  };
}

function block(payload: object[]): string {
  return [
    `<!-- KLX-SCHEMA-BEGIN -->`,
    ...payload.map((p) => `<script type="application/ld+json">${JSON.stringify(p)}</script>`),
    `<!-- KLX-SCHEMA-END -->`,
  ].join("\n");
}

function upsert(existing: string, b: string): string {
  if (/<!-- KLX-SCHEMA-BEGIN -->/.test(existing) && /<!-- KLX-SCHEMA-END -->/.test(existing)) {
    return existing.replace(/<!-- KLX-SCHEMA-BEGIN -->[\s\S]*?<!-- KLX-SCHEMA-END -->/, b);
  }
  return existing.trimEnd() + "\n\n" + b + "\n";
}

async function getPage(id: number): Promise<any> {
  const res = await fetch(`${WP_BASE}/pages/${id}?context=edit`, { headers: { Authorization: `Basic ${btoa(`${WP_USER}:${WP_PASS}`)}` } });
  if (!res.ok) throw new Error(`GET page ${id} → ${res.status}`);
  return res.json();
}

async function patchPage(id: number, content: string): Promise<any> {
  const res = await fetch(`${WP_BASE}/pages/${id}`, {
    method: "POST",
    headers: { Authorization: `Basic ${btoa(`${WP_USER}:${WP_PASS}`)}`, "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`PATCH page ${id} → ${res.status} ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

async function main() {
  const results: any[] = [];
  for (const t of TARGETS) {
    try {
      const page = await getPage(t.id);
      const raw = page.content?.raw ?? page.content?.rendered ?? "";
      let payload: object[];
      if (t.type === "homepage") payload = [ORG];
      else if (t.type === "service" && t.service) payload = [serviceSchema(t.service)];
      else payload = [ORG];
      const b = block(payload);
      const next = upsert(raw, b);
      const action = raw === next ? "noop" : raw.includes("KLX-SCHEMA-BEGIN") ? "replaced" : "appended";
      if (action !== "noop") await patchPage(t.id, next);
      results.push({ id: t.id, type: t.type, action });
      console.log(`${action.padEnd(10)} id=${t.id} ${t.type}`);
    } catch (e: any) {
      results.push({ id: t.id, error: e.message });
      console.error(`! id=${t.id}: ${e.message}`);
    }
  }
  mkdirSync(resolve(PROJECT_ROOT, ".loki/evidence"), { recursive: true });
  writeFileSync(EVIDENCE, JSON.stringify({ at: new Date().toISOString(), results }, null, 2));
  console.log(`\nDone. ok=${results.filter((r) => !r.error).length} fail=${results.filter((r) => r.error).length}`);
}

main();
