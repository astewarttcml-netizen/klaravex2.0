import { afterAll, beforeAll, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import index from "./index.html";
import privacy from "./privacy.html";
import terms from "./terms.html";
import legal from "./legal.html";
import industriesHealthcare from "./industries-healthcare.html";
import industriesLegalFinancial from "./industries-legal-financial.html";
import industriesM365Smb from "./industries-m365-smb.html";
import about from "./about.html";
import services from "./services.html";
import contact from "./contact.html";
import faq from "./faq.html";
import notFound from "./not-found.html";
import { SECURITY_HEADERS, SECURITY_TXT } from "./server";

let server: ReturnType<typeof Bun.serve>;
let base: string;

const frontendSrc = readFileSync(
  join(import.meta.dir, "frontend.tsx"),
  "utf8",
);
const htmlSrc = readFileSync(join(import.meta.dir, "index.html"), "utf8");
const privacySrc = readFileSync(join(import.meta.dir, "privacy.html"), "utf8");
const termsSrc = readFileSync(join(import.meta.dir, "terms.html"), "utf8");
const legalSrc = readFileSync(join(import.meta.dir, "legal.html"), "utf8");
const industriesHealthcareSrc = readFileSync(
  join(import.meta.dir, "industries-healthcare.html"),
  "utf8",
);
const industriesLegalFinancialSrc = readFileSync(
  join(import.meta.dir, "industries-legal-financial.html"),
  "utf8",
);
const industriesM365SmbSrc = readFileSync(
  join(import.meta.dir, "industries-m365-smb.html"),
  "utf8",
);
const aboutSrc = readFileSync(join(import.meta.dir, "about.html"), "utf8");
const servicesSrc = readFileSync(join(import.meta.dir, "services.html"), "utf8");
const contactSrc = readFileSync(join(import.meta.dir, "contact.html"), "utf8");
const faqSrc = readFileSync(join(import.meta.dir, "faq.html"), "utf8");
const notFoundSrc = readFileSync(
  join(import.meta.dir, "not-found.html"),
  "utf8",
);

const ROBOTS_TXT = `User-agent: *\nAllow: /\n\nSitemap: https://klaravex.com/sitemap.xml\n`;
const SITEMAP_XML = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://klaravex.com/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>https://klaravex.com/about</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://klaravex.com/services</loc><changefreq>monthly</changefreq><priority>0.9</priority></url>
  <url><loc>https://klaravex.com/contact</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://klaravex.com/faq</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>
  <url><loc>https://klaravex.com/industries/healthcare</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://klaravex.com/industries/legal-financial</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://klaravex.com/industries/m365-smb</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://klaravex.com/privacy</loc><changefreq>monthly</changefreq><priority>0.4</priority></url>
  <url><loc>https://klaravex.com/terms</loc><changefreq>monthly</changefreq><priority>0.4</priority></url>
  <url><loc>https://klaravex.com/legal</loc><changefreq>monthly</changefreq><priority>0.4</priority></url>
</urlset>
`;

const brandExports = join(import.meta.dir, "..", "brand", "exports");
const favicon = Bun.file(join(brandExports, "klaravex-icon-512.png"));
const ogImage = Bun.file(join(brandExports, "klaravex-og-image.png"));

const withSec = (extra: Record<string, string>) => ({ ...SECURITY_HEADERS, ...extra });

const serveAsset = (file: ReturnType<typeof Bun.file>, type: string) =>
  async () =>
    new Response(await file.arrayBuffer(), {
      headers: withSec({ "content-type": type, "cross-origin-resource-policy": "cross-origin" }),
    });

beforeAll(() => {
  server = Bun.serve({
    port: 0,
    routes: {
      "/": index,
      "/privacy": privacy,
      "/terms": terms,
      "/legal": legal,
      "/industries/healthcare": industriesHealthcare,
      "/industries/legal-financial": industriesLegalFinancial,
      "/industries/m365-smb": industriesM365Smb,
      "/about": about,
      "/services": services,
      "/contact": contact,
      "/faq": faq,
      "/404": notFound,
      "/health": () =>
        new Response("ok", {
          headers: withSec({ "content-type": "text/plain; charset=utf-8" }),
        }),
      "/favicon.png": serveAsset(favicon, "image/png"),
      "/og-image.png": serveAsset(ogImage, "image/png"),
      "/robots.txt": () =>
        new Response(ROBOTS_TXT, {
          headers: withSec({ "content-type": "text/plain; charset=utf-8" }),
        }),
      "/sitemap.xml": () =>
        new Response(SITEMAP_XML, {
          headers: withSec({ "content-type": "application/xml; charset=utf-8" }),
        }),
      "/.well-known/security.txt": () =>
        new Response(SECURITY_TXT, {
          headers: withSec({ "content-type": "text/plain; charset=utf-8" }),
        }),
      "/security.txt": () =>
        new Response(SECURITY_TXT, {
          headers: withSec({ "content-type": "text/plain; charset=utf-8" }),
        }),
    },
    fetch() {
      return new Response(notFoundSrc, {
        status: 404,
        headers: withSec({ "content-type": "text/html; charset=utf-8" }),
      });
    },
  });
  base = `http://${server.hostname}:${server.port}`;
});

afterAll(() => {
  server.stop(true);
});

test("/health returns ok", async () => {
  const res = await fetch(`${base}/health`);
  expect(res.status).toBe(200);
  expect(await res.text()).toBe("ok");
});

test("/ returns HTML with Klaravex brand mark in title", async () => {
  const res = await fetch(`${base}/`);
  expect(res.status).toBe(200);
  const contentType = res.headers.get("content-type") ?? "";
  expect(contentType).toContain("text/html");
  const body = await res.text();
  expect(body).toContain("Klaravex");
  expect(body.toLowerCase()).toContain("<!doctype html");
});

test("source code contains no CMMC/DIB references (policy guard)", () => {
  // CLAUDE.md (May 2026): NO defense/DIB/CMMC clients — ITAR route not pursued.
  // This guard prevents accidental re-introduction in marketing copy.
  for (const src of [frontendSrc, htmlSrc]) {
    expect(src).not.toMatch(/\bCMMC\b/);
    expect(src).not.toMatch(/Defense Subcontractor/i);
    expect(src).not.toMatch(/\bDIB\b/);
  }
});

test("source code surfaces required regulatory-readiness posture", () => {
  // US-primary regulatory verticals per CLAUDE.md "Klaravex.com positioning rules".
  // NIS2 was intentionally removed in iteration 3 — out of scope for US surface.
  expect(frontendSrc).toMatch(/HIPAA/);
  expect(frontendSrc).toMatch(/SOC 2/);
  expect(frontendSrc).toMatch(/ISO 27001/);
  expect(frontendSrc).toMatch(/Ubiquiti UniFi/);
});

test("source code uses readiness/advisory language, not 'compliance' as a promise (policy guard)", () => {
  // CLAUDE.md: "Never use 'compliance' in marketing — use 'readiness',
  // 'preparation', 'advisory'." The word "compliance" must not appear in the
  // live marketing surface (index.html title/meta, frontend.tsx copy).
  // It is allowed in long-form legal disclaimers under website/copy/*.md
  // because those describe what Klaravex does NOT do (issue certifications).
  for (const src of [frontendSrc, htmlSrc]) {
    expect(src.toLowerCase()).not.toMatch(/compliance/);
  }
});

