# Klaravex — Smartlead Cold Outreach Kit

**Market:** United States (national, remote delivery)  
**Model:** B2B managed IT support, AI-powered monitoring  
**Target segment:** SMBs 10–150 employees with no dedicated internal IT  

---

## 1. ICP Definition

### Who we're targeting

| Dimension | Target |
|-----------|--------|
| Company size | 10–150 employees |
| IT setup | No internal IT staff — "we figure it out" or one generalist person |
| Geography | United States, all states |
| Budget signal | $2M–$30M revenue range |
| Decision maker | CEO, COO, Founder, President, Operations Director, Office Manager |

### Best-performing verticals (ranked)

1. **Accounting / CPA firms** — tech-dependent, regulated, no IT budget for staff
2. **Law firms** (solo to 30 attorneys) — confidentiality risk, downtime = billable hour loss
3. **Dental and medical practices** — HIPAA exposure, clinical software dependency
4. **Insurance agencies** — data-heavy, often old infrastructure
5. **Financial advisory / wealth management** — SEC/FINRA compliance awareness
6. **Architecture and engineering firms** — CAD/large file workflows, critical uptime
7. **Real estate brokerages** — distributed teams, heavy SaaS dependency
8. **Marketing/PR agencies** — fast-moving, client deliverables, no patience for IT issues
9. **Nonprofit organizations** — underinvested in IT, high risk exposure

### Exclusions

- Company name contains: "technology", "software", "IT", "tech", "systems", "solutions", "digital"
- Already listed as an MSP or technology company
- Enterprise (500+ employees)
- Consumer-facing retail / restaurants / hospitality

---

## 2. Apollo Search Parameters

### Search A — Professional services generalist

```
Job Titles (include any):
  CEO, COO, Founder, Co-Founder, President, Managing Director,
  Operations Director, Director of Operations, Office Manager,
  Principal, Managing Partner

Company Headcount:
  10–150

Location:
  United States

Industry (include any):
  Accounting, Law Practice, Legal Services, Financial Services,
  Insurance, Real Estate, Architecture & Planning,
  Marketing & Advertising, Management Consulting,
  Nonprofit Organization Management

Keywords (company — exclude):
  technology, software, IT, tech, systems, solutions

Technologies (optional boost):
  Microsoft 365, Google Workspace, QuickBooks, Salesforce
  (companies using these are SMB and tech-dependent)
```

**Estimated pool size:** 200K–500K contacts in Apollo

### Search B — Healthcare / HIPAA angle

```
Job Titles:
  Practice Administrator, Office Manager, CEO, Founder, President,
  Medical Director (smaller practices)

Company Headcount:
  5–100

Industry:
  Medical Practice, Hospital & Health Care, Mental Health Care,
  Physical Therapy, Veterinary

Location:
  United States
```

---

## 3. Campaign Structure in Smartlead

### Recommended campaigns

| Campaign | Angle | Sequence length | Target list |
|----------|-------|-----------------|-------------|
| KLX-01 | IT outage risk — general SMB | 4 steps | Search A (CEO/Founder focus) |
| KLX-02 | HIPAA / data risk | 4 steps | Search B (healthcare) |
| KLX-03 | "Replace your IT guy" | 4 steps | Search A (companies where existing MSP is mentioned) |

Start with **KLX-01** only. Add KLX-02 after 2 weeks of data.

### Sending settings

- **Schedule:** Monday–Thursday, 8am–5pm recipient local time
- **Per-mailbox daily limit:** 30–40 emails/day after warmup (50 max)
- **Warmup period:** 3–4 weeks minimum for any new @klaravex.com sending mailbox
- **Tracking:** Turn off link tracking for Email 1 (improves deliverability)
- **Reply detection:** On — pause sequence on any reply

### Sending mailbox setup

Use subdomain or variation of klaravex.com for outreach mailboxes to protect the main domain reputation:

```
outreach@mail.klaravex.com   — or —
firstname@klaravex.com (e.g. alex@klaravex.com)
```

Ensure SPF, DKIM, and DMARC are configured on the sending domain before warming up. Smartlead's warmup feature handles the rest.

---

## 4. Email Sequences

### Campaign KLX-01 — General SMB, IT outage risk

---

**Email 1 — Day 1**

Subject A: `quick question about your IT`  
Subject B: `who handles IT at {{company_name}}?`  
Subject C: `IT question for {{first_name}}`

```
Hi {{first_name}},

When something breaks at {{company_name}} — a laptop dies, email stops working, the network goes down — who handles it?

If the honest answer is "we figure it out" or "we have a guy we call," you're one bad week from serious downtime.

Klaravex provides AI-backed IT support for US companies your size. Proactive monitoring, same-day response, and a real person who knows your setup — without hiring an IT employee.

Worth a 15-minute call this week?

{{sender_name}}
```

---

**Email 2 — Day 4**

Subject: `re: quick question` *(reply thread)*

