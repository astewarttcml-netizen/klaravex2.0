import React from "react";
import { createRoot } from "react-dom/client";

const SERVICES = [
  {
    tier: "Tier 1",
    name: "Foundation",
    price: "$100/user/mo",
    desc: "Operational baseline for businesses moving off break/fix. Reliable managed IT without regulatory-readiness overhead.",
    features: [
      "RMM + patch management",
      "Tier-1 helpdesk + Klaravex AI first-line support",
      "EDR endpoint agent",
      "Microsoft 365 user management",
      "Ubiquiti UniFi firewall & network management",
      "Monthly reporting",
    ],
    featured: false,
  },
  {
    tier: "Tier 2",
    name: "Assurance",
    price: "$165/user/mo",
    desc: "Security-aware operations for businesses that have had an incident — or fear one.",
    features: [
      "Everything in Foundation",
      "Proactive security monitoring",
      "Backup & disaster recovery",
      "SIEM / log aggregation",
      "Ubiquiti UniFi network monitoring & segmentation",
      "Vendor management",
    ],
    featured: false,
  },
  {
    tier: "Tier 3",
    name: "Directive",
    price: "$295/user/mo",
    desc: "Readiness advisory and strategic depth for regulated industries, healthcare-adjacent firms, and SMBs facing multi-state or EU obligations.",
    features: [
      "Everything in Assurance",
      "24/7 MDR (Managed Detection & Response)",
      "vCISO advisory",
      "HIPAA · SOC 2 · ISO 27001 readiness",
      "Multi-state US privacy advisory (CCPA/CDPA/VCDPA)",
      "Strategic IT roadmap",
      "Entra ID identity governance",
      "Onsite SLA available",
    ],
    featured: true,
  },
];

const VERTICALS = [
  {
    reg: "HIPAA",
    name: "Healthcare-Adjacent SMBs",
    pain: "2025 Security Rule modernisation and intensified OCR enforcement. A single violation: up to $50K. Most clinics have no dedicated security team.",
  },
  {
    reg: "PCI-DSS v4.0 · State Privacy",
    name: "Legal & Financial Services",
    pain: "20+ active state privacy regimes. PCI-DSS v4.0 deadline passed. Multi-state regulatory burden is too complex for generalist IT support.",
  },
  {
    reg: "Microsoft 365 · Google Workspace · AWS",
    name: "General SMBs (10–250 employees)",
    pain: "61% of SMBs report difficulty hiring IT staff. 57% cite security as their top priority. Senior expertise on call — without the senior salary.",
  },
  {
    reg: "Microsoft 365 · Entra ID · Defender",
    name: "Microsoft 365 Tenant Hardening",
    pain: "Most SMB M365 tenants ship with defaults that fail a SOC 2 audit and leak data through over-permissioned guest access. Entra ID conditional access, Purview DLP, and Defender for Business are the controls that move the needle.",
  },
];

const WHY = [
  {
    icon: "🔒",
    title: "Readiness-native, not readiness-adjacent",
    text: "We speak HIPAA, SOC 2, and ISO 27001 as primary languages — not afterthoughts bolted onto a helpdesk practice.",
  },
  {
    icon: "🏗️",
    title: "Microsoft 365 depth",
    text: "Entra ID architecture, Purview data governance, Defender for Business, Copilot deployment — the full tenant, hardened.",
  },
  {
    icon: "🎯",
    title: "SMB-sized engagement, enterprise expertise",
    text: "Senior-level security and regulatory-readiness knowledge on retainer. No junior technicians learning on your dime.",
  },
  {
    icon: "📋",
    title: "Scope-limited by design",
    text: "We provide readiness and advisory — not certification conduct. Every SOW defines exactly where our work ends and yours begins.",
  },
];