test("source code does not over-claim EU as a primary market (policy guard)", () => {
  // CLAUDE.md "Klaravex.com positioning rules": klaravex.com is US-primary.
  // EU served via DPA only — a light-touch capability line is allowed, but
  // "US and EU SMBs" framing and NIS2/DORA leadership belong to
  // out of scope for the US-primary surface.
  for (const src of [frontendSrc, htmlSrc]) {
    expect(src).not.toMatch(/US and EU SMBs/i);
    expect(src).not.toMatch(/\bNIS2\b/);
    expect(src).not.toMatch(/\bDORA\b/);
    expect(src).not.toMatch(/EU entity in formation/i);
    expect(src).not.toMatch(/Klaravex GmbH/i);
  }
});

test("source code reflects US-primary positioning surface (policy guard)", () => {
  // Positive guard: the US-primary regulatory verticals must appear.
  expect(frontendSrc).toMatch(/HIPAA/);
  expect(frontendSrc).toMatch(/SOC 2/);
  expect(frontendSrc).toMatch(/ISO 27001/);
  expect(htmlSrc).toMatch(/US SMBs/);
});

test("/favicon.png serves a PNG", async () => {
  const res = await fetch(`${base}/favicon.png`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type")).toBe("image/png");
  // PNG magic bytes: 89 50 4E 47
  const buf = new Uint8Array(await res.arrayBuffer());
  expect(buf[0]).toBe(0x89);
  expect(buf[1]).toBe(0x50);
  expect(buf[2]).toBe(0x4e);
  expect(buf[3]).toBe(0x47);
});

test("/og-image.png serves a PNG", async () => {
  const res = await fetch(`${base}/og-image.png`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type")).toBe("image/png");
});

test("index.html declares OG and Twitter card meta with absolute klaravex.com URLs", () => {
  // Open Graph + Twitter cards must reference absolute URLs so social
  // previews resolve. Relative paths fail when the page is shared.
  expect(htmlSrc).toMatch(/<meta property="og:title"/);
  expect(htmlSrc).toMatch(/<meta property="og:image" content="https:\/\/klaravex\.com\/og-image\.png"/);
  expect(htmlSrc).toMatch(/<meta name="twitter:card" content="summary_large_image"/);
  expect(htmlSrc).toMatch(/<meta name="twitter:image" content="https:\/\/klaravex\.com\/og-image\.png"/);
});

test("index.html embeds JSON-LD Organization schema with US/WY address", () => {
  expect(htmlSrc).toMatch(/<script type="application\/ld\+json">/);
  expect(htmlSrc).toMatch(/"@type": "Organization"/);
  expect(htmlSrc).toMatch(/"legalName": "Klaravex LLC"/);
  expect(htmlSrc).toMatch(/"addressCountry": "US"/);
  expect(htmlSrc).toMatch(/"addressRegion": "WY"/);
});

test("/privacy serves the Privacy Policy page", async () => {
  const res = await fetch(`${base}/privacy`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("Privacy Policy");
  expect(body).toContain("Klaravex LLC");
});

test("/terms serves the Terms of Service page", async () => {
  const res = await fetch(`${base}/terms`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("Terms of Service");
  expect(body).toContain("Master Services Agreement");
});

test("privacy.html covers CCPA, GDPR, and contact path", () => {
  expect(privacySrc).toMatch(/CCPA/);
  expect(privacySrc).toMatch(/GDPR/);
  expect(privacySrc).toMatch(/hello@klaravex\.com/);
  expect(privacySrc).toMatch(/<link rel="canonical" href="https:\/\/klaravex\.com\/privacy"/);
});

test("terms.html names MSA precedence and Wyoming governing law", () => {
  expect(termsSrc).toMatch(/Master Services Agreement/);
  expect(termsSrc).toMatch(/Wyoming/);
  expect(termsSrc).toMatch(/<link rel="canonical" href="https:\/\/klaravex\.com\/terms"/);
});

test("frontend.tsx footer links to /privacy and /terms (no mailto stubs)", () => {
  expect(frontendSrc).toMatch(/href="\/privacy"/);
  expect(frontendSrc).toMatch(/href="\/terms"/);
  expect(frontendSrc).not.toMatch(/mailto:hello@klaravex\.com\?subject=Privacy/);
  expect(frontendSrc).not.toMatch(/mailto:hello@klaravex\.com\?subject=Terms/);
});

test("frontend.tsx footer surfaces /industries/healthcare so the new vertical is discoverable", () => {
  expect(frontendSrc).toMatch(/href="\/industries\/healthcare"/);
});

test("frontend.tsx footer surfaces /industries/legal-financial", () => {
  expect(frontendSrc).toMatch(/href="\/industries\/legal-financial"/);
});

test("frontend.tsx footer surfaces /industries/m365-smb", () => {
  // CLAUDE.md primary vertical #3: M365/GWorkspace/AWS SMBs. Discoverable
  // from the main marketing surface alongside healthcare and legal-financial.
  expect(frontendSrc).toMatch(/href="\/industries\/m365-smb"/);
});

test("privacy.html and terms.html keep policy guards (no CMMC/compliance/NIS2)", () => {
  for (const src of [privacySrc, termsSrc, legalSrc]) {
    expect(src).not.toMatch(/\bCMMC\b/);
    expect(src).not.toMatch(/\bDIB\b/);
    expect(src).not.toMatch(/\bNIS2\b/);
    expect(src).not.toMatch(/\bDORA\b/);
  }
  // "compliance" is allowed in legal pages because they describe what
  // Klaravex does NOT do (issue compliance certifications). The policy
  // guard only excludes it from the public marketing surface.
});

test("/legal serves the Legal Notices page", async () => {
  const res = await fetch(`${base}/legal`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("Legal Notices");
  expect(body).toContain("No Certification or Attestation");
});

test("legal.html declares Wyoming entity, USPTO trademark, and cross-links to privacy/terms", () => {
  expect(legalSrc).toMatch(/Wyoming/);
  expect(legalSrc).toMatch(/99856526/);
  expect(legalSrc).toMatch(/href="\/privacy"/);
  expect(legalSrc).toMatch(/href="\/terms"/);
  expect(legalSrc).toMatch(/<link rel="canonical" href="https:\/\/klaravex\.com\/legal"/);
});

test("/robots.txt allows all crawlers and references the sitemap", async () => {
  const res = await fetch(`${base}/robots.txt`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/plain");
  const body = await res.text();
  expect(body).toMatch(/User-agent: \*/);
  expect(body).toMatch(/Allow: \//);
  expect(body).toMatch(/Sitemap: https:\/\/klaravex\.com\/sitemap\.xml/);
});

test("/sitemap.xml lists the indexable URLs with absolute klaravex.com origins", async () => {
  const res = await fetch(`${base}/sitemap.xml`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("application/xml");
  const body = await res.text();
  expect(body).toMatch(/<\?xml version="1\.0" encoding="UTF-8"\?>/);
  expect(body).toMatch(/<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/);
  expect(body).toMatch(/<loc>https:\/\/klaravex\.com\/<\/loc>/);
  expect(body).toMatch(/<loc>https:\/\/klaravex\.com\/about<\/loc>/);
  expect(body).toMatch(/<loc>https:\/\/klaravex\.com\/services<\/loc>/);
  expect(body).toMatch(/<loc>https:\/\/klaravex\.com\/industries\/healthcare<\/loc>/);
  expect(body).toMatch(/<loc>https:\/\/klaravex\.com\/industries\/legal-financial<\/loc>/);
  expect(body).toMatch(/<loc>https:\/\/klaravex\.com\/privacy<\/loc>/);
  expect(body).toMatch(/<loc>https:\/\/klaravex\.com\/terms<\/loc>/);
  expect(body).toMatch(/<loc>https:\/\/klaravex\.com\/legal<\/loc>/);
});

test("unknown routes return the branded 404 page with status 404", async () => {
  const res = await fetch(`${base}/does-not-exist-${Date.now()}`);
  expect(res.status).toBe(404);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("Page not found");
  expect(body).toContain("Klaravex");
});

test("not-found.html is noindex and links back to the main marketing surface", () => {
  expect(notFoundSrc).toMatch(/<meta name="robots" content="noindex/);
  expect(notFoundSrc).toMatch(/href="\/"/);
  expect(notFoundSrc).toMatch(/href="\/#services"/);
  expect(notFoundSrc).toMatch(/href="\/privacy"/);
  expect(notFoundSrc).toMatch(/href="\/terms"/);
  expect(notFoundSrc).toMatch(/href="\/legal"/);
});

test("not-found.html keeps the marketing policy guards", () => {
  expect(notFoundSrc).not.toMatch(/\bCMMC\b/);
  expect(notFoundSrc).not.toMatch(/\bDIB\b/);
  expect(notFoundSrc).not.toMatch(/\bNIS2\b/);
  expect(notFoundSrc).not.toMatch(/\bDORA\b/);
  expect(notFoundSrc.toLowerCase()).not.toMatch(/compliance/);
});

// ─────────────────────────────────────────────────────────────────────────
// Security headers (iteration 6)
// A managed-security brand must ship the obvious HTTP defences on its own
// marketing site. HSTS + X-Content-Type-Options + X-Frame-Options +
// Referrer-Policy + Permissions-Policy + COOP/CORP are applied to every
// dynamic response. CSP + Referrer-Policy ride along on the bundled HTML
// pages via <meta> tags because Bun's HTML imports are owned by the
// bundler and not directly wrappable here.
// ─────────────────────────────────────────────────────────────────────────

const HEADER_SENSITIVE_ROUTES = [
  "/health",
  "/robots.txt",
  "/sitemap.xml",
  "/favicon.png",
  "/og-image.png",
  "/.well-known/security.txt",
  "/security.txt",
];

for (const route of HEADER_SENSITIVE_ROUTES) {
  test(`${route} emits the full security-header set`, async () => {
    const res = await fetch(`${base}${route}`);
    expect(res.status).toBe(200);
    expect(res.headers.get("strict-transport-security")).toMatch(/max-age=\d+/);
    expect(res.headers.get("strict-transport-security")).toContain("includeSubDomains");
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    expect(res.headers.get("x-frame-options")).toBe("DENY");
    expect(res.headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
    expect(res.headers.get("permissions-policy")).toMatch(/camera=\(\)/);
    expect(res.headers.get("permissions-policy")).toMatch(/microphone=\(\)/);
    expect(res.headers.get("permissions-policy")).toMatch(/geolocation=\(\)/);
    expect(res.headers.get("cross-origin-opener-policy")).toBe("same-origin");
  });
}

test("the 404 fallback response also carries security headers", async () => {
  const res = await fetch(`${base}/does-not-exist-headers-${Date.now()}`);
  expect(res.status).toBe(404);
  expect(res.headers.get("strict-transport-security")).toMatch(/max-age=/);
  expect(res.headers.get("x-frame-options")).toBe("DENY");
  expect(res.headers.get("x-content-type-options")).toBe("nosniff");
  expect(res.headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
});

test("static asset routes use cross-origin CORP so OG images render in third-party previews", async () => {
  for (const r of ["/favicon.png", "/og-image.png"]) {
    const res = await fetch(`${base}${r}`);
    expect(res.headers.get("cross-origin-resource-policy")).toBe("cross-origin");
  }
});

const htmlPages: Array<[string, string]> = [
  ["index.html", htmlSrc],
  ["privacy.html", privacySrc],
  ["terms.html", termsSrc],
  ["legal.html", legalSrc],
  ["industries-healthcare.html", industriesHealthcareSrc],
  ["industries-legal-financial.html", industriesLegalFinancialSrc],
  ["industries-m365-smb.html", industriesM365SmbSrc],
  ["about.html", aboutSrc],
  ["services.html", servicesSrc],
  ["contact.html", contactSrc],
  ["faq.html", faqSrc],
  ["not-found.html", notFoundSrc],
];

for (const [name, src] of htmlPages) {
  test(`${name} declares a Content-Security-Policy meta tag`, () => {
    expect(src).toMatch(/<meta http-equiv="Content-Security-Policy"/);
    expect(src).toMatch(/default-src 'self'/);
    expect(src).toMatch(/frame-ancestors 'none'/);
    expect(src).toMatch(/object-src 'none'/);
    expect(src).toMatch(/base-uri 'self'/);
    expect(src).toMatch(/upgrade-insecure-requests/);
  });

  test(`${name} declares a strict referrer policy via meta`, () => {
    expect(src).toMatch(/<meta name="referrer" content="strict-origin-when-cross-origin"/);
  });
}

// ─────────────────────────────────────────────────────────────────────────
// /industries/healthcare (iteration 7)
// First industry vertical page built from website/copy/11-industry-healthcare.md.
// Adapted to readiness/advisory language per CLAUDE.md positioning rules;
// "compliance" is only present inside the scope-disclaimer / "we don't
// certify" answers, where it describes what Klaravex does NOT do.
// ─────────────────────────────────────────────────────────────────────────

test("/industries/healthcare serves the HIPAA readiness advisory page", async () => {
  const res = await fetch(`${base}/industries/healthcare`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("HIPAA Security Rule readiness");
  expect(body).toContain("Klaravex");
  expect(body).toContain("Business Associate Agreement");
});

test("industries-healthcare.html ships the FAQPage JSON-LD schema", () => {
  expect(industriesHealthcareSrc).toMatch(/<script type="application\/ld\+json">/);
  expect(industriesHealthcareSrc).toMatch(/"@type": "FAQPage"/);
  expect(industriesHealthcareSrc).toMatch(/"@type": "Question"/);
  expect(industriesHealthcareSrc).toMatch(/Does Klaravex sign a BAA\?/);
});

test("industries-healthcare.html declares canonical and indexable robots meta", () => {
  expect(industriesHealthcareSrc).toMatch(
    /<link rel="canonical" href="https:\/\/klaravex\.com\/industries\/healthcare"/,
  );
  expect(industriesHealthcareSrc).toMatch(/<meta name="robots" content="index,follow"/);
});

test("industries-healthcare.html keeps the CMMC/DIB/NIS2/DORA marketing policy guards", () => {
  expect(industriesHealthcareSrc).not.toMatch(/\bCMMC\b/);
  expect(industriesHealthcareSrc).not.toMatch(/\bDIB\b/);
  expect(industriesHealthcareSrc).not.toMatch(/\bNIS2\b/);
  expect(industriesHealthcareSrc).not.toMatch(/\bDORA\b/);
});

test("industries-healthcare.html restricts 'compliance' to the disclaimer/FAQ scope", () => {
  // CLAUDE.md: marketing surfaces must use readiness/advisory language.
  // Disclaimer sections describing what Klaravex does NOT do may use
  // "compliance" — this test enforces that constraint structurally by
  // checking the high-visibility surfaces: <title>, the description
  // meta, the OG title/description, the H1, and the hero paragraph
  // immediately following the H1. The disclaimer body and the FAQ
  // JSON-LD intentionally retain "compliance" because they describe
  // what Klaravex does NOT do.
  const titleMatch = industriesHealthcareSrc.match(/<title>([\s\S]*?)<\/title>/);
  const descMatch = industriesHealthcareSrc.match(
    /<meta name="description" content="([^"]*)"/,
  );
  const ogTitleMatch = industriesHealthcareSrc.match(
    /<meta property="og:title" content="([^"]*)"/,
  );
  const ogDescMatch = industriesHealthcareSrc.match(
    /<meta property="og:description" content="([^"]*)"/,
  );
  const h1Match = industriesHealthcareSrc.match(/<h1>([\s\S]*?)<\/h1>/);

  for (const m of [titleMatch, descMatch, ogTitleMatch, ogDescMatch, h1Match]) {
    expect(m).not.toBeNull();
    expect((m![1] ?? "").toLowerCase()).not.toMatch(/compliance/);
  }
});

test("industries-healthcare.html links back to the main marketing surface and legal pages", () => {
  expect(industriesHealthcareSrc).toMatch(/href="\/"/);
  expect(industriesHealthcareSrc).toMatch(/href="\/privacy"/);
  expect(industriesHealthcareSrc).toMatch(/href="\/terms"/);
  expect(industriesHealthcareSrc).toMatch(/href="\/legal"/);
});

// ─────────────────────────────────────────────────────────────────────────
// /industries/legal-financial (iteration 8)
// Second industry vertical page built from
// website/copy/12-industry-legal-financial.md. Same disclaimer-pattern
// applies — promise-text uses readiness/advisory language; "compliance"
// only appears in the scope-disclaimer paragraph.
// ─────────────────────────────────────────────────────────────────────────

test("/industries/legal-financial serves the legal/financial readiness page", async () => {
  const res = await fetch(`${base}/industries/legal-financial`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("Klaravex");
  expect(body).toMatch(/PCI[\s-]?DSS/);
  expect(body).toMatch(/GLB/);
});

test("industries-legal-financial.html ships the FAQPage JSON-LD schema", () => {
  expect(industriesLegalFinancialSrc).toMatch(/<script type="application\/ld\+json">/);
  expect(industriesLegalFinancialSrc).toMatch(/"@type": "FAQPage"/);
  expect(industriesLegalFinancialSrc).toMatch(/"@type": "Question"/);
});

test("industries-legal-financial.html declares canonical and indexable robots meta", () => {
  expect(industriesLegalFinancialSrc).toMatch(
    /<link rel="canonical" href="https:\/\/klaravex\.com\/industries\/legal-financial"/,
  );
  expect(industriesLegalFinancialSrc).toMatch(/<meta name="robots" content="index,follow"/);
});

test("industries-legal-financial.html keeps the marketing policy guards", () => {
  expect(industriesLegalFinancialSrc).not.toMatch(/\bCMMC\b/);
  expect(industriesLegalFinancialSrc).not.toMatch(/\bDIB\b/);
  expect(industriesLegalFinancialSrc).not.toMatch(/\bNIS2\b/);
  expect(industriesLegalFinancialSrc).not.toMatch(/\bDORA\b/);
});

test("industries-legal-financial.html restricts 'compliance' to the disclaimer scope", () => {
  // High-visibility surfaces (title, description, og, h1) must be
  // readiness/advisory language only. "compliance" is allowed inside
  // the scope-disclaimer paragraph because it describes what Klaravex
  // does NOT do (PCI compliance must be validated by a QSA).
  const titleMatch = industriesLegalFinancialSrc.match(/<title>([\s\S]*?)<\/title>/);
  const descMatch = industriesLegalFinancialSrc.match(
    /<meta name="description" content="([^"]*)"/,
  );
  const ogTitleMatch = industriesLegalFinancialSrc.match(
    /<meta property="og:title" content="([^"]*)"/,
  );
  const ogDescMatch = industriesLegalFinancialSrc.match(
    /<meta property="og:description" content="([^"]*)"/,
  );
  const h1Match = industriesLegalFinancialSrc.match(/<h1>([\s\S]*?)<\/h1>/);
  for (const m of [titleMatch, descMatch, ogTitleMatch, ogDescMatch, h1Match]) {
    expect(m).not.toBeNull();
    expect((m![1] ?? "").toLowerCase()).not.toMatch(/compliance/);
  }
});

// ─────────────────────────────────────────────────────────────────────────
// /industries/m365-smb (iteration 7 — third primary vertical)
// Built from CLAUDE.md primary vertical #3: M365/GWorkspace/AWS SMBs.
// Same disclaimer-pattern as healthcare/legal-financial — high-visibility
// surfaces use readiness/advisory language; "compliance" only appears in
// the scope-disclaimer paragraph if at all.
// ─────────────────────────────────────────────────────────────────────────

test("/industries/m365-smb serves the M365/Workspace/AWS managed services page", async () => {
  const res = await fetch(`${base}/industries/m365-smb`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("Klaravex");
  expect(body).toMatch(/Microsoft 365/);
  expect(body).toMatch(/Google Workspace/);
  expect(body).toMatch(/AWS/);
  expect(body).toMatch(/Entra ID/);
});

test("industries-m365-smb.html ships the FAQPage JSON-LD schema", () => {
  expect(industriesM365SmbSrc).toMatch(/<script type="application\/ld\+json">/);
  expect(industriesM365SmbSrc).toMatch(/"@type": "FAQPage"/);
  expect(industriesM365SmbSrc).toMatch(/"@type": "Question"/);
});

test("industries-m365-smb.html declares canonical and indexable robots meta", () => {
  expect(industriesM365SmbSrc).toMatch(
    /<link rel="canonical" href="https:\/\/klaravex\.com\/industries\/m365-smb"/,
  );
  expect(industriesM365SmbSrc).toMatch(/<meta name="robots" content="index,follow"/);
});

test("industries-m365-smb.html keeps the marketing policy guards", () => {
  // CLAUDE.md: NO CMMC/DIB anywhere on klaravex.com; NIS2/DORA belong on
  // out of scope for the US-primary surface.
  expect(industriesM365SmbSrc).not.toMatch(/\bCMMC\b/);
  expect(industriesM365SmbSrc).not.toMatch(/\bDIB\b/);
  expect(industriesM365SmbSrc).not.toMatch(/\bNIS2\b/);
  expect(industriesM365SmbSrc).not.toMatch(/\bDORA\b/);
});

test("industries-m365-smb.html surfaces the UniFi tier benefit per CLAUDE.md", () => {
  // CLAUDE.md: "Ubiquiti UniFi firewall and network infrastructure
  // management included in all service tiers." Must be mentioned on the
  // SMB platform page where it is most relevant.
  expect(industriesM365SmbSrc).toMatch(/UniFi/);
});

test("industries-m365-smb.html restricts 'compliance' to the disclaimer scope", () => {
  // High-visibility surfaces (title, description, og, h1) must avoid
  // "compliance" per CLAUDE.md marketing policy.
  const titleMatch = industriesM365SmbSrc.match(/<title>([\s\S]*?)<\/title>/);
  const descMatch = industriesM365SmbSrc.match(
    /<meta name="description" content="([^"]*)"/,
  );
  const ogTitleMatch = industriesM365SmbSrc.match(
    /<meta property="og:title" content="([^"]*)"/,
  );
  const ogDescMatch = industriesM365SmbSrc.match(
    /<meta property="og:description" content="([^"]*)"/,
  );
  const h1Match = industriesM365SmbSrc.match(/<h1>([\s\S]*?)<\/h1>/);
  for (const m of [titleMatch, descMatch, ogTitleMatch, ogDescMatch, h1Match]) {
    expect(m).not.toBeNull();
    expect((m![1] ?? "").toLowerCase()).not.toMatch(/compliance/);
  }
});

