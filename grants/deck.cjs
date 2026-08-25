const pptxgen = require('/Users/als/.npm-global/lib/node_modules/pptxgenjs');
const p = new pptxgen();
p.defineLayout({ name: 'W', width: 13.33, height: 7.5 });
p.layout = 'W';

// Palette
const BG = '06080E', PANEL = '0E1220', PANEL2 = '111827', INK = 'FFFFFF',
      MUT = '94A3B8', IND = '6366F1', LIL = '818CF8', VIO = '7C3AED', OK = '34D399';
const HEAD = 'Trebuchet MS', BODY = 'Calibri';

function base(s){ s.background = { color: BG }; }
function eyebrow(s, txt, x=0.7, y=0.55){
  s.addText(txt.toUpperCase(), { x, y, w: 8, h: 0.3, fontFace: BODY, fontSize: 11, bold: true, color: LIL, charSpacing: 3 });
}
function title(s, txt, x=0.7, y=0.92, w=11.9, size=34){
  s.addText(txt, { x, y, w, h: 0.95, fontFace: HEAD, fontSize: size, bold: true, color: INK });
}
function foot(s, n){
  s.addText('KLARAVEX — Confidential', { x: 0.7, y: 7.05, w: 4, h: 0.3, fontFace: BODY, fontSize: 9, color: '475569' });
  s.addText(String(n), { x: 12.4, y: 7.05, w: 0.5, h: 0.3, fontFace: BODY, fontSize: 9, color: '475569', align: 'right' });
}
function statCard(s, x, y, w, h, big, label, sub, accent=IND){
  s.addShape('roundRect', { x, y, w, h, rectRadius: 0.08, fill: { color: PANEL }, line: { color: '1E293B', width: 1 } });
  s.addText(big, { x: x+0.05, y: y+0.18, w: w-0.1, h: h*0.42, fontFace: HEAD, fontSize: 40, bold: true, color: accent, align: 'center' });
  s.addText(label, { x: x+0.15, y: y+h*0.52, w: w-0.3, h: 0.32, fontFace: BODY, fontSize: 13, bold: true, color: INK, align: 'center' });
  s.addText(sub, { x: x+0.15, y: y+h*0.52+0.34, w: w-0.3, h: h-(h*0.52+0.45), fontFace: BODY, fontSize: 10.5, color: MUT, align: 'center' });
}
function bulletRows(s, items, x, y, w, rowH=0.92, dotColor=IND){
  items.forEach((it, i) => {
    const yy = y + i*rowH;
    s.addShape('ellipse', { x, y: yy+0.06, w: 0.34, h: 0.34, fill: { color: dotColor } });
    s.addText(it.n || String(i+1), { x, y: yy+0.06, w: 0.34, h: 0.34, fontFace: HEAD, fontSize: 13, bold: true, color: 'FFFFFF', align: 'center', valign: 'middle' });
    s.addText(it.h, { x: x+0.5, y: yy, w: w-0.5, h: 0.32, fontFace: BODY, fontSize: 15, bold: true, color: INK });
    s.addText(it.b, { x: x+0.5, y: yy+0.3, w: w-0.5, h: rowH-0.32, fontFace: BODY, fontSize: 12, color: MUT });
  });
}

// ---------- 1. TITLE ----------
let s = p.addSlide(); base(s);
s.addShape('rect', { x: 8.9, y: 0, w: 4.43, h: 7.5, fill: { color: PANEL } });
s.addShape('ellipse', { x: 9.6, y: 1.5, w: 4.6, h: 4.6, fill: { color: '15173A' }, line: { type: 'none' } });
s.addShape('ellipse', { x: 10.6, y: 2.5, w: 2.6, h: 2.6, fill: { color: '1E2152' }, line: { type: 'none' } });
s.addShape('roundRect', { x: 0.7, y: 1.45, w: 0.62, h: 0.62, rectRadius: 0.12, fill: { color: IND } });
s.addText('K', { x: 0.7, y: 1.45, w: 0.62, h: 0.62, fontFace: HEAD, fontSize: 26, bold: true, color: 'FFFFFF', align: 'center', valign: 'middle' });
s.addText('KLARAVEX', { x: 1.45, y: 1.5, w: 5, h: 0.55, fontFace: HEAD, fontSize: 26, bold: true, color: INK, charSpacing: 4 });
s.addText('The AI-native managed IT & security provider.', { x: 0.7, y: 2.7, w: 7.6, h: 1.6, fontFace: HEAD, fontSize: 38, bold: true, color: INK });
s.addText([
  { text: '78 production AI agents resolve first-line IT. ', options: { color: LIL, bold: true } },
  { text: 'One senior engineer owns every outcome.', options: { color: MUT } },
], { x: 0.7, y: 4.35, w: 7.4, h: 0.8, fontFace: BODY, fontSize: 17 });
s.addText('Anthony Stewart, Founder  ·  Los Angeles, CA  ·  klaravex.com  ·  June 2026', { x: 0.7, y: 6.35, w: 8, h: 0.35, fontFace: BODY, fontSize: 12, color: MUT });

