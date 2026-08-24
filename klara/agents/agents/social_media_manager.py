"""
app/agents/social_media_manager.py
────────────────────────────────────
SocialMediaManagerAgent — P3 outbound publishing.

Generates social media content bundles for up to 8 platforms, each with:
  - 3 hook variants
  - Final post copy (platform-native format)
  - First-hour engagement plan
  - Short-video briefs for Instagram / TikTok
  - Reddit risk notes

Platform coverage (canonical keys — no underscores):
  linkedincompany   LinkedIn Company Page  (Klaravex)
  linkedinpersonal  LinkedIn Personal      (Klaravex brand voice)
  xing              XING                   (DACH secondary surface)
  twitter           X / Twitter Brand      (@Klaravex)
  facebook          Facebook Business Page (Klaravex)
  instagram         Instagram              (visual-first, Reel + Carousel)
  tiktok            TikTok                 (short-form video)
  reddit            Reddit                 (community-native discussion)

Permission: P3 — external content publishing. Always requires approval.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.lead import Lead

logger = structlog.get_logger(__name__)


# ── Platform registry ─────────────────────────────────────────────────────────

PLATFORMS_ALL = [
    "linkedincompany",
    "linkedinpersonal",
    "xing",
    "twitter",
    "facebook",
    "instagram",
    "tiktok",
    "reddit",
]

# Old underscore-style names used by the beat task and social_publisher.
# Normalised to canonical (no-underscore) names on the way in.
_ALIAS_TO_CANONICAL: dict[str, str] = {
    "linkedin_company":  "linkedincompany",
    "linkedin_personal": "linkedinpersonal",
}

# Reverse map — publisher / audit trail still expects old-style keys.
_CANONICAL_TO_PUBLISHER: dict[str, str] = {
    "linkedincompany":  "linkedin_company",
    "linkedinpersonal": "linkedin_personal",
}

PLATFORM_DEFAULTS: dict[str, dict[str, Any]] = {
    "linkedincompany":  {"length": "150-220 words",              "format": "authority post",                  "hashtags": "3-5 specific hashtags"},
    "linkedinpersonal": {"length": "180-260 words",              "format": "practitioner post",               "hashtags": "3-5 specific hashtags"},
    "xing":             {"length": "130-200 words",              "format": "German practical post",           "hashtags": "3-5 German hashtags"},
    "twitter":          {"length": "2-post thread",              "format": "plain-ASCII thread",              "hashtags": "2-3 total hashtags"},
    "facebook":         {"length": "100-160 words",              "format": "plain-English SMB explainer",     "hashtags": "2-3 casual hashtags"},
    "instagram":        {"length": "caption + Reel/Carousel",    "format": "visual-first multi-format brief", "hashtags": "niche + branded mix"},
    "tiktok":           {"length": "15-45 second script",        "format": "vertical short-form video",       "hashtags": "5-8 platform-native hashtags"},
    "reddit":           {"length": "discussion starter",         "format": "community-native text post",      "hashtags": "none"},
}

VOICE_GUARDRAILS = [
    "No hypey AI language.",
    "No invented statistics or fake case studies.",
    "Be specific, operational, and practitioner-led.",
    "Respect platform culture instead of reusing one generic draft.",
]

BEST_PRACTICES: dict[str, list[str]] = {
    "linkedin": [
        "Generate hook variants first.",
        "Lead with a defensible point of view.",
        "Optimise for dwell time and comment quality.",
        "Include a first-hour engagement plan.",
    ],
    "instagram": [
        "Support feed, story, and reel angles.",
        "Keep visual direction specific.",
        "Include save/share-oriented CTA.",
    ],
    "tiktok": [
        "Hook in the first 3 seconds.",
        "Use a pattern interrupt and clear story arc.",
        "Optimise for completion rate and rewatch potential.",
    ],
    "reddit": [
        "Be useful and discussion-led.",
        "Avoid obvious promotion.",
        "Write like a participant, not a brand deck.",
    ],
    "video": [
        "Every cut needs a reason.",
        "Voice clarity is priority number one.",
        "Subtitles must be readable and manually reviewed.",
        "Export per platform with safe zones in mind.",
    ],
}


# ── Klaravex approved real stats ──────────────────────────────────────────────
#
# Single source of truth for stats the social-media prompts may quote in
# generated drafts. Edit this dict to update what the LLM is allowed to
# claim. Keeps the agent from inventing plausible-but-wrong numbers.
#
# Update cadence: the brand-level stats (pricing, AI rate) are stable;
# operational counters (tickets per month) should be refreshed monthly
# by whoever runs the social rotation.

KLARAVEX_REAL_STATS: dict[str, str] = {
    # Pricing (per-user / month, EUR)
    "foundation_price": "€75/user/month",
    "assurance_price":  "€125/user/month",
    "directive_price":  "€200/user/month",

    # Operational mix
    "ai_resolution_rate":       "89%",
    "human_oversight_rate":     "11%",
    "median_human_first_touch": "4 minutes 22 seconds",
    "industry_avg_resolution":  "14 hours",

    # Verticals served
    "primary_verticals": "kleine Kanzleien, Steuerkanzleien, Arzt- und Zahnarztpraxen, kleine Beratungsunternehmen",
    "firm_size_range":   "10 bis 50 Mitarbeiter",

    # Contract terms
    "contract_length":   "monatlich kuendbar, keine Mindestlaufzeit",
    "switch_time":       "5 Werktage, keine Ausfallzeit",

    # Compliance / certifications
    "compliance_focus": "DSGVO-konformes Managed IT; ISO 27001 Beratung; BSI IT-Grundschutz orientiert",
}


def _stats_block() -> str:
    """Render KLARAVEX_REAL_STATS into a prompt-injectable block."""
    lines = ["APPROVED REAL STATS — use these verbatim; do NOT invent additional metrics:"]
    for k, v in KLARAVEX_REAL_STATS.items():
        lines.append(f"  - {k.replace('_', ' ')}: {v}")
    return "\n".join(lines)


# ── Per-platform prompts ──────────────────────────────────────────────────────
#
# Each prompt produces structured output with clearly labelled sections
# so _parse_draft() can extract hooks, body, engagement plan, etc.

PLATFORM_PROMPTS: dict[str, str] = {

    "linkedincompany": """\