test("industries-m365-smb.html links back to the main marketing surface and legal pages", () => {
  expect(industriesM365SmbSrc).toMatch(/href="\/"/);
  expect(industriesM365SmbSrc).toMatch(/href="\/privacy"/);
  expect(industriesM365SmbSrc).toMatch(/href="\/terms"/);
  expect(industriesM365SmbSrc).toMatch(/href="\/legal"/);
});

test("sitemap.xml lists the m365-smb industry page", async () => {
  const res = await fetch(`${base}/sitemap.xml`);
  expect(res.status).toBe(200);
  const body = await res.text();
  expect(body).toContain("https://klaravex.com/industries/m365-smb");
});

// ─────────────────────────────────────────────────────────────────────────
// BreadcrumbList JSON-LD on every industry page (iteration 7)
// Each industry page declares Home → Industries → <vertical> so Google
// can render breadcrumb chips in SERP results.
// ─────────────────────────────────────────────────────────────────────────

const industryPages: Array<[string, string]> = [
  ["industries-healthcare.html", industriesHealthcareSrc],
  ["industries-legal-financial.html", industriesLegalFinancialSrc],
  ["industries-m365-smb.html", industriesM365SmbSrc],
];

for (const [name, src] of industryPages) {
  test(`${name} ships BreadcrumbList JSON-LD with Home → Industries → vertical`, () => {
    expect(src).toMatch(/"@type": "BreadcrumbList"/);
    expect(src).toMatch(/"position": 1[\s\S]*?"name": "Home"/);
    expect(src).toMatch(/"position": 2[\s\S]*?"name": "Industries"/);
    expect(src).toMatch(/"position": 3/);
    // Sanity: at least the Home item resolves to the production URL.
    expect(src).toMatch(/"item": "https:\/\/klaravex\.com\/"/);
  });
}