// ---------- 2. PROBLEM ----------
s = p.addSlide(); base(s); eyebrow(s, 'Problem'); title(s, 'Small businesses get the worst of IT.'); foot(s, 2);
bulletRows(s, [
  { h: 'Enterprise threats, consumer budgets', b: 'Ransomware, compliance mandates, and cyber-insurance requirements hit 10–50-person companies that have no security posture at all.' },
  { h: 'Traditional MSPs price them out', b: 'Managed-services economics require human headcount, so providers chase bigger clients — small businesses become an afterthought.' },
  { h: 'The result: nobody owns the outcome', b: 'SMBs bounce between break-fix vendors, unanswered tickets, and DIY — until an incident forces a panic spend.' },
], 0.7, 2.1, 7.0, 1.35);
statCard(s, 8.3, 2.1, 4.3, 1.85, '10–50', 'employee companies', 'the under-served core of the market', LIL);
statCard(s, 8.3, 4.15, 4.3, 1.85, '$0', 'security budget', 'typical posture before their first incident', 'F87171');

// ---------- 3. SOLUTION ----------
s = p.addSlide(); base(s); eyebrow(s, 'Solution'); title(s, 'AI does first-line. A senior engineer owns the rest.'); foot(s, 3);
const cols = [
  { h: 'Resolve', t: '78 production AI agents handle tier-1/2 support, triage, scheduling, and compliance workflows around the clock — always AI-labeled, never pretending to be human.' },
  { h: 'Escalate', t: 'Human-in-the-loop gates on higher-risk actions. Complex issues route to a senior engineer with full context — no re-explaining, no ticket purgatory.' },
  { h: 'Own', t: 'Every client gets a named senior engineer accountable for outcomes, a live portal, and documented resolutions. Accountability is the product.' },
];
cols.forEach((c, i) => {
  const x = 0.7 + i*4.12;
  s.addShape('roundRect', { x, y: 2.15, w: 3.82, h: 3.6, rectRadius: 0.1, fill: { color: PANEL }, line: { color: '1E293B', width: 1 } });
  s.addShape('ellipse', { x: x+0.3, y: 2.45, w: 0.55, h: 0.55, fill: { color: i===2 ? VIO : IND } });
  s.addText(String(i+1), { x: x+0.3, y: 2.45, w: 0.55, h: 0.55, fontFace: HEAD, fontSize: 18, bold: true, color: 'FFFFFF', align: 'center', valign: 'middle' });
  s.addText(c.h, { x: x+0.3, y: 3.2, w: 3.2, h: 0.4, fontFace: HEAD, fontSize: 19, bold: true, color: INK });
  s.addText(c.t, { x: x+0.3, y: 3.65, w: 3.25, h: 1.9, fontFace: BODY, fontSize: 12, color: MUT });
});
s.addText('“89% of IT issues resolved before you finish your coffee.”', { x: 0.7, y: 6.1, w: 11.9, h: 0.5, fontFace: BODY, fontSize: 15, italic: true, color: LIL, align: 'center' });

// ---------- 4. WHY NOW ----------
s = p.addSlide(); base(s); eyebrow(s, 'Why now'); title(s, 'The AI-native window is open — briefly.'); foot(s, 4);
bulletRows(s, [
  { h: 'Agents crossed the reliability threshold', b: 'In the last 18 months, frontier-model agents became dependable enough for real ticket resolution — not chatbots, actual fixes.' },
  { h: 'Incumbents cannot retrofit the cost structure', b: 'Traditional MSPs carry human-headcount economics. An AI-first operator sets a price floor they cannot follow.' },
  { h: 'Compliance demand is exploding downstream', b: 'Cyber-insurance questionnaires, HIPAA, SOC 2 — requirements now reach companies far too small for traditional providers.' },
], 0.7, 2.2, 7.2, 1.4);
statCard(s, 8.3, 2.3, 4.3, 3.3, '~5×', 'cost advantage', 'one engineer + agents vs. a ten-person MSP delivering the same client base', OK);