You are drafting a LinkedIn company page post for Klaravex.
Audience: managing partners, ops leads, and IT decision-makers at German
and EU small professional services firms (10-50 employees) — law,
accounting, medical, dental, consulting.
Tone: corporate first-person plural, direct, anti-hype, proof-driven.

BANNED in post body or hashtags:
- Personal names (no founder identity)
- "Klara AI" or any internal codename
- First-person singular ("I", "me", "my") — Klaravex speaks as "we"
- Infra vendor names (Hetzner, Azure, Vapi, Atera, Smartlead, Apollo)
- "Thought leadership" tone or industry-news commentary
- Vague abstractions ("digital transformation", "synergies", "leverage")

REQUIRED in every post:
- "We" / "Klaravex" as subject
- At least one specific number (89%, €75/month, 4m 22s, etc.)
- A named vertical where it fits (small law firms, medical practices,
  accounting offices, professional services)
- CTA: klaravex.de on its own final line

Requirements:
- 3 hook variants (curiosity gap / bold claim / proof-stat opener)
- Final post (150-220 words)
- 3 comment prompts for first-hour engagement
- 3-5 hashtags (specific beats generic)

Topic: {topic}

Output exactly these labelled sections (no extra text outside them):
HOOK_VARIANTS:
[Hook 1: ...]
[Hook 2: ...]
[Hook 3: ...]

FINAL_POST:
[full post text including CTA + hashtags]

ENGAGEMENT_PLAN:
[3 comment prompt lines]
""",

    "linkedinpersonal": """\
You are drafting a LinkedIn post for Klaravex. This is the same brand
voice as the company page — Klaravex never speaks as an individual.
Audience: technical peers, German and EU small-firm partners and ops leads,
prospective clients at law / accounting / medical / consulting firms
(10-50 employees).
Tone: corporate first-person plural — direct, opinionated, anti-hype.
Never personal-brand. Never founder-voiced. Klaravex speaks as Klaravex.

BANNED in body or hashtags:
- Personal names (no founder identity, no biography)
- "Klara AI" or any internal codename
- First-person singular ("I", "me", "my") — Klaravex speaks as "we"
- Infra vendor names (Hetzner, Azure, Vapi, Atera, Smartlead, Apollo)
- "Thought leadership" or topical commentary on industry news
- Vague abstractions ("digital transformation", "leverage", "synergies")

REQUIRED in every post:
- "We" / "Klaravex" as subject
- At least one specific number (89%, €75/month, 4m 22s, etc.)
- Named verticals where relevant (small law firms, medical practices,
  accounting offices, professional services)
- CTA: klaravex.de or personal.klaravex.de on its own final line

Requirements:
- 3 hook variants (curiosity gap / bold claim / proof-stat opener)
- Final post (180-260 words)
- End with one honest discussion question (not "what do you think?")
- First-hour engagement plan: 3 specific reply angles
- 3-5 hashtags

Topic: {topic}

Output exactly these labelled sections:
HOOK_VARIANTS:
[Hook 1: ...]
[Hook 2: ...]
[Hook 3: ...]

FINAL_POST:
[full post text including CTA + hashtags]

ENGAGEMENT_PLAN:
[3 reply angle lines]
""",

    "xing": """\
Du schreibst einen XING-Post fuer Klaravex (DACH-Sekundaersurface).
Klaravex spricht immer als Unternehmen ("wir" / "Klaravex"), niemals
als Einzelperson.
Zielgruppe: deutschsprachige IT-Entscheider, Office-Leitungen,
Geschaeftsfuehrer in kleinen Kanzleien, Praxen und Beratungen.
Ton: sachlich, direkt, praxisnah — kein Marketing-Jargon, kein KI-Hype.

VERBOTEN im Post:
- Personennamen (kein Gruender, kein Mitarbeiter namentlich)
- "Klara AI" oder interne Codenamen
- Erste Person Singular ("ich", "mir", "mein") — Klaravex ist "wir"
- Namen von Infra-Anbietern (Hetzner, Azure, Vapi, Atera, Smartlead)
- "Thought Leadership"-Ton oder Medienkommentar
- Vage Abstraktionen ("digitale Transformation", "Synergien")

PFLICHT:
- "Wir" / "Klaravex" als Subjekt
- Mindestens eine konkrete Zahl (89%, 100$/Monat, 4 Min 22 Sek)
- Branchenbezug (kleine Kanzleien, Arztpraxen, Steuerbueros) wo passend
- CTA: klaravex.de am Ende

Anforderungen:
- 2 Hook-Varianten auf Deutsch
- Finaler Post (130-200 Woerter) auf Deutsch
- Konkrete Handlungsempfehlung oder offene Diskussionsfrage
- 3-5 deutsche Hashtags

Thema: {topic}

Ausgabe mit EXAKT diesen Abschnitten (Header bleiben auf Englisch):

HOOK_VARIANTS:
[Variante 1: ...]
[Variante 2: ...]

FINAL_POST:
[vollstaendiger Post-Text mit CTA und Hashtags]

ENGAGEMENT_PLAN:
[2-3 Antwort-Prompts]
""",

    "twitter": """\
Draft for the Klaravex brand account on X (Twitter).
Klaravex speaks as a corporation — "we" / "Klaravex", never as an
individual.
Audience: tech-forward IT pros, founders, ops leads who spot hype
immediately and will call it out.
Tone: sharp, confident, no padding. One strong take per thread.

BANNED:
- Personal names (no founder identity)
- "Klara AI" or internal codenames
- First-person singular ("I", "me", "my") — Klaravex speaks as "we"
- Infra vendor names (Hetzner, Azure, Vapi, Atera, Smartlead, Apollo)
- Soft openers ("Just thinking…", "Hot take incoming…")
- Vague abstractions

REQUIRED:
- "We" / "Klaravex" as subject
- At least one specific number (89%, €75/mo, 4m 22s)
- klaravex.de CTA somewhere across the thread