// ─────────────────────────────────────────────────────────────────────────
// RFC 9116 security.txt (iteration 8)
// A managed-security brand must publish a coordinated-disclosure contact.
// /.well-known/security.txt is the canonical location; /security.txt is
// served as a mirror for crawlers that still hit the legacy path.
// ─────────────────────────────────────────────────────────────────────────

test("/.well-known/security.txt serves the RFC 9116 disclosure file", async () => {
  const res = await fetch(`${base}/.well-known/security.txt`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/plain");
  const body = await res.text();
  expect(body).toMatch(/^Contact: mailto:security@klaravex\.com$/m);
  expect(body).toMatch(/^Expires: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/m);
  expect(body).toMatch(/^Canonical: https:\/\/klaravex\.com\/\.well-known\/security\.txt$/m);
  expect(body).toMatch(/^Policy: https:\/\/klaravex\.com\/legal$/m);
});

test("/security.txt mirror serves identical content to the .well-known canonical", async () => {
  const [canonical, mirror] = await Promise.all([
    fetch(`${base}/.well-known/security.txt`).then((r) => r.text()),
    fetch(`${base}/security.txt`).then((r) => r.text()),
  ]);
  expect(mirror).toBe(canonical);
});

test("security.txt Expires field is in the future (RFC 9116 §2.5.5)", () => {
  // RFC 9116 requires Expires to be a date in the future. If this test ever
  // fails, rotate SECURITY_TXT's Expires before the rotation window closes.
  const expiresLine = SECURITY_TXT.match(/^Expires:\s*(.+)$/m);
  expect(expiresLine).not.toBeNull();
  const expiresDate = new Date(expiresLine![1].trim());
  expect(Number.isNaN(expiresDate.getTime())).toBe(false);
  expect(expiresDate.getTime()).toBeGreaterThan(Date.now());
});

test("security.txt declares Preferred-Languages including en", () => {
  expect(SECURITY_TXT).toMatch(/^Preferred-Languages:\s*[^\n]*\ben\b/m);
});

// ─────────────────────────────────────────────────────────────────────────
// /about (iteration 9)
// CLAUDE.md mandates a one-line Berlin/DPA capability disclosure in About
// (not on the homepage hero). This block enforces: the route serves, the
// page declares the right structured data, the policy guards stay in place,
// "compliance" is restricted to scope-disclaimer phrasing, and the Berlin
// principal + GDPR DPA capability line is present (light touch, not pitch).
// ─────────────────────────────────────────────────────────────────────────

test("/about serves the About page", async () => {
  const res = await fetch(`${base}/about`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("About Klaravex");
  expect(body).toContain("Wyoming");
  expect(body).toContain("Klaravex LLC");
});

test("about.html ships AboutPage, BreadcrumbList, and Organization JSON-LD", () => {
  expect(aboutSrc).toMatch(/"@type": "AboutPage"/);
  expect(aboutSrc).toMatch(/"@type": "BreadcrumbList"/);
  expect(aboutSrc).toMatch(/"@type": "Organization"/);
  expect(aboutSrc).toMatch(/"legalName": "Klaravex LLC"/);
  expect(aboutSrc).toMatch(/"addressCountry": "US"/);
  expect(aboutSrc).toMatch(/"addressRegion": "WY"/);
});

test("about.html declares canonical and indexable robots meta", () => {
  expect(aboutSrc).toMatch(
    /<link rel="canonical" href="https:\/\/klaravex\.com\/about"/,
  );
  expect(aboutSrc).toMatch(/<meta name="robots" content="index,follow"/);
});

test("about.html keeps the CMMC/DIB/NIS2/DORA marketing policy guards", () => {
  // CLAUDE.md: NO defense/DIB/CMMC clients anywhere on klaravex.com.
  // NIS2/DORA are out of scope for the US surface. The about page is the
  // most tempting place to bleed EU regulatory naming in — guard it.
  // CMMC may appear in the "Who we are not" section explicitly stating
  // we don't serve those clients; verify it is bracketed by the negation.
  expect(aboutSrc).not.toMatch(/\bNIS2\b/);
  expect(aboutSrc).not.toMatch(/\bDORA\b/);
  // "Klaravex GmbH" must not appear — it's visa-gated and not committed.
  expect(aboutSrc).not.toMatch(/Klaravex GmbH/i);
  expect(aboutSrc).not.toMatch(/EU entity in formation/i);
});

test("about.html restricts 'compliance' to scope-disclaimer phrasing", () => {
  // Title, meta description, OG meta, and H1 must remain in
  // readiness/advisory voice per CLAUDE.md marketing policy.
  const titleMatch = aboutSrc.match(/<title>([\s\S]*?)<\/title>/);
  const descMatch = aboutSrc.match(
    /<meta name="description" content="([^"]*)"/,
  );
  const ogTitleMatch = aboutSrc.match(
    /<meta property="og:title" content="([^"]*)"/,
  );
  const ogDescMatch = aboutSrc.match(
    /<meta property="og:description" content="([^"]*)"/,
  );
  const h1Match = aboutSrc.match(/<h1>([\s\S]*?)<\/h1>/);
  for (const m of [titleMatch, descMatch, ogTitleMatch, ogDescMatch, h1Match]) {
    expect(m).not.toBeNull();
    expect((m![1] ?? "").toLowerCase()).not.toMatch(/compliance/);
  }
});

