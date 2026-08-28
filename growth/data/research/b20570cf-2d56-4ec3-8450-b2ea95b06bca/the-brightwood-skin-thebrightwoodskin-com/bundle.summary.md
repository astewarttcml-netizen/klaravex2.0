# Research summary — The Brightwood Skin

**Domain:** thebrightwoodskin.com
**Confidence:** 0.50
**Contact:** Katelyn Laskosky

## Signals (cite signal_id in outreach copy)

| signal_id | scraper | excerpt |
|-----------|---------|---------|
| web-01 | web_scanner | X-Powered-By header exposes: Next.js, Payload |
| web-02 | web_scanner | Missing CSP header (Content-Security-Policy) |
| web-03 | web_scanner | Missing X-Frame-Options header (X-Frame-Options) |
| web-04 | web_scanner | Missing X-Content-Type-Options header (X-Content-Type-Options) |
| web-05 | web_scanner | Missing Referrer-Policy header (Referrer-Policy) |
| web-06 | web_scanner | Missing Permissions-Policy header (Permissions-Policy) |
| web-07 | web_scanner | Server: Vercel |
| web-08 | web_scanner | Email: Google Workspace |
| web-09 | web_scanner | Analytics: Google Analytics/GTM |
| web-10 | web_scanner | SSL: Using Let's Encrypt (free cert — no EV/OV validation) |
| web-11 | web_scanner | DNS: No DMARC record — anyone can spoof emails from thebrightwoodskin.com |
| web-12 | web_scanner | DNS: SPF uses ~all (softfail) instead of -all (hardfail) |
| soc-01 | social_hook | News: "Feed Me's Ultimate Beauty Black Book. - Feed Me" (Feed Me, Tue, 22 Oct 2024) |
| news-01 | news_mentions | News: "Feed Me's Ultimate Beauty Black Book. - Feed Me" (Feed Me, Tue, 22 Oct 2024) |
| tech-01 | tech_stack | Server: Vercel |
| tech-02 | tech_stack | Email: Google Workspace |
| tech-03 | tech_stack | Analytics: Google Analytics/GTM |
| ssl-01 | ssl_scanner | SSL: Using Let's Encrypt (free cert — no EV/OV validation) |
| ssl-02 | ssl_scanner | DNS: No DMARC record — anyone can spoof emails from thebrightwoodskin.com |
| ssl-03 | ssl_scanner | DNS: SPF uses ~all (softfail) instead of -all (hardfail) |