// ---------- 5. PRODUCT ----------
s = p.addSlide(); base(s); eyebrow(s, 'Product'); title(s, 'A production platform, not a prototype.'); foot(s, 5);
const feats = [
  ['78 AI agents', 'support resolution, lead qualification, scheduling, compliance — in production today'],
  ['Client portal', 'magic-link auth, live ticket status, named engineer, documented resolutions'],
  ['Knowledge-base RAG', 'semantic search grounded answers; every fix becomes searchable institutional memory'],
  ['Billing & ops', '50 Stripe products live; self-healing infrastructure with watchdog monitoring'],
];
feats.forEach((f, i) => {
  const x = 0.7 + (i%2)*6.0, y = 2.2 + Math.floor(i/2)*1.95;
  s.addShape('roundRect', { x, y, w: 5.7, h: 1.7, rectRadius: 0.1, fill: { color: PANEL }, line: { color: '1E293B', width: 1 } });
  s.addShape('rect', { x, y, w: 0.09, h: 1.7, fill: { color: IND } });
  s.addText(f[0], { x: x+0.32, y: y+0.22, w: 5.2, h: 0.4, fontFace: HEAD, fontSize: 17, bold: true, color: INK });
  s.addText(f[1], { x: x+0.32, y: y+0.66, w: 5.2, h: 0.9, fontFace: BODY, fontSize: 12.5, color: MUT });
});
s.addText('Stack: Claude API · FastAPI · Celery · MCP · RAG · Azure + Hetzner', { x: 0.7, y: 6.25, w: 11.9, h: 0.4, fontFace: BODY, fontSize: 12, color: '64748B', align: 'center' });

// ---------- 6. MARKET ----------
s = p.addSlide(); base(s); eyebrow(s, 'Market'); title(s, 'A huge market the incumbents structurally ignore.'); foot(s, 6);
statCard(s, 0.7, 2.2, 3.9, 2.6, '$300B+', 'global managed services', 'growing ~12% annually', IND);
statCard(s, 4.75, 2.2, 3.9, 2.6, '33M', 'US small businesses', 'most with no dedicated IT', LIL);
statCard(s, 8.8, 2.2, 3.9, 2.6, '2', 'revenue engines', 'B2B recurring plans + consumer self-serve sessions', VIO);
s.addText([
  { text: 'Beachhead: ', options: { bold: true, color: INK } },
  { text: '10–50-seat US businesses with compliance pressure (healthcare, legal, finance) — bought per-seat, landed through a free assessment funnel, expanded through supplier-diversity procurement (NGLCC / MBE certified).', options: { color: MUT } },
], { x: 0.7, y: 5.3, w: 11.9, h: 0.9, fontFace: BODY, fontSize: 14 });

// ---------- 7. BUSINESS MODEL ----------
s = p.addSlide(); base(s); eyebrow(s, 'Business model'); title(s, 'Recurring per-seat revenue, near-zero marginal cost.'); foot(s, 7);
const tiers = [
  ['B2B Managed Plans', 'Foundation · Assurance · Directive', 'per-seat monthly recurring; the core engine'],
  ['Fixed-fee Projects', 'audits, M365/Azure, compliance readiness', 'high-margin entry points that convert to plans'],
  ['Consumer Sessions', 'tech help, security, job-hunt kit', 'Stripe self-checkout; zero sales motion'],
];
tiers.forEach((t, i) => {
  const x = 0.7 + i*4.12;
  s.addShape('roundRect', { x, y: 2.2, w: 3.82, h: 2.5, rectRadius: 0.1, fill: { color: i===0 ? '15173A' : PANEL }, line: { color: i===0 ? IND : '1E293B', width: i===0 ? 1.5 : 1 } });
  s.addText(t[0], { x: x+0.28, y: 2.45, w: 3.3, h: 0.4, fontFace: HEAD, fontSize: 16.5, bold: true, color: i===0 ? LIL : INK });
  s.addText(t[1], { x: x+0.28, y: 2.92, w: 3.3, h: 0.55, fontFace: BODY, fontSize: 12.5, bold: true, color: INK });
  s.addText(t[2], { x: x+0.28, y: 3.5, w: 3.3, h: 1.0, fontFace: BODY, fontSize: 12, color: MUT });
});
s.addText([
  { text: 'The unit-economics engine: ', options: { bold: true, color: INK } },
  { text: 'AI deflection resolves routine tickets at near-zero marginal cost. Each new seat adds revenue without adding headcount — the margin curve bends the opposite way from a traditional MSP.', options: { color: MUT } },
], { x: 0.7, y: 5.15, w: 11.9, h: 0.95, fontFace: BODY, fontSize: 14 });