test("about.html carries the Berlin-principal + GDPR DPA capability disclosure", () => {
  // CLAUDE.md "Klaravex.com positioning rules":
  //   "LIGHT TOUCH (capability, not pitch): 'Berlin-based principal;
  //    EU clients served under GDPR DPA.' One line in About, not a
  //    primary vertical."
  // The About page is the designated home for that line.
  expect(aboutSrc).toMatch(/Berlin/);
  expect(aboutSrc).toMatch(/GDPR/);
  expect(aboutSrc).toMatch(/Data Processing Addendum|DPA/);
});

test("about.html names the explicit market exclusions per CLAUDE.md", () => {
  // CLAUDE.md (May 2026 decision, recorded in CONTINUITY history):
  // "NO defense/DIB/CMMC clients. ITAR route not pursued. Do not
  //  re-open without export controls counsel."
  // The About page must surface this exclusion so prospects self-route.
  expect(aboutSrc).toMatch(/defense|DIB|CMMC|ITAR/);
});

test("about.html links back to home, industries, legal pages, and security.txt", () => {
  expect(aboutSrc).toMatch(/href="\/"/);
  expect(aboutSrc).toMatch(/href="\/industries\/healthcare"/);
  expect(aboutSrc).toMatch(/href="\/industries\/legal-financial"/);
  expect(aboutSrc).toMatch(/href="\/industries\/m365-smb"/);
  expect(aboutSrc).toMatch(/href="\/privacy"/);
  expect(aboutSrc).toMatch(/href="\/terms"/);
  expect(aboutSrc).toMatch(/href="\/legal"/);
  expect(aboutSrc).toMatch(/href="\/\.well-known\/security\.txt"/);
});