```
Hi {{first_name}},

Circling back in case my last note got buried.

One thing we do differently from typical IT firms: our monitoring flags problems before you notice them. Instead of you calling us when something breaks, we alert you — or just fix it in the background.

For a company the size of {{company_name}}, that usually costs less than what one day of downtime costs you.

Curious if that's the kind of thing on your radar right now?

{{sender_name}}
```

---

**Email 3 — Day 9**

Subject: *(no subject)*

```
{{first_name}} — keeping this short.

Are you currently paying someone to keep your IT running, or handling it in-house?

Either way, happy to compare notes. Takes 15 minutes.

{{sender_name}}
```

---

**Email 4 — Day 18 (breakup)**

Subject: `closing the loop`

```
Hi {{first_name}},

I've sent a couple of notes — won't keep following up after this.

If IT ever becomes a problem at {{company_name}} and you want a second opinion, you can book a call here: [Calendly link]

Good luck with everything.

{{sender_name}}
```

---

### Campaign KLX-02 — Healthcare / HIPAA angle

---

**Email 1 — Day 1**

Subject A: `HIPAA and your IT — quick question`  
Subject B: `question about your practice's IT`

```
Hi {{first_name}},

Most practices your size handle HIPAA-related IT requirements with a patchwork of solutions — and most are one breach or audit away from a serious problem.

Klaravex supports medical and dental practices with managed IT that keeps ePHI protected, systems running, and staff supported — without the cost of in-house IT.

Is this something worth a 15-minute conversation?

{{sender_name}}
```

---

**Email 2 — Day 4**

Subject: `re: your practice's IT`

```
Hi {{first_name}},

Wanted to follow up in case my last note missed you.

Specifically: if your practice uses any EHR, billing software, or cloud storage for patient records, you're carrying IT risk that most practice owners don't think about until something goes wrong.

We've helped practices in your situation tighten that up — and usually find coverage gaps in the first audit.

Open to a short call?

{{sender_name}}
```

---

**Email 3 — Day 9**

Subject: *(no subject)*

```
{{first_name}},

Last email on this. One question:

Is your current IT setup something you're confident in, or something you've been meaning to revisit?

If the latter — we should talk.

{{sender_name}}
```

---

**Email 4 — Day 18**

Subject: `closing the loop`

```
Hi {{first_name}},

Won't follow up after this.

If you ever want a quick review of your IT risk exposure at {{company_name}}, you can book directly here: [Calendly link]

{{sender_name}}
```

---

## 5. Personalization Variables (Smartlead tokens)

| Token | Source | Notes |
|-------|--------|-------|
| `{{first_name}}` | Apollo contact | Always verify — don't let "N/A" slip through |
| `{{company_name}}` | Apollo company | Clean up "LLC", "Inc" suffixes for better readability |
| `{{sender_name}}` | Smartlead sender | Use real first name only |
| `{{industry_line}}` | Custom column | Optional: "For a law firm your size" / "For a medical practice like yours" |

**First-line personalization (add to Email 1 when doing high-touch sends):**

```
Saw you've been at {{company_name}} for a while — wanted to reach out directly.
```
or
```
Came across {{company_name}} while looking at [industry] firms in [city].
```

---

## 6. Lead Sourcing Workflow

1. Pull 200–300 contacts from Apollo using **Search A** (professional services)
2. Verify emails: use Apollo's verify feature or NeverBounce before import
3. Clean `company_name`: remove legal suffixes (LLC, Inc, Corp) for natural tone
4. Import to Smartlead → Campaign KLX-01
5. After 3 weeks: review open rate / reply rate by vertical
6. Double down on top-performing verticals; pause low-performers
7. Pull 100 healthcare contacts → run Campaign KLX-02 in parallel

**Target metrics (first 60 days):**

| Metric | Benchmark |
|--------|-----------|
| Open rate | 45–60% |
| Reply rate | 3–6% |
| Positive reply rate | 0.5–1.5% |
| Booked calls from 1,000 contacts | 5–15 |

---

## 7. Sender Setup Checklist

- [ ] New sending mailbox created: `[name]@klaravex.com` or `[name]@mail.klaravex.com`
- [ ] SPF record added for sending domain
- [ ] DKIM configured and verified
- [ ] DMARC policy set (at minimum `p=none` with reporting)
- [ ] Mailbox added to Smartlead
- [ ] Warmup enabled — minimum 3 weeks before first send
- [ ] Calendly link ready (book a call — 15 min discovery)
- [ ] First Apollo export cleaned and imported
- [ ] Link tracking disabled for Email 1
- [ ] Unsubscribe handling configured

---

## 8. Next Steps

1. **This week:** Set up sending mailbox, enable warmup
2. **Week 2–3:** Pull Apollo list, clean and import; warmup continues
3. **Week 4:** Launch KLX-01 at 20 sends/day; ramp to 40 by end of week
4. **Week 6:** Review data, optimize subjects, add KLX-02
5. **Week 8:** First performance review — identify best-converting verticals