// ---------- 8. TRACTION ----------
s = p.addSlide(); base(s); eyebrow(s, 'Traction'); title(s, 'Built and live — launching revenue now.'); foot(s, 8);
statCard(s, 0.7, 2.2, 2.85, 2.3, '78', 'AI agents', 'in production', IND);
statCard(s, 3.72, 2.2, 2.85, 2.3, '50', 'Stripe SKUs', 'payment links live', LIL);
statCard(s, 6.74, 2.2, 2.85, 2.3, '4', 'web properties', 'US + EU, B2B + consumer', VIO);
statCard(s, 9.76, 2.2, 2.85, 2.3, '$0', 'raised', '100% bootstrapped', OK);
s.addText([
  { text: 'Status (June 2026): ', options: { bold: true, color: INK } },
  { text: 'pre-revenue; platform, billing, portal, and insurance (cyber + E&O) all in place; first marketing campaign launching now; NGLCC LGBTBE and MBE certifications in progress.', options: { color: MUT } },
], { x: 0.7, y: 4.95, w: 11.9, h: 0.8, fontFace: BODY, fontSize: 14 });
s.addText('Everything on this slide was designed, built, and shipped by one founder.', { x: 0.7, y: 5.9, w: 11.9, h: 0.45, fontFace: BODY, fontSize: 14, italic: true, color: LIL });

// ---------- 9. GTM ----------
s = p.addSlide(); base(s); eyebrow(s, 'Go-to-market'); title(s, 'Land with a free assessment. Expand per seat.'); foot(s, 9);
const steps = [
  ['Free IT assessment', 'red/yellow/green risk scorecard — a concrete artifact, not a sales call'],
  ['Convert to managed plan', 'findings map directly to per-seat tiers; the scorecard sells the fix'],
  ['Expand & refer', 'portal visibility + quarterly reviews drive seat growth and referrals'],
];
steps.forEach((st, i) => {
  const x = 0.7 + i*4.12;
  s.addShape('roundRect', { x, y: 2.2, w: 3.7, h: 2.2, rectRadius: 0.1, fill: { color: PANEL }, line: { color: '1E293B', width: 1 } });
  s.addText(String(i+1), { x: x+0.28, y: 2.4, w: 0.8, h: 0.7, fontFace: HEAD, fontSize: 30, bold: true, color: IND });
  s.addText(st[0], { x: x+0.28, y: 3.05, w: 3.2, h: 0.4, fontFace: HEAD, fontSize: 15.5, bold: true, color: INK });
  s.addText(st[1], { x: x+0.28, y: 3.5, w: 3.2, h: 0.8, fontFace: BODY, fontSize: 11.5, color: MUT });
  if (i < 2) s.addText('→', { x: x+3.74, y: 3.0, w: 0.4, h: 0.5, fontFace: HEAD, fontSize: 22, bold: true, color: '475569' });
});
s.addText([
  { text: 'Channels: ', options: { bold: true, color: INK } },
  { text: 'SEO/AEO content engine (knowledge base live) · partner referrals (accountants, cyber-insurance brokers) · supplier-diversity procurement via NGLCC + MBE certification · consumer self-serve at personal.klaravex.com.', options: { color: MUT } },
], { x: 0.7, y: 4.95, w: 11.9, h: 1.0, fontFace: BODY, fontSize: 14 });