test("frontend.tsx nav and footer surface /about so the page is discoverable", () => {
  // The homepage is the entry point — About must be reachable from both
  // the top nav and the footer to maintain a single click depth.
  const navHits = frontendSrc.match(/href="\/about"/g) ?? [];
  expect(navHits.length).toBeGreaterThanOrEqual(2);
});

test("industry pages surface /about in their footer navigation", () => {
  for (const src of [
    industriesHealthcareSrc,
    industriesLegalFinancialSrc,
    industriesM365SmbSrc,
  ]) {
    expect(src).toMatch(/href="\/about"/);
  }
});

// ─────────────────────────────────────────────────────────────────────────
// /services (iteration 9 — extension)
// CLAUDE.md GTM rule: "Lead with Directive tier in ALL sales conversations.
// Foundation is a delivery mechanism, not the pitch." The /services page
// makes that ordering explicit on the marketing surface — Directive first,
// then Assurance, then Foundation — and carries Schema.org Service markup
// inside an ItemList so search engines render the tiers as a structured
// service offer.
// ─────────────────────────────────────────────────────────────────────────

test("/services serves the tier-detail page", async () => {
  const res = await fetch(`${base}/services`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("Service Tiers");
  expect(body).toContain("Directive");
  expect(body).toContain("Assurance");
  expect(body).toContain("Foundation");
});

test("services.html orders Directive before Assurance before Foundation (GTM rule)", () => {
  // CLAUDE.md: "Lead with Directive tier in ALL sales conversations."
  // Structurally enforce that Directive's H2 appears before Assurance's,
  // and Assurance's before Foundation's, on the marketing tier page.
  const directiveIdx = servicesSrc.indexOf("Tier 3 — Directive");
  const assuranceIdx = servicesSrc.indexOf("Tier 2 — Assurance");
  const foundationIdx = servicesSrc.indexOf("Tier 1 — Foundation");
  expect(directiveIdx).toBeGreaterThan(0);
  expect(assuranceIdx).toBeGreaterThan(0);
  expect(foundationIdx).toBeGreaterThan(0);
  expect(directiveIdx).toBeLessThan(assuranceIdx);
  expect(assuranceIdx).toBeLessThan(foundationIdx);
});

test("services.html ships ItemList + Service + BreadcrumbList JSON-LD", () => {
  expect(servicesSrc).toMatch(/"@type": "ItemList"/);
  expect(servicesSrc).toMatch(/"@type": "Service"/);
  expect(servicesSrc).toMatch(/"@type": "BreadcrumbList"/);
  expect(servicesSrc).toMatch(/"name": "Directive"/);
  expect(servicesSrc).toMatch(/"name": "Assurance"/);
  expect(servicesSrc).toMatch(/"name": "Foundation"/);
});

test("services.html declares canonical and indexable robots meta", () => {
  expect(servicesSrc).toMatch(
    /<link rel="canonical" href="https:\/\/klaravex\.com\/services"/,
  );
  expect(servicesSrc).toMatch(/<meta name="robots" content="index,follow"/);
});

test("services.html keeps marketing policy guards", () => {
  expect(servicesSrc).not.toMatch(/\bCMMC\b/);
  expect(servicesSrc).not.toMatch(/\bDIB\b/);
  expect(servicesSrc).not.toMatch(/\bNIS2\b/);
  expect(servicesSrc).not.toMatch(/\bDORA\b/);
  expect(servicesSrc).not.toMatch(/Klaravex GmbH/i);
});

test("services.html restricts 'compliance' to scope-disclaimer phrasing", () => {
  const titleMatch = servicesSrc.match(/<title>([\s\S]*?)<\/title>/);
  const descMatch = servicesSrc.match(
    /<meta name="description" content="([^"]*)"/,
  );
  const ogTitleMatch = servicesSrc.match(
    /<meta property="og:title" content="([^"]*)"/,
  );
  const ogDescMatch = servicesSrc.match(
    /<meta property="og:description" content="([^"]*)"/,
  );
  const h1Match = servicesSrc.match(/<h1>([\s\S]*?)<\/h1>/);
  for (const m of [titleMatch, descMatch, ogTitleMatch, ogDescMatch, h1Match]) {
    expect(m).not.toBeNull();
    expect((m![1] ?? "").toLowerCase()).not.toMatch(/compliance/);
  }
});

test("services.html surfaces UniFi inclusion across tiers (per CLAUDE.md)", () => {
  // CLAUDE.md: "Ubiquiti UniFi firewall and network infrastructure
  // management included in all service tiers."
  expect(servicesSrc).toMatch(/UniFi/);
});