Requirements:
- 3 hook/take variants
- 2-tweet thread in plain ASCII (no em-dashes, no smart quotes)
- Tweet 1: max 240 chars — lead with the take, not a warmup
- Tweet 2: max 240 chars — specific implication + CTA
- 2-3 hashtags spread across both tweets
- Reply strategy: 3 follow-up angles

Topic: {topic}

Output exactly these labelled sections (no extra text outside them).
Each section header must appear alone on its own line.

HOOK_VARIANTS:
[Hook 1: ...]
[Hook 2: ...]
[Hook 3: ...]

FINAL_POST:
Tweet 1: [text]
Tweet 2: [text]

ENGAGEMENT_PLAN:
[3 reply angle lines]
""",

    "facebook": """\
Draft a Facebook post for the Klaravex business page.
Klaravex speaks as a company ("we" / "Klaravex"), never as an
individual.
Audience: US small-firm owners and office managers (law, accounting,
medical, consulting) — non-technical people who need their IT to work
and are confused by AI noise.
Tone: friendly, plain English, zero jargon — but still corporate-voiced.

BANNED:
- Personal names (no founder identity)
- "Klara AI" or internal codenames
- First-person singular ("I", "me", "my")
- Infra vendor names
- "Thought leadership" tone
- Vague abstractions

REQUIRED:
- "We" / "Klaravex" as subject
- At least one specific number (89%, $100/mo, etc.)
- Named vertical or business situation
- CTA to klaravex.com on a clean final line

Requirements:
- 2 hook options (relatable opener or named business situation)
- Final post (100-160 words)
- Plain explanation of why it matters to their business
- 2-3 casual hashtags

Topic: {topic}

Output exactly these labelled sections:
HOOK_VARIANTS:
[Hook 1: ...]
[Hook 2: ...]

FINAL_POST:
[full post text including CTA and hashtags]

ENGAGEMENT_PLAN:
[2 comment prompt ideas]
""",

    "instagram": """\
You are the Instagram strategist for Klaravex.
Klaravex speaks as a brand ("we" / "Klaravex") — never as an
individual face. Visual personality comes from the brand: bold
typography, stat posters, dashboard screenshots, comparison cards.
Audience: US SMB owners, ops leads, and partners at small firms.
Visual learners, brand-personality driven.

BANNED in caption or visual concept:
- Personal names or founder identity
- "Klara AI" or internal codenames
- First-person singular ("I", "me", "my")
- Infra vendor names on the visual
- "Thought leadership" tone

REQUIRED in every post:
- "We" / "Klaravex" voice
- At least one specific number in the visual or caption
- Named vertical where relevant
- klaravex.com or personal.klaravex.com CTA in caption end

Visual format options (rotate):
- Big-number stat poster (Receipts angle)
- Single bold-quote billboard (Manifesto angle)
- Comparison split-screen card (Klaravex vs generic MSP)
- Multi-slide ticket walkthrough (Carousel format)
- Dashboard screenshot in clean terminal aesthetic (BTS angle)

Requirements:
- 3 hook options for on-screen text or caption opener
- A Reel concept (15-30 sec): premise, hook moment, scene breakdown, CTA
- A Carousel concept: slide-by-slide outline (max 8 slides)
- Final caption (include hashtag guidance: niche + branded + discovery)
- First-hour engagement plan

Topic: {topic}

Output exactly these labelled sections:
HOOK_VARIANTS:
[Hook 1: ...]
[Hook 2: ...]
[Hook 3: ...]

REEL_BRIEF:
[reel concept and breakdown]

CAROUSEL_BRIEF:
[slide-by-slide outline]

FINAL_CAPTION:
[caption text + hashtag guidance + CTA on its own line]

ENGAGEMENT_PLAN:
[3 engagement actions]
""",

    "tiktok": """\
You are the TikTok strategist for Klaravex.
Klaravex speaks as a brand ("we" / "Klaravex"), not as an
individual on camera. Voiceover is corporate first-person plural; no
faces required. Visual personality comes from on-screen stats,
comparison cards, dashboard screenshots, animated text.
Platform reality: 15-45 second vertical video, hook in first 3 seconds,
algorithm rewards completion + rewatch.
Audience: under-40 US SMB owners and ops leads discovering MSP
alternatives through short video.

BANNED:
- Personal names (no founder identity)
- "Klara AI" or internal codenames
- First-person singular ("I", "me", "my") in voiceover or captions
- Faces of any individual employee on camera
- Infra vendor names
- "Thought leadership" tone

REQUIRED:
- "We" / "Klaravex" voiceover
- At least one specific number on screen
- Named vertical where it fits
- klaravex.com in the final caption

Requirements:
- 3 hook variants (visual hook or on-screen text for first 3 seconds)
- 15-45 sec script with clear scene/action notes
- Video brief: setup, audio direction, on-screen text guidance
- 5-8 platform-native hashtags
- First-hour engagement actions

Topic: {topic}

Output exactly these labelled sections:
HOOK_VARIANTS:
[Hook 1: ...]
[Hook 2: ...]
[Hook 3: ...]

VIDEO_SCRIPT:
[timestamped script with action notes]

VIDEO_BRIEF:
[setup, audio, b-roll guidance, on-screen text]

FINAL_CAPTION:
[caption + hashtags + CTA]

ENGAGEMENT_PLAN:
[3 first-hour actions]
""",

    "reddit": """\
You are drafting a Reddit post for Klaravex.
Platform reality: Reddit users reject obvious promotion instantly.
This must read as a genuine community contribution from someone at
Klaravex sharing real observations — useful, specific, discussion-
oriented.
Subreddit context: r/sysadmin, r/msp, r/smallbusiness — community-
native, merit-based, promotion-averse.

Voice on Reddit is the one exception to "no first-person singular".
"We" reads as PR-speak on Reddit and tanks engagement. Use "we at
Klaravex" sparingly. The post may use "I" / "our team" / "at our
shop" framing, written as a Klaravex engineer or ops person. Still
no individual names.

