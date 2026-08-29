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
import { join } from "node:path";

const port = process.env.PORT ? parseInt(process.env.PORT) : 3000;

const brandExports = join(import.meta.dir, "..", "brand", "exports");
const favicon = Bun.file(join(brandExports, "klaravex-icon-512.png"));
const ogImage = Bun.file(join(brandExports, "klaravex-og-image.png"));

// HTTP security headers applied to every dynamic response. Bun's HTML imports
// are bundled internally and cannot be wrapped here — those routes carry a
// CSP + referrer policy via <meta> tags in the HTML <head> instead. The
// edge/CDN layer (Cloudflare/Vercel) MUST still emit HSTS + X-Frame-Options
// + Permissions-Policy on the static HTML responses in production.
export const SECURITY_HEADERS: Record<string, string> = {
  "strict-transport-security": "max-age=31536000; includeSubDomains; preload",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
  "referrer-policy": "strict-origin-when-cross-origin",
  "permissions-policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
  "cross-origin-opener-policy": "same-origin",
  "cross-origin-resource-policy": "same-origin",
};

const withSecurity = (extra: Record<string, string> = {}): Record<string, string> => ({
  ...SECURITY_HEADERS,
  ...extra,
});

const serveAsset = (file: ReturnType<typeof Bun.file>, type: string) =>
  async () =>
    new Response(await file.arrayBuffer(), {
      headers: withSecurity({
        "content-type": type,
        "cache-control": "public, max-age=86400",
        "cross-origin-resource-policy": "cross-origin",
      }),
    });

const ROBOTS_TXT = `User-agent: *
Allow: /

Sitemap: https://klaravex.com/sitemap.xml
`;

// RFC 9116 security.txt — published at /.well-known/security.txt with a
// mirror at /security.txt. A managed-security brand must publish its own
// coordinated vulnerability disclosure contact. Expires is set ~12 months
// out per RFC 9116 §2.5.5; rotate before the date passes.
export const SECURITY_TXT = `Contact: mailto:security@klaravex.com
Expires: 2027-06-06T00:00:00.000Z
Preferred-Languages: en
Canonical: https://klaravex.com/.well-known/security.txt
Canonical: https://klaravex.com/security.txt
Policy: https://klaravex.com/legal
`;

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

// Run the server only when this file is executed directly (`bun run server.ts`).
// Importing it from tests must NOT start a live listener.
if (import.meta.main) {
  Bun.serve({
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
          headers: withSecurity({ "content-type": "text/plain; charset=utf-8" }),
        }),
      "/favicon.png": serveAsset(favicon, "image/png"),
      "/og-image.png": serveAsset(ogImage, "image/png"),
      "/robots.txt": () =>
        new Response(ROBOTS_TXT, {
          headers: withSecurity({
            "content-type": "text/plain; charset=utf-8",
            "cache-control": "public, max-age=86400",
          }),
        }),
      "/sitemap.xml": () =>
        new Response(SITEMAP_XML, {
          headers: withSecurity({
            "content-type": "application/xml; charset=utf-8",
            "cache-control": "public, max-age=86400",
          }),
        }),
      "/.well-known/security.txt": () =>
        new Response(SECURITY_TXT, {
          headers: withSecurity({
            "content-type": "text/plain; charset=utf-8",
            "cache-control": "public, max-age=86400",
          }),
        }),
      "/security.txt": () =>
        new Response(SECURITY_TXT, {
          headers: withSecurity({
            "content-type": "text/plain; charset=utf-8",
            "cache-control": "public, max-age=86400",
          }),
        }),
    },
    async fetch() {
      return new Response(await Bun.file(join(import.meta.dir, "not-found.html")).text(), {
        status: 404,
        headers: withSecurity({ "content-type": "text/html; charset=utf-8" }),
      });
    },
    development: {
      hmr: true,
      console: true,
    },
    port,
  });

  console.log(`Klaravex dev server → http://localhost:${port}`);
}