test("services.html prices match CLAUDE.md service-tier rate guidance", () => {
  // CLAUDE.md "Service tiers": Foundation (~$75–100/user/mo) ·
  // Assurance (~$100–150) · Directive (~$150–250). Source uses an
  // en-dash range (e.g. "$75–100"), so assert each range's lower bound
  // plus an en-dash plus the upper bound — the canonical price-band
  // glyph the marketing surface ships.
  expect(servicesSrc).toMatch(/\$75[–-]100/);
  expect(servicesSrc).toMatch(/\$100[–-]150/);
  expect(servicesSrc).toMatch(/\$150[–-]250/);
});

test("services.html cross-links to industry verticals and legal pages", () => {
  expect(servicesSrc).toMatch(/href="\/about"/);
  expect(servicesSrc).toMatch(/href="\/industries\/healthcare"/);
  expect(servicesSrc).toMatch(/href="\/industries\/legal-financial"/);
  expect(servicesSrc).toMatch(/href="\/industries\/m365-smb"/);
  expect(servicesSrc).toMatch(/href="\/privacy"/);
  expect(servicesSrc).toMatch(/href="\/terms"/);
  expect(servicesSrc).toMatch(/href="\/legal"/);
});

// ─────────────────────────────────────────────────────────────────────────
// /contact (iteration 10)
// A managed-security marketing site without a contact page is incomplete.
// The /contact page surfaces three deliberately-separated lanes: prospective
// engagements (hello@), existing-client support (support@), and coordinated
// vulnerability disclosure (security@) — the same three contact points
// CLAUDE.md names. It also carries ContactPage + BreadcrumbList JSON-LD and
// stays inside the readiness/advisory marketing-language policy.
// ─────────────────────────────────────────────────────────────────────────

test("/contact serves the Contact page", async () => {
  const res = await fetch(`${base}/contact`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("Contact");
  expect(body).toContain("Klaravex");
});

test("contact.html ships ContactPage + BreadcrumbList JSON-LD", () => {
  expect(contactSrc).toMatch(/"@type": "ContactPage"/);
  expect(contactSrc).toMatch(/"@type": "BreadcrumbList"/);
  expect(contactSrc).toMatch(/"position": 1[\s\S]*?"name": "Home"/);
  expect(contactSrc).toMatch(/"position": 2[\s\S]*?"name": "Contact"/);
});

test("contact.html surfaces the three CLAUDE.md contact lanes", () => {
  // CLAUDE.md "Domain & identity":
  //   "Brand email: hello@klaravex.com · support@klaravex.com"
  // and the security contact is published per RFC 9116 (iteration 8).
  // All three must be reachable from /contact so prospects/clients/researchers
  // self-route to the correct inbox.
  expect(contactSrc).toMatch(/hello@klaravex\.com/);
  expect(contactSrc).toMatch(/support@klaravex\.com/);
  expect(contactSrc).toMatch(/security@klaravex\.com/);
});

test("contact.html declares ContactPoint entries for the three lanes", () => {
  // Structured data must mirror the visible contact lanes so search engines
  // surface them in knowledge-graph contact cards.
  expect(contactSrc).toMatch(/"contactType": "sales"/);
  expect(contactSrc).toMatch(/"contactType": "customer support"/);
  expect(contactSrc).toMatch(/"contactType": "security"/);
});

test("contact.html declares canonical and indexable robots meta", () => {
  expect(contactSrc).toMatch(
    /<link rel="canonical" href="https:\/\/klaravex\.com\/contact"/,
  );
  expect(contactSrc).toMatch(/<meta name="robots" content="index,follow"/);
});

test("contact.html keeps the CMMC/DIB/NIS2/DORA marketing policy guards", () => {
  // CLAUDE.md: NIS2/DORA are out of scope for the US surface. CMMC may appear only
  // in an explicit out-of-scope negation. NIS2 must not appear at all.
  expect(contactSrc).not.toMatch(/\bNIS2\b/);
  expect(contactSrc).not.toMatch(/\bDORA\b/);
  expect(contactSrc).not.toMatch(/Klaravex GmbH/i);
  expect(contactSrc).not.toMatch(/EU entity in formation/i);
});

test("contact.html restricts 'compliance' to scope-disclaimer phrasing", () => {
  // Title, meta description, OG meta, and H1 must remain in readiness/advisory
  // voice per CLAUDE.md marketing policy.
  const titleMatch = contactSrc.match(/<title>([\s\S]*?)<\/title>/);
  const descMatch = contactSrc.match(
    /<meta name="description" content="([^"]*)"/,
  );
  const ogTitleMatch = contactSrc.match(
    /<meta property="og:title" content="([^"]*)"/,
  );
  const ogDescMatch = contactSrc.match(
    /<meta property="og:description" content="([^"]*)"/,
  );
  const h1Match = contactSrc.match(/<h1>([\s\S]*?)<\/h1>/);
  for (const m of [titleMatch, descMatch, ogTitleMatch, ogDescMatch, h1Match]) {
    expect(m).not.toBeNull();
    expect((m![1] ?? "").toLowerCase()).not.toMatch(/compliance/);
  }
});

test("contact.html points at the RFC 9116 security.txt for the disclosure lane", () => {
  expect(contactSrc).toMatch(/href="\/\.well-known\/security\.txt"/);
});

test("contact.html cross-links to about, services, industries, and legal pages", () => {
  expect(contactSrc).toMatch(/href="\/about"/);
  expect(contactSrc).toMatch(/href="\/services"/);
  expect(contactSrc).toMatch(/href="\/industries\/healthcare"/);
  expect(contactSrc).toMatch(/href="\/industries\/legal-financial"/);
  expect(contactSrc).toMatch(/href="\/industries\/m365-smb"/);
  expect(contactSrc).toMatch(/href="\/privacy"/);
  expect(contactSrc).toMatch(/href="\/terms"/);
  expect(contactSrc).toMatch(/href="\/legal"/);
});

test("sitemap.xml lists the contact page", async () => {
  const res = await fetch(`${base}/sitemap.xml`);
  expect(res.status).toBe(200);
  const body = await res.text();
  expect(body).toContain("https://klaravex.com/contact");
});

test("about, services, and industry pages surface /contact in their footer", () => {
  // /contact must be reachable in one click from every primary marketing
  // surface, not only from the homepage. This guards against drift where a
  // new footer pattern is rolled out without the contact link.
  for (const src of [
    aboutSrc,
    servicesSrc,
    industriesHealthcareSrc,
    industriesLegalFinancialSrc,
    industriesM365SmbSrc,
  ]) {
    expect(src).toMatch(/href="\/contact"/);
  }
});

test("not-found.html links to the dedicated /contact page (not the homepage anchor)", () => {
  // After /contact ships, the 404 page should send confused visitors to the
  // dedicated contact page, not back to /#contact on the homepage.
  expect(notFoundSrc).toMatch(/href="\/contact"/);
  expect(notFoundSrc).not.toMatch(/href="\/#contact"/);
});

// ─────────────────────────────────────────────────────────────────────────
// /faq (iteration 11)
// Centralised FAQ aggregator covering engagement model, service tiers,
// scope disclaimers, EU coverage under GDPR DPA, UniFi inclusion, Klaravex AI
// usage, and the explicit defense/DIB/CMMC exclusion. Carries FAQPage +
// BreadcrumbList JSON-LD; promise-text stays inside CLAUDE.md's
// readiness/advisory marketing-language policy.
// ─────────────────────────────────────────────────────────────────────────