Rules:
- No personal names (no founder identity, no employee names)
- No "Klara AI" or internal codenames
- No marketing hype, no soft openers like "Just wanted to share"
- Klaravex.com is allowed in ENGAGEMENT_PLAN as a reply-time link;
  keep it out of the original post body
- Use at least one specific operational number
- Reference a real vertical or scenario

Requirements:
- 2 title options for a professional subreddit
- Full post body that opens a real conversation (no hard sell)
- Engagement plan: likely comment angles + how to respond
- Risk notes: moderation concerns, brigading risk, sensitivity flags

Topic: {topic}

Output exactly these labelled sections. Each header must be on its
own line, with the colon, nothing after it on the same line.

TITLE_OPTIONS:
[Title 1: ...]
[Title 2: ...]

FINAL_POST:
[full post body]

ENGAGEMENT_PLAN:
[expected comment types + response guidance]

RISK_NOTES:
[moderation or community risk flags]
""",
}


# ── Topic generation prompt ───────────────────────────────────────────────────

_TOPIC_GENERATOR_PROMPT = """\
You are the social content strategist for Klaravex, a US-incorporated
managed IT and security firm (Klaravex LLC, Wyoming). Primary market:
US small professional services firms (10-50 employees) — law,
accounting, medical, dental, consulting. Cross-Atlantic capability
into the EU available but not the lead surface.

VOICE (binding — applies to every topic you suggest):
- Klaravex speaks in corporate first-person plural: "we" / "Klaravex"
- NEVER reference any individual by name (no founder, no personal history)
- NEVER use "I", "me", "my" — the corporation speaks, not a person
- NEVER reference infra vendor names (Hetzner, Azure, Vapi, Atera,
  Smartlead, Apollo) on consumer-facing platforms — those reveal stack
  and are only acceptable on dev-audience surfaces with explicit intent
- Always include concrete numbers when claiming a metric
- Always reference named verticals where it fits (small law firms,
  medical practices, accounting offices, professional services)
- Every topic must enable a klaravex.com or personal.klaravex.com CTA

SIX CREATIVE ANGLES — pick ONE per platform topic. Rotate angles
within a single generation. Do not assign the same angle to two
platforms in the same run.

  Angle 1 — RECEIPTS (proof-driven):
    Stat-stacked truths from operations. Tickets resolved, AI-handled
    percentage, response times, prices. Specific numbers that beat
    industry averages.
  Angle 2 — ANTI-MSP MANIFESTO (contrarian):
    One bold declaration of how Klaravex deletes a standard practice
    in legacy MSPs (vendor commissions, sales teams, locked-in
    contracts, hardware markups, discovery calls).
  Angle 3 — REAL TICKET WALKTHROUGH:
    Anonymized ticket arc — issue, AI handling, resolution time.
    Walks the reader through transparency. Builds trust through
    specificity.
  Angle 4 — WHY WE DON'T DO X (contrarian week):
    Singular statement of a thing Klaravex refuses to do, with the
    rationale. "Why we don't run quarterly audits — we run daily."
    "Why we don't have a sales team — we have a price page."
  Angle 5 — BEHIND-THE-SCENES (operational reality):
    A specific 24-hour or 1-week operational moment. Anonymized
    metrics from the dashboard. "Last week our AI auto-resolved N
    ransomware suspects overnight." Shows the operating reality.
  Angle 6 — ANONYMIZED CLIENT WIN:
    Named vertical + specific metrics. "A 14-person law firm in
    Phoenix switched to Klaravex in April. Last quarter their IT
    spend dropped 47%, incidents dropped 71%." No names, specific
    numbers.

{stats}

Campaign brief:
{brief}

{news_context}

Generate one DISTINCT topic per requested platform. Each topic must:
- Use ONE of the 6 angles (mention the angle in brackets at the start
  of the topic line, e.g. "[Receipts] ...")
- Be specific enough to write a complete post immediately
- Match the platform's audience and culture (audiences below)
- Honor the voice rules above
- No overlap between topics in the same run
- Use ONLY numbers from the APPROVED REAL STATS block above.
  If you need a number not on that list, write "{{stat:description}}"
  as a placeholder instead of inventing — the human approver will fill it.

Platform audiences:
- linkedincompany: US IT decision-makers at SMBs (10-50 employees);
  managing partners and ops leads at small professional services firms
- linkedinpersonal: The Klaravex page's first-person-plural voice; peers
  and IT buyers at US small firms. (Still "we", never "I".)
- xing: German-speaking DACH IT professionals if EU market is requested
  (secondary surface; .de commercial activity is currently paused)
- twitter: Tech-forward IT pros, founders, ops leads who spot hype fast
- facebook: Non-technical US small-firm owners confused by AI noise
- instagram: SMB owners + ops leads; visual learners; brand-personality
  driven (still corporate voice, no individual face)
- tiktok: Under-40 ops leads and small-firm owners discovering MSP
  alternatives through short video; needs strong 3-second hook
- reddit: r/sysadmin, r/msp, r/smallbusiness — community-native,
  promotion-averse; topics MUST be discussion-worthy not promotional

Requested platforms: {platforms}