function App() {
  return (
    <>
      {/* Nav */}
      <nav>
        <div className="container nav-inner">
          <a href="#" className="logo">
            KLARA<span>VEX</span>
          </a>
          <ul className="nav-links">
            <li><a href="/services">Services</a></li>
            <li><a href="#verticals">Verticals</a></li>
            <li><a href="#why">Why Klaravex</a></li>
            <li><a href="/about">About</a></li>
            <li><a href="#contact" className="nav-cta">Book a call</a></li>
          </ul>
        </div>
      </nav>

      {/* Hero */}
      <section className="hero">
        <div className="container">
          <p className="hero-eyebrow">Managed Security · Regulatory Readiness · AI Adoption</p>
          <h1>
            Enterprise-grade security<br />
            for businesses that <em>can't build</em><br />
            an internal security team.
          </h1>
          <p className="hero-sub">
            Klaravex delivers managed security, regulatory readiness, and Microsoft 365
            expertise to US SMBs — on retainer, without the senior-level salary.
          </p>
          <div className="hero-actions">
            <a href="#contact" className="btn-primary">Book a discovery call</a>
            <a href="#services" className="btn-secondary">See service tiers</a>
          </div>
          <div className="hero-tagline">
            <div className="tagline-item">
              <span className="tagline-word">Clarity.</span>
              <span className="tagline-desc">No fluff</span>
            </div>
            <div className="tagline-item">
              <span className="tagline-word">Security.</span>
              <span className="tagline-desc">Real controls</span>
            </div>
            <div className="tagline-item">
              <span className="tagline-word">Results.</span>
              <span className="tagline-desc">Measurable outcomes</span>
            </div>
          </div>
        </div>
      </section>

      {/* Verticals strip */}
      <div className="verticals-strip">
        <div className="container">
          <div className="verticals-inner">
            <span className="vertical-label">We specialise in →</span>
            {["HIPAA Security Rule", "SOC 2 Type II", "ISO 27001", "Microsoft 365 / Entra ID", "Ubiquiti UniFi", "vCISO Retainer"].map(v => (
              <span key={v} className="vertical-badge">{v}</span>
            ))}
          </div>
        </div>
      </div>

      {/* Services */}
      <section id="services">
        <div className="container">
          <p className="section-eyebrow">Service tiers</p>
          <h2 className="section-title">The right level of depth<br />for where your risk actually lives.</h2>
          <p className="section-sub">
            Most clients start with Assurance and move to Directive when regulatory
            requirements become contractual. Foundation is a delivery mechanism —
            not the reason to choose Klaravex.
          </p>
          <div className="services-grid">
            {SERVICES.map(s => (
              <div key={s.name} className={`service-card${s.featured ? " featured" : ""}`}>
                <p className="service-tier">{s.tier}</p>
                <h3 className="service-name">{s.name}</h3>
                <p className="service-price">{s.price}</p>
                <p className="service-desc">{s.desc}</p>
                <ul className="service-features">
                  {s.features.map(f => <li key={f}>{f}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Why */}
      <section id="why">
        <div className="container">
          <p className="section-eyebrow">Why Klaravex</p>
          <h2 className="section-title">Regulated-vertical depth<br />that generalist MSPs can't fake.</h2>
          <p className="section-sub">
            The market is highly fragmented. PE roll-ups are commoditising mid-tier MSPs.
            Buyer decisions in regulated verticals are trust- and credential-based,
            not per-seat price comparisons.
          </p>
          <div className="why-grid">
            {WHY.map(w => (
              <div key={w.title} className="why-item">
                <div className="why-icon">{w.icon}</div>
                <h3 className="why-title">{w.title}</h3>
                <p className="why-text">{w.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Verticals */}
      <section id="verticals">
        <div className="container">
          <p className="section-eyebrow">Target verticals</p>
          <h2 className="section-title">Built for regulated industries<br />and readiness-driven buyers.</h2>
          <p className="section-sub">
            Every vertical we serve has a regulatory driver that turns security from a nice-to-have
            into a contract condition, a licensing requirement, or a personal liability.
          </p>
          <div className="verticals-grid">
            {VERTICALS.map(v => (
              <div key={v.name} className="vertical-card">
                <span className="vertical-reg">{v.reg}</span>
                <h3 className="vertical-name">{v.name}</h3>
                <p className="vertical-pain">{v.pain}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section id="contact">
        <div className="container">
          <div className="cta-inner">
            <p className="section-eyebrow">Get started</p>
            <h2 className="section-title">Start with a 30-minute discovery call.</h2>
            <p className="section-sub">
              We'll ask about your current IT setup, any regulatory obligations you're
              navigating, and what's keeping your leadership up at night. No pitch deck.
              No obligation.
            </p>
            <div style={{ marginTop: 32, display: "flex", gap: 16, flexWrap: "wrap" }}>
              <a href="mailto:hello@klaravex.com" className="btn-primary">
                hello@klaravex.com
              </a>
              <a href="https://linkedin.com/company/klaravex" className="btn-secondary">
                LinkedIn
              </a>
            </div>
            <blockquote className="cta-pitch">
              "Klaravex handles the IT, security, and regulatory-readiness infrastructure that
              growing businesses need but can't justify hiring full-time staff to manage.
              We specialise in Microsoft 365, endpoint security, and readiness advisory —
              HIPAA, SOC 2, and ISO 27001 — for US companies between 10 and 250 people.
              Our clients get senior-level expertise on call, without the senior-level salary."
            </blockquote>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer>
        <div className="container">
          <div className="footer-inner">
            <div className="footer-brand">
              <a href="#" className="logo">KLARA<span>VEX</span></a>
              <p className="footer-tagline">
                Managed security and regulatory-readiness advisory for US SMBs.
              </p>
            </div>
            <ul className="footer-links">
              <li><a href="/services">Service tiers</a></li>
              <li><a href="#verticals">Verticals</a></li>
              <li><a href="/industries/healthcare">HIPAA readiness</a></li>
              <li><a href="/industries/legal-financial">Legal & Financial</a></li>
              <li><a href="/industries/m365-smb">M365 / Workspace / AWS</a></li>
              <li><a href="#why">Why Klaravex</a></li>
              <li><a href="/about">About</a></li>
              <li><a href="/contact">Contact</a></li>
              <li><a href="/faq">FAQ</a></li>
            </ul>
            <ul className="footer-links">
              <li><a href="/privacy">Privacy Policy</a></li>
              <li><a href="/terms">Terms of Service</a></li>
              <li><a href="/legal">Legal Notices</a></li>
              <li><a href="https://linkedin.com/company/klaravex">LinkedIn</a></li>
            </ul>
          </div>
          <div className="footer-legal">
            <span>© 2026 Klaravex LLC. Wyoming LLC. All rights reserved.</span>
            <span>Readiness and advisory services only — not certification or assessment conduct. E&O insured.</span>
          </div>
        </div>
      </footer>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