// ---------- 10. FOUNDER ----------
s = p.addSlide(); base(s); eyebrow(s, 'Founder'); title(s, 'Anthony Stewart — builder and operator.'); foot(s, 10);
s.addShape('roundRect', { x: 0.7, y: 2.2, w: 5.6, h: 3.9, rectRadius: 0.1, fill: { color: PANEL }, line: { color: '1E293B', width: 1 } });
s.addShape('ellipse', { x: 0.95, y: 2.5, w: 1.0, h: 1.0, fill: { color: IND } });
s.addText('AS', { x: 0.95, y: 2.5, w: 1.0, h: 1.0, fontFace: HEAD, fontSize: 24, bold: true, color: 'FFFFFF', align: 'center', valign: 'middle' });
s.addText('Anthony Stewart', { x: 2.1, y: 2.6, w: 4, h: 0.4, fontFace: HEAD, fontSize: 18, bold: true, color: INK });
s.addText('Founder & Senior Engineer · Los Angeles', { x: 2.1, y: 3.0, w: 4, h: 0.35, fontFace: BODY, fontSize: 12, color: MUT });
s.addText([
  { text: '15+ years enterprise IT and security', options: { bullet: { code: '2022' }, color: INK, breakLine: true } },
  { text: 'Ran an independent consultancy in Berlin serving SMBs', options: { bullet: { code: '2022' }, color: INK, breakLine: true } },
  { text: 'Personally engineered the 78-agent platform end-to-end', options: { bullet: { code: '2022' }, color: INK, breakLine: true } },
  { text: 'Black- and LGBTQ+-owned (100%) — NGLCC & MBE certifications in progress', options: { bullet: { code: '2022' }, color: INK } },
], { x: 0.98, y: 3.75, w: 5.1, h: 2.2, fontFace: BODY, fontSize: 12.5, paraSpaceAfter: 8, valign: 'top' });
s.addShape('roundRect', { x: 6.7, y: 2.2, w: 5.95, h: 3.9, rectRadius: 0.1, fill: { color: '15173A' }, line: { color: IND, width: 1 } });
s.addText('Why this founder wins this market', { x: 7.0, y: 2.5, w: 5.4, h: 0.4, fontFace: HEAD, fontSize: 15, bold: true, color: LIL });
s.addText('There is no gap between “the technical founder” and “the delivery team.” The person who built the agents is the senior engineer who owns client outcomes — which is exactly the accountability promise the product makes. Bootstrapped discipline keeps costs near zero until revenue scales.', { x: 7.0, y: 3.05, w: 5.4, h: 2.9, fontFace: BODY, fontSize: 13.5, color: 'CBD5E1' });

// ---------- 11. ASK ----------
s = p.addSlide(); base(s); eyebrow(s, 'The ask'); title(s, 'Next 12 months: prove the model in public.'); foot(s, 11);
bulletRows(s, [
  { h: '10 B2B clients + 100 consumer sessions', b: 'recurring revenue covering all operating costs by month twelve' },
  { h: 'NGLCC LGBTBE + MBE certified', b: 'first two corporate supplier-diversity registrations submitted' },
  { h: 'Published AI-deflection economics', b: '≥80% AI resolution rate and cost-per-ticket benchmarks vs. traditional MSPs' },
], 0.7, 2.2, 7.0, 1.25);
s.addShape('roundRect', { x: 8.3, y: 2.2, w: 4.35, h: 3.5, rectRadius: 0.1, fill: { color: '15173A' }, line: { color: IND, width: 1.5 } });
s.addText('What we’re seeking', { x: 8.6, y: 2.5, w: 3.8, h: 0.4, fontFace: HEAD, fontSize: 15, bold: true, color: LIL });
s.addText('Accelerator partnership, mentorship, and growth capital conversations — plus customers and supplier-diversity channel introductions. Capital accelerates acquisition and certifications; the platform is already paid for.', { x: 8.6, y: 3.0, w: 3.8, h: 2.5, fontFace: BODY, fontSize: 12.5, color: 'CBD5E1', valign: 'top' });
s.addText('Anthony Stewart · astewart@klaravex.com · klaravex.com', { x: 0.7, y: 6.35, w: 11.9, h: 0.4, fontFace: BODY, fontSize: 13, color: MUT, align: 'center' });

p.writeFile({ fileName: '/Users/als/Documents/Claude/Projects/Active/klaravex/grants/Klaravex-Pitch-Deck.pptx' })
  .then(() => console.log('WRITTEN'));