test("/faq serves the FAQ page", async () => {
  const res = await fetch(`${base}/faq`);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type") ?? "").toContain("text/html");
  const body = await res.text();
  expect(body).toContain("Frequently Asked Questions");
  expect(body).toContain("Klaravex");
});

test("faq.html ships FAQPage + BreadcrumbList JSON-LD", () => {
  expect(faqSrc).toMatch(/"@type": "FAQPage"/);
  expect(faqSrc).toMatch(/"@type": "Question"/);
  expect(faqSrc).toMatch(/"@type": "Answer"/);
  expect(faqSrc).toMatch(/"@type": "BreadcrumbList"/);
  expect(faqSrc).toMatch(/"position": 1[\s\S]*?"name": "Home"/);
  expect(faqSrc).toMatch(/"position": 2[\s\S]*?"name": "FAQ"/);
});

test("faq.html declares canonical and indexable robots meta", () => {
  expect(faqSrc).toMatch(
    /<link rel="canonical" href="https:\/\/klaravex\.com\/faq"/,
  );
  expect(faqSrc).toMatch(/<meta name="robots" content="index,follow"/);
});

test("faq.html covers the questions that drive prospect self-qualification", () => {
  // The FAQ aggregator must answer the questions that recur on every
  // discovery call so prospects can self-qualify before writing to
  // hello@. Each pattern below corresponds to a published FAQ question.
  expect(faqSrc).toMatch(/Foundation/);
  expect(faqSrc).toMatch(/Assurance/);
  expect(faqSrc).toMatch(/Directive/);
  expect(faqSrc).toMatch(/HIPAA/);
  expect(faqSrc).toMatch(/SOC 2/);
  expect(faqSrc).toMatch(/ISO 27001/);
  expect(faqSrc).toMatch(/UniFi/);
  expect(faqSrc).toMatch(/GDPR/);
  expect(faqSrc).toMatch(/Data Processing Addendum|DPA/);
  expect(faqSrc).toMatch(/Klaravex AI/);
  expect(faqSrc).toMatch(/10[\s–-]+250/);
});

test("faq.html surfaces the CLAUDE.md tier price bands", () => {
  // Price bands must match the canonical CLAUDE.md tier guidance so the
  // FAQ does not drift from the /services tier-detail page.
  expect(faqSrc).toMatch(/\$75[–-]100/);
  expect(faqSrc).toMatch(/\$100[–-]150/);
  expect(faqSrc).toMatch(/\$150[–-]250/);
});

test("faq.html keeps the marketing policy guards (NIS2/DORA/GmbH never appear)", () => {
  // CLAUDE.md: NIS2/DORA are out of scope, never on klaravex.com.
  // "Klaravex GmbH" must not appear — it is visa-gated and not committed.
  // Defense/DIB/CMMC may appear ONLY inside an explicit out-of-scope negation;
  // we verify negation context below rather than banning the words outright.
  expect(faqSrc).not.toMatch(/\bNIS2\b/);
  expect(faqSrc).not.toMatch(/\bDORA\b/);
  expect(faqSrc).not.toMatch(/Klaravex GmbH/i);
  expect(faqSrc).not.toMatch(/EU entity in formation/i);
});

test("faq.html restricts 'compliance' to scope-disclaimer phrasing", () => {
  // High-visibility surfaces — title, meta description, OG title/description,
  // and the H1 — must stay in readiness/advisory voice. "compliance" is
  // allowed inside FAQ answer bodies and the scope-disclaimer paragraph
  // because they describe what Klaravex does NOT do (issue certifications).
  const titleMatch = faqSrc.match(/<title>([\s\S]*?)<\/title>/);
  const descMatch = faqSrc.match(/<meta name="description" content="([^"]*)"/);
  const ogTitleMatch = faqSrc.match(
    /<meta property="og:title" content="([^"]*)"/,
  );
  const ogDescMatch = faqSrc.match(
    /<meta property="og:description" content="([^"]*)"/,
  );
  const h1Match = faqSrc.match(/<h1>([\s\S]*?)<\/h1>/);
  for (const m of [titleMatch, descMatch, ogTitleMatch, ogDescMatch, h1Match]) {
    expect(m).not.toBeNull();
    expect((m![1] ?? "").toLowerCase()).not.toMatch(/compliance/);
  }
});

test("faq.html mentions CMMC and DIB only inside an explicit out-of-scope answer", () => {
  // CLAUDE.md: defense/DIB/CMMC may only appear on klaravex.com when
  // bracketed by a clear negation ("No.", "explicitly out of scope",
  // "explicitly declined"). This guards against accidental positive
  // mentions creeping in later through copy edits.
  const cmmcQuestion = faqSrc.match(
    /Do you serve US defense contractors, DIB, or CMMC engagements\?[\s\S]{0,2000}/,
  );
  expect(cmmcQuestion).not.toBeNull();
  const block = cmmcQuestion![0];
  expect(block).toMatch(/out of scope/i);
  expect(block).toMatch(/ITAR/);
});

test("faq.html links back to home, services, contact, security.txt, and legal pages", () => {
  expect(faqSrc).toMatch(/href="\/"/);
  expect(faqSrc).toMatch(/href="\/about"/);
  expect(faqSrc).toMatch(/href="\/services"/);
  expect(faqSrc).toMatch(/href="\/contact"/);
  expect(faqSrc).toMatch(/href="\/industries\/healthcare"/);
  expect(faqSrc).toMatch(/href="\/industries\/legal-financial"/);
  expect(faqSrc).toMatch(/href="\/industries\/m365-smb"/);
  expect(faqSrc).toMatch(/href="\/\.well-known\/security\.txt"/);
  expect(faqSrc).toMatch(/href="\/privacy"/);
  expect(faqSrc).toMatch(/href="\/terms"/);
  expect(faqSrc).toMatch(/href="\/legal"/);
});

test("sitemap.xml lists the faq page", async () => {
  const res = await fetch(`${base}/sitemap.xml`);
  expect(res.status).toBe(200);
  const body = await res.text();
  expect(body).toContain("https://klaravex.com/faq");
});

test("about, services, contact, and industry pages surface /faq in their footer", () => {
  // /faq must be reachable in one click from every primary marketing
  // surface so prospects can resolve common questions without writing
  // first. Guards against drift where a new footer pattern is rolled
  // out without the FAQ link.
  for (const src of [
    aboutSrc,
    servicesSrc,
    contactSrc,
    industriesHealthcareSrc,
    industriesLegalFinancialSrc,
    industriesM365SmbSrc,
  ]) {
    expect(src).toMatch(/href="\/faq"/);
  }
});

test("frontend.tsx footer surfaces /faq so the homepage routes to it", () => {
  expect(frontendSrc).toMatch(/href="\/faq"/);
});

test("SECURITY_HEADERS exports a stable shape the deploy layer can mirror", () => {
  // Edge/CDN configuration must mirror these — keep keys lower-case so they
  // can be diff-compared against Cloudflare Transform Rules or Vercel
  // headers config without case normalisation.
  for (const key of Object.keys(SECURITY_HEADERS)) {
    expect(key).toBe(key.toLowerCase());
  }
  expect(SECURITY_HEADERS["strict-transport-security"]).toContain("preload");
  expect(SECURITY_HEADERS["x-frame-options"]).toBe("DENY");
  expect(SECURITY_HEADERS["x-content-type-options"]).toBe("nosniff");
});