Return format — exactly one line per platform, no preamble, no
explanation:
platform: [Angle N] topic
"""

_NEWS_CONTEXT_TEMPLATE = """\
Current news context (ground topics in real events where relevant):
{headlines}
"""

_FALLBACK_TOPICS: dict[str, str] = {
    # Angle 1 — Receipts
    "linkedincompany":  "[Receipts] Last month at Klaravex: 1,247 tickets opened across our clients, 1,109 resolved by our AI without a human (89%), median first-touch from a senior engineer at 4m 22s. Industry-average resolution time for the same ticket class: 14 hours. Same SLA, fraction of the cost.",
    # Angle 2 — Anti-MSP Manifesto
    "linkedinpersonal": "[Manifesto] We deleted the vendor-commission business model. Most MSPs collect commissions on the hardware they recommend; we charge $100/user/month flat and don't sell hardware. Here is what changes when nobody on your IT bill is paid to recommend a product.",
    # Angle 4 — Why we don't do X (DACH market)
    "xing":             "[Warum wir das nicht tun] Klaravex bietet keine quartalsweisen Sicherheits-Audits an. Wir machen taegliche automatisierte Audits. Hier ist, warum vierteljaehrliche Checks bei kleinen Kanzleien und Praxen in der Praxis nichts mehr finden — und was stattdessen funktioniert.",
    # Angle 4 — Why we don't do X
    "twitter":          "[Why we don't do X] Klaravex doesn't run quarterly security audits. We run daily ones. Reason: 90 days is a long time for a misconfigured backup or a disabled endpoint to sit unnoticed at a small firm. Daily is cheaper now that AI runs the check.",
    # Angle 6 — Anonymized client win
    "facebook":         "[Client win] A 14-person law firm switched from a traditional IT provider to Klaravex in April. Last quarter their IT spend dropped 47%, incidents dropped 71%, and the time partners spent on tech dropped from 11 hours/week to under 1. Foundation plan, no add-ons.",
    # Angle 5 — Behind-the-scenes
    "instagram":        "[BTS] Last week at Klaravex our AI auto-resolved 4 ransomware-suspect alerts overnight, patched 18 endpoints, and drafted 3 client status emails — all before a human reviewed anything. This is what 89% AI MSP looks like at 3am.",
    # Angle 3 — Real ticket walkthrough
    "tiktok":           "[Walkthrough] Real Klaravex ticket: small accounting firm, VPN drops every 20 minutes. AI handles it in 12 minutes start-to-fix. Industry SLA for the same ticket: 4 days. Stat overlay shows the full timeline.",
    # Angle 1 — Receipts (Reddit-appropriate framing)
    "reddit":           "[Receipts] Sharing some numbers from running an AI-first MSP for small US professional services firms: 89% of incoming tickets resolved without human escalation, 4m 22s median first-human-touch when escalation is needed, $100/user/month flat, no vendor commissions. Curious how this compares to what others are seeing at traditional MSPs.",
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass(slots=True)
class CampaignBrief:
    primary_goal: str
    audience: str
    offer: str | None = None
    topic: str | None = None
    pillar: str | None = None
    call_to_action: str | None = None
    region: str = "United States"
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_input(cls, input_data: dict[str, Any]) -> "CampaignBrief":
        return cls(
            primary_goal=input_data.get("primary_goal") or "Build authority and generate qualified inbound interest",
            audience=input_data.get("audience") or "SMB IT buyers and technical stakeholders across Germany and the EU",
            offer=input_data.get("offer"),
            topic=input_data.get("topic"),
            pillar=input_data.get("pillar"),
            call_to_action=input_data.get("call_to_action"),
            region=input_data.get("region") or "Germany / EU",
            notes=input_data.get("notes") or [],
        )

    def as_prompt_block(self) -> str:
        lines = [
            f"Primary goal:  {self.primary_goal}",
            f"Audience:      {self.audience}",
            f"Offer:         {self.offer or 'Not specified'}",
            f"Pillar:        {self.pillar or 'Not specified'}",
            f"Primary CTA:   {self.call_to_action or 'Not specified'}",
            f"Region:        {self.region}",
        ]
        if self.notes:
            lines.append("Notes:         " + " | ".join(self.notes))
        return "\n".join(lines)


@dataclass(slots=True)
class PlatformDraft:
    platform: str
    topic: str
    draft: str                             # FINAL_POST / FINAL_CAPTION section
    hooks: list[str] = field(default_factory=list)
    engagement_plan: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)  # reel/carousel/video/risk sections


# ── Agent ─────────────────────────────────────────────────────────────────────

class SocialMediaManagerAgent(BaseAgent):
    name = "social_media_manager"
    description = (
        "Generates multi-platform social content bundles with hook variants, "
        "engagement plans, and short-video briefs for up to 8 platforms "
        "(LinkedIn Company/Personal, XING, Twitter, Facebook, Instagram, TikTok, Reddit). "
        "Each platform gets a DIFFERENT topic suited to its audience. "
        "Content focuses on AI + IT intersection for SMBs across Germany and the EU. "
        "All posts bundled into a single P3 approval request."
    )
    permission_level = PermissionLevel.P2

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run(self, context: AgentContext, input_data: dict[str, Any]) -> AgentResult:
        brief = CampaignBrief.from_input(input_data)
        platforms = self._resolve_platforms(input_data.get("platforms"))
        if not platforms:
            return AgentResult.fail(
                "social_media_manager: no valid platforms provided",
                agent=self.name,
            )

        lead_id = input_data.get("lead_id") or context.lead_id

        # Accept both old-style (platform_topics with underscore keys) and new-style
        raw_platform_topics: dict[str, str] = (
            input_data.get("platform_topics")
            or input_data.get("platformtopics")
            or {}
        )
        # Normalise any old-style underscore keys to canonical form
        platform_topics: dict[str, str] = {
            _ALIAS_TO_CANONICAL.get(k, k): v
            for k, v in raw_platform_topics.items()
        }

        single_topic: str = input_data.get("topic") or brief.topic or ""

        # ── Build topic from lead if no topics supplied ───────────────────────
        if not single_topic and not platform_topics and lead_id:
            try:
                result = await context.db.execute(select(Lead).where(Lead.id == lead_id))
                lead: Lead | None = result.scalar_one_or_none()
                if lead:
                    services = lead.services_interest or "IT consulting"
                    company  = lead.company or "a client"
                    single_topic = (
                        f"Recent win: successfully supported {company} with {services}. "
                        f"Share a key practitioner insight from this engagement relevant "
                        f"to AI adoption or modern IT infrastructure."
                    )
            except Exception as exc:
                logger.warning("social_media_manager.lead_lookup_failed", error=str(exc))

        if not single_topic and not platform_topics:
            return AgentResult.fail(
                "social_media_manager: no topic or platform_topics provided",
                agent=self.name,
            )

        # ── Resolve per-platform topics ───────────────────────────────────────
        if platform_topics:
            # Fill any missing platforms with the single_topic fallback
            resolved_topics: dict[str, str] = {
                p: platform_topics.get(p) or single_topic or _FALLBACK_TOPICS.get(p, "")
                for p in platforms
            }
        else:
            resolved_topics = {p: single_topic for p in platforms}

        # ── Generate all platform drafts in parallel ──────────────────────────
        platform_drafts = await self._generate_all_drafts(
            resolved_topics=resolved_topics,
            api_key=context.settings.anthropic_api_key,
            brief=brief,
        )

        successful = {p: d for p, d in platform_drafts.items() if d is not None}
        failed = [p for p, d in platform_drafts.items() if d is None]

        # ── Placeholder lint — drop per-platform drafts that leaked template tokens.
        # Fail-granular: one bad LinkedIn draft must not block a clean Twitter one.
        from app.services.draft_validator import find_unfilled_placeholders
        placeholder_failures: dict[str, list[str]] = {}
        for platform, draft in list(successful.items()):
            issues = find_unfilled_placeholders(draft.draft)
            if issues:
                placeholder_failures[platform] = issues
                successful.pop(platform)
                failed.append(platform)
        if placeholder_failures:
            logger.error(
                "social_media_manager.placeholder_lint_failed",
                platforms=list(placeholder_failures.keys()),
                violations=placeholder_failures,
            )

        if not successful:
            return AgentResult.fail(
                "social_media_manager: all platform drafts failed",
                agent=self.name,
            )
        if failed:
            logger.warning("social_media_manager.partial_failure", failed_platforms=failed)

        # ── Build approval payload ────────────────────────────────────────────
        payload = self._build_approval_payload(
            brief=brief,
            platform_topics=resolved_topics,
            drafts=successful,
            single_topic=single_topic,
            lead_id=lead_id,
            scheduled_for=input_data.get("scheduled_for"),
        )

        # ── Queue approval ────────────────────────────────────────────────────
        try:
            from app.agents.registry import registry
            approval_mgr = registry.get("approval_manager")
            approval_result = await approval_mgr(
                context,
                {
                    "action":        "create",
                    "action_name":   "social_media_manager.publish",
                    "risk_level":    "P3",
                    "payload":       payload,
                    "justification": self._build_justification(
                        platform_topics=resolved_topics,
                        drafts=successful,
                        brief=brief,
                    ),
                    "requested_by":  self.name,
                },
            )
        except Exception as exc:
            logger.error("social_media_manager.approval_error", error=str(exc))
            return AgentResult.fail(
                f"social_media_manager: approval queue error — {exc}",
                agent=self.name,
            )

        approval_id = (
            approval_result.output.get("approval_id") if approval_result.success else None
        )
        logger.info(
            "social_media_manager.queued",
            approval_id=approval_id,
            platforms=[_CANONICAL_TO_PUBLISHER.get(p, p) for p in successful],
            failed_platforms=failed,
            per_platform_topics=bool(platform_topics),
        )
        return AgentResult.needs_approval(
            approval_id=approval_id or "unknown",
            action="social_media_manager.publish",
        )

    # ── Topic generation (used by beat task) ─────────────────────────────────

    @classmethod
    async def generate_platform_topics(
        cls,
        api_key: str,
        platforms: list[str] | None = None,
        brief: CampaignBrief | None = None,
        market: str = "eu",
    ) -> dict[str, str]:
        """
        Generate one distinct topic per platform via Claude, grounded in current
        news headlines fetched from RSS.

        market="eu"  → DACH/EU audience; default platform set includes XING
        market="us"  → US/NA audience; XING excluded, reddit substituted

        Returns dict[canonical_platform_key → topic_string].
        Falls back to _FALLBACK_TOPICS per platform if the LLM call fails or
        returns an incomplete result.
        """
        _US_PLATFORMS = ["linkedincompany", "linkedinpersonal", "twitter", "facebook", "reddit"]
        if market == "us":
            target_platforms = platforms or _US_PLATFORMS
            brief_block = brief.as_prompt_block() if brief else (
                "Primary goal: Build authority and generate qualified inbound interest\n"
                "Audience: SMB IT buyers and technical stakeholders across the United States\n"
                "Region: United States / North America"
            )
        else:
            target_platforms = platforms or PLATFORMS_ALL[:5]  # default: original 5 (includes XING)
            brief_block = brief.as_prompt_block() if brief else (
                "Primary goal: Build authority and generate qualified inbound interest\n"
                "Audience: SMB IT buyers and technical stakeholders across Germany and the EU\n"
                "Region: Germany / EU"
            )
        news_context = await cls._fetch_news_context()

        prompt = _TOPIC_GENERATOR_PROMPT.format(
            stats=_stats_block(),
            brief=brief_block,
            news_context=(
                _NEWS_CONTEXT_TEMPLATE.format(headlines=news_context)
                if news_context
                else "(No current news context — use evergreen operational pain points.)"
            ),
            platforms=", ".join(target_platforms),
        )

        client = AsyncAnthropic(api_key=api_key)
        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            try:
                from app.services.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model="claude-haiku-4-5-20251001",
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            raw = response.content[0].text.strip()
            topics: dict[str, str] = {}
            for line in raw.splitlines():
                line = line.strip()
                if ": " in line:
                    platform, _, topic_text = line.partition(": ")
                    platform = _ALIAS_TO_CANONICAL.get(platform.strip().lower(), platform.strip().lower())
                    if platform in target_platforms and topic_text.strip():
                        topics[platform] = topic_text.strip()

            if len(topics) == len(target_platforms):
                logger.info(
                    "social_media_manager.platform_topics_generated",
                    platforms=list(topics.keys()),
                    news_injected=bool(news_context),
                )
                return topics

            logger.warning(
                "social_media_manager.platform_topics_incomplete",
                got=list(topics.keys()),
                expected=target_platforms,
            )
        except Exception as exc:
            logger.warning("social_media_manager.platform_topics_error", error=str(exc))

        return {p: _FALLBACK_TOPICS.get(p, "AI and IT infrastructure for European SMBs") for p in target_platforms}

    @classmethod
    async def generate_weekly_topics(cls, api_key: str) -> list[str]:
        """
        Legacy wrapper. Returns per-platform topics as a flat list.
        Prefer generate_platform_topics() for new code.
        """
        topics = await cls.generate_platform_topics(api_key=api_key)
        return list(topics.values())

    # ── News context (RSS) ────────────────────────────────────────────────────

    @classmethod
    async def _fetch_news_context(cls) -> str:
        """
        Fetch current IT/AI/EU news headlines from RSS feeds.
        Returns a formatted headlines string or empty string on failure.
        """
        import feedparser  # type: ignore

        feeds = [
            ("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
            ("The Verge",      "https://www.theverge.com/rss/index.xml"),
            ("Heise Online",   "https://www.heise.de/rss/heise-atom.xml"),
            ("EU Digital",     "https://digital-strategy.ec.europa.eu/en/rss.xml"),
        ]
        headlines: list[str] = []
        loop = asyncio.get_event_loop()

        for source, url in feeds:
            try:
                feed = await loop.run_in_executor(
                    None, lambda u=url: feedparser.parse(u)
                )
                for entry in feed.entries[:3]:
                    title = entry.get("title", "").strip()
                    if title:
                        headlines.append(f"- [{source}] {title}")
            except Exception as exc:
                logger.debug("social_media_manager.rss_error", source=source, error=str(exc))

        if not headlines:
            logger.info("social_media_manager.news_context_empty")
            return ""

        logger.info("social_media_manager.news_context_fetched", count=len(headlines))
        return "\n".join(headlines[:12])

    # ── Draft generation ──────────────────────────────────────────────────────

    def _resolve_platforms(self, raw: Any) -> list[str]:
        """
        Accept a list of platform names in any case/format, normalise to
        canonical (no-underscore) keys, return only valid entries.
        Falls back to the default 5 platforms if raw is falsy.
        """
        if not raw:
            return PLATFORMS_ALL[:5]
        if isinstance(raw, str):
            raw = [raw]
        result: list[str] = []
        for p in raw:
            normalised = _ALIAS_TO_CANONICAL.get(p, p.lower().replace("_", "").replace("-", ""))
            if normalised in PLATFORMS_ALL:
                result.append(normalised)
        return result or PLATFORMS_ALL[:5]

    async def _generate_all_drafts(
        self,
        resolved_topics: dict[str, str],
        api_key: str,
        brief: CampaignBrief | None = None,
    ) -> dict[str, PlatformDraft | None]:
        """Fire all platform drafts in parallel via asyncio.gather()."""
        tasks = [
            self._generate_one_draft(platform=p, topic=t, api_key=api_key, brief=brief)
            for p, t in resolved_topics.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            platform: (None if isinstance(result, Exception) else result)
            for platform, result in zip(resolved_topics.keys(), results)
        }

    async def _generate_one_draft(
        self,
        platform: str,
        topic: str,
        api_key: str,
        brief: CampaignBrief | None = None,
    ) -> PlatformDraft:
        """
        Generate a single platform draft. Raises on LLM error so gather()
        can capture it and map it to None in the caller.

        When ``brief`` is provided, appends CAMPAIGN CONTEXT + PLATFORM DEFAULTS
        + VOICE GUARDRAILS + BEST PRACTICES blocks to the prompt so the LLM has
        full campaign awareness for each individual platform call.
        """
        prompt_template = PLATFORM_PROMPTS.get(platform)
        if not prompt_template:
            raise ValueError(f"No prompt template for platform: {platform}")

        prompt = prompt_template.format(topic=topic)

        if brief is not None:
            defaults = PLATFORM_DEFAULTS.get(platform, {})
            best_practices = self._platform_context(platform, brief, defaults)
            defaults_block = "\n".join(f"  {k}: {v}" for k, v in defaults.items())
            guardrails_block = "\n".join(f"- {g}" for g in VOICE_GUARDRAILS)
            practices_block = "\n".join(f"- {bp}" for bp in best_practices)
            prompt += (
                "\n\nCAMPAIGN CONTEXT:\n" + brief.as_prompt_block()
                + "\n\nPLATFORM DEFAULTS:\n" + defaults_block
                + "\n\nVOICE GUARDRAILS:\n" + guardrails_block
                + "\n\nBEST PRACTICES:\n" + practices_block
            )

        client = AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model="claude-haiku-4-5-20251001",
                response=response, lead_id=getattr(context, 'lead_id', None),
            )
        except Exception:
            pass
        raw = response.content[0].text.strip()
        draft = self._parse_draft(platform=platform, topic=topic, raw=raw)

        logger.info(
            "social_media_manager.draft_generated",
            platform=platform,
            topic=topic[:60],
            chars=len(draft.draft),
            hooks=len(draft.hooks),
        )
        return draft

    @staticmethod
    def _parse_draft(platform: str, topic: str, raw: str) -> PlatformDraft:
        """
        Extract labelled sections from the structured LLM output.

        Handles all platform output schemas:
          - Standard:  HOOK_VARIANTS / FINAL_POST / ENGAGEMENT_PLAN
          - Instagram:  + REEL_BRIEF / CAROUSEL_BRIEF / FINAL_CAPTION
          - TikTok:     + VIDEO_SCRIPT / VIDEO_BRIEF / FINAL_CAPTION
          - Reddit:    TITLE_OPTIONS / FINAL_POST / ENGAGEMENT_PLAN / RISK_NOTES
          - XING:      HOOK_VARIANTS (2) / FINAL_POST / ENGAGEMENT_PLAN
        """
        sections: dict[str, str] = {}
        current_key: str | None = None
        current_lines: list[str] = []

        # Section headers — order matters for split; longer names first
        section_keys = [
            "HOOK_VARIANTS", "FINAL_POST", "ENGAGEMENT_PLAN",
            "REEL_BRIEF", "CAROUSEL_BRIEF", "FINAL_CAPTION",
            "VIDEO_SCRIPT", "VIDEO_BRIEF", "TITLE_OPTIONS", "RISK_NOTES",
        ]
        header_re = re.compile(
            r"^(" + "|".join(re.escape(k) for k in section_keys) + r"):?\s*$"
        )

        for line in raw.splitlines():
            m = header_re.match(line.strip())
            if m:
                if current_key:
                    sections[current_key] = "\n".join(current_lines).strip()
                current_key = m.group(1)
                current_lines = []
            else:
                if current_key:
                    current_lines.append(line)

        if current_key:
            sections[current_key] = "\n".join(current_lines).strip()

        # Extract hooks as a list
        hooks: list[str] = []
        hook_block = sections.get("HOOK_VARIANTS", "")
        for line in hook_block.splitlines():
            line = line.strip()
            # Strip leading markers: [Hook 1: ...], Hook 1:, [Variante 1: ...]
            line = re.sub(r"^\[?(Hook|Variante|Option)\s*\d+:?\s*", "", line, flags=re.IGNORECASE).strip(" ]")
            if line:
                hooks.append(line)

        # Engagement plan as a list
        engagement_plan: list[str] = [
            ln.strip().lstrip("-•·").strip()
            for ln in sections.get("ENGAGEMENT_PLAN", "").splitlines()
            if ln.strip()
        ]

        # Main post body — FINAL_POST for most platforms, FINAL_CAPTION for visual platforms
        main_post = (
            sections.get("FINAL_POST")
            or sections.get("FINAL_CAPTION")
            or raw  # fallback: entire response
        )

        # Extra sections for visual / video / reddit platforms
        meta: dict[str, Any] = {}
        for key in ("REEL_BRIEF", "CAROUSEL_BRIEF", "VIDEO_SCRIPT", "VIDEO_BRIEF",
                    "TITLE_OPTIONS", "RISK_NOTES"):
            if key in sections and sections[key]:
                meta[key.lower()] = sections[key]

        return PlatformDraft(
            platform=platform,
            topic=topic,
            draft=main_post,
            hooks=hooks,
            engagement_plan=engagement_plan,
            meta=meta,
        )

    # ── Prompt assembly helpers ───────────────────────────────────────────────

    def _platform_context(
        self,
        platform: str,
        brief: CampaignBrief,
        defaults: dict[str, Any],
    ) -> list[str]:
        """
        Assemble an ordered list of best-practice rules for a specific platform,
        enriched with campaign-specific offer/CTA constraints.

        Returns a list of rule strings ready to be joined into a prompt block.
        """
        # LinkedIn variants share the linkedin key
        key = "linkedin" if platform.startswith("linkedin") else platform
        rules: list[str] = BEST_PRACTICES.get(key, []).copy()

        # Visual/video platforms get the shared video production rules
        if platform in {"instagram", "tiktok"}:
            rules.extend(BEST_PRACTICES.get("video", []))

        # Inject campaign-specific constraints when present
        if brief.offer:
            rules.append(f"Tie the content back to this offer when natural: {brief.offer}")
        if brief.call_to_action:
            rules.append(f"Preferred CTA direction: {brief.call_to_action}")
        if brief.pillar:
            rules.append(f"Content pillar for this campaign: {brief.pillar}")

        return rules

    # ── Approval payload builders ─────────────────────────────────────────────

    def _build_approval_payload(
        self,
        *,
        brief: CampaignBrief,
        platform_topics: dict[str, str],
        drafts: dict[str, PlatformDraft],
        single_topic: str,
        lead_id: Any,
        scheduled_for: str | None,
    ) -> dict[str, Any]:
        """
        Build the structured approval payload.

        Keys that use publisher-style names (linkedin_company etc.) for backward
        compat with execute_approved_action.py and social_publisher.py.
        """
        def _pub(p: str) -> str:
            return _CANONICAL_TO_PUBLISHER.get(p, p)

        return {
            # ── Publisher-compat top-level keys ──────────────────────────────
            "platform_topics":  {_pub(p): t for p, t in platform_topics.items()},
            "topic":            single_topic,
            "drafts":           {_pub(p): d.draft for p, d in drafts.items()},
            "platforms":        [_pub(p) for p in drafts],
            # ── Extended content ──────────────────────────────────────────────
            "hooks":            {_pub(p): d.hooks for p, d in drafts.items()},
            "engagement_plans": {_pub(p): d.engagement_plan for p, d in drafts.items()},
            "meta":             {_pub(p): d.meta for p, d in drafts.items() if d.meta},
            # ── Campaign context ──────────────────────────────────────────────
            "campaign": {
                "primary_goal":   brief.primary_goal,
                "audience":       brief.audience,
                "offer":          brief.offer,
                "pillar":         brief.pillar,
                "call_to_action": brief.call_to_action,
                "region":         brief.region,
                "notes":          brief.notes,
            },
            # ── Scheduling / traceability ─────────────────────────────────────
            "scheduled_for": scheduled_for,
            "lead_id":       str(lead_id) if lead_id else None,
            "generated_at":  datetime.now(tz=timezone.utc).isoformat(),
        }

    def _build_justification(
        self,
        platform_topics: dict[str, str],
        drafts: dict[str, PlatformDraft],
        brief: CampaignBrief,
    ) -> str:
        """
        Human-readable justification string for the approval queue.
        Shows goal, audience, platform count, and the first 3 topic slugs.
        """
        def _pub(p: str) -> str:
            return _CANONICAL_TO_PUBLISHER.get(p, p)

        topic_parts = [
            f"{_pub(p)}: {topic[:80]}"
            for p, topic in list(platform_topics.items())[:3]
        ]
        if len(platform_topics) > 3:
            topic_parts.append(f"… +{len(platform_topics) - 3} more")

        return (
            f"Social post drafts ready for review across {len(drafts)} platform(s). "
            f"Goal: {brief.primary_goal}. "
            f"Audience: {brief.audience}. "
            f"Topics: {'; '.join(topic_parts)}"
        )

    @staticmethod
    def _extract_section_list(text: str, section_name: str) -> list[str]:
        """
        Regex-based alternative to the line-by-line parser.
        Extracts the body of a labelled section as a list of non-empty lines.

        Handles sections that end at the next ALL_CAPS label or end of string.
        """
        pattern = rf"{re.escape(section_name)}:\s*(.*?)(?:\n[A-Z_]{{2,}}:|\Z)"
        match = re.search(pattern, text, flags=re.S)
        if not match:
            return []
        return [
            line.strip().lstrip("-•·").strip()
            for line in match.group(1).splitlines()
            if line.strip()
        ]
