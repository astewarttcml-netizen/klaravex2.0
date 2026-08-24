"""
Marketing AI team orchestration.

Each team runs daily 'tick' loops. Each tick:
  1. Pulls current state (budget, spend, attribution conversions, recent actions)
  2. Asks Claude (with team's personality) for the next moves
  3. Parses requested tool calls
  4. Runs each tool through the brand-voice classifier first when applicable
  5. Executes tools; records every action; updates run status

Teams cannot bypass:
  - The Mercury card spend cap (enforced server-side via webhook)
  - The brand-voice classifier on outbound copy
  - The daily action cap (defends against runaway loops)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from .db import get_pool
from . import marketing_tools as tools

log = logging.getLogger("klaravex.marketing_team")

LITELLM_URL = os.environ.get("LITELLM_URL", "")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
MAX_TOOL_CALLS_PER_TICK = int(os.environ.get("MARKETING_MAX_CALLS_PER_TICK", "8"))


TEAM_SYSTEM_HEADER = """\
You are the lead marketing strategist for an autonomous AI marketing team running
against another AI team in a 30-day competition. Both teams have $1,000 to spend
on a Mercury virtual card to acquire real Klaravex clients.

WIN CONDITION: Most billed revenue from acquired clients within 30 days.
(Acquisition is tracked via attribution_team tags on klaravex_clients rows.)

Klaravex offers:
  - klaravex.com  (B2B managed IT & security: Foundation $49/mo, Assurance $79/mo,
    Directive $129/mo). US SMBs — law, accounting, medical, professional services.
  - personal.klaravex.com (consumer: Essentials $24/mo, Home Membership $39/mo,
    per-incident calls). Families, parents, individuals.

Positioning fact (background only — see voice rules below): Klaravex is 89% AI /
11% human, no vendor commissions on hardware/software it recommends.

⚠️ BINDING VOICE POLICY — violating this blocks every draft, no exceptions:
  - NEVER write in first-person singular ("I", "me", "my", "I built…", "I was
    let go…"). NEVER name the founder or write his personal biography/layoff
    story. The corporation speaks as "we" / "Klaravex" — always third-person,
    always the company as the actor, never an individual.
  - NEVER say "Klara AI" — refer to it as "our AI" or "Klaravex AI."
  - NEVER sign off as an individual person.
  - This applies to EVERY surface: ad copy, LinkedIn (company AND "personal"
    account posts), Twitter, email, everything. There is no surface where
    first-person personal narrative is acceptable.

CONSTRAINTS:
  - Daily spend cap is $50. Burn evenly or take measured risks.
  - Every external post/email must pass the brand voice gate (no first-person
    singular, no personal biography, no buzzwords, no fake urgency, no
    scarcity tricks, no overclaiming).
  - Actions touching real customers (publishing posts, sending emails) start as
    drafts requiring Anthony's one-click approval.
  - You can request human approval for ambitious moves over $50 single-spend.

HARD GUARDRAILS:
  - You cannot bypass the Mercury card cap (the card itself enforces it).
  - You cannot publish to brand accounts without Anthony approving the draft.
  - You cannot DM, cold-call, or email anyone without Apollo-sourced + consent-aware data.
"""


def _team_personality(team_row: dict) -> str:
    return f"""
YOUR TEAM: {team_row['display_name']} ({team_row['team_code'].upper()})
YOUR PERSONALITY:
{team_row['personality_brief']}

YOUR ATTRIBUTION TAG: {team_row['attribution_tag']}
YOUR LANDING URL FRAGMENT: {team_row['utm_landing_path']}
"""


async def _gather_state(team_id: str) -> dict:
    """Pull the team's current state — what they have to work with."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        team = await conn.fetchrow(
            "SELECT * FROM klaravex_marketing_teams WHERE id=$1", team_id,
        )
        recent_actions = await conn.fetch(
            """
            SELECT action_type, status, created_at, payload, result
              FROM klaravex_marketing_actions
             WHERE team_id=$1
             ORDER BY created_at DESC LIMIT 20
            """,
            team_id,
        )
        conversion_count = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_clients WHERE attribution_team=$1",
            team["attribution_tag"],
        )
        # Revenue attribution = sum of all subscription monthly value for clients tagged to us
        # (For v1 we approximate via metadata. Real version pulls Stripe.)
        attributed_clients = await conn.fetch(
            """
            SELECT email, segment, created_at FROM klaravex_clients
             WHERE attribution_team=$1 ORDER BY created_at DESC LIMIT 30
            """,
            team["attribution_tag"],
        )
        today_spend = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_usd), 0) FROM klaravex_marketing_spend
             WHERE team_id=$1 AND txn_at::date = current_date AND status IN ('settled','authorized')
            """,
            team_id,
        )

    return {
        "team": dict(team),
        "budget_remaining": float(team["budget_usd"] or 0) - float(team["spend_usd"] or 0),
        "total_spent": float(team["spend_usd"] or 0),
        "daily_spend_so_far": float(today_spend or 0),
        "daily_cap_remaining": max(0, float(team["daily_spend_cap_usd"] or 50) - float(today_spend or 0)),
        "conversion_count": int(conversion_count or 0),
        "attributed_clients": [dict(r) for r in attributed_clients],
        "recent_actions_summary": [
            {"type": r["action_type"], "status": r["status"], "at": r["created_at"].isoformat()}
            for r in recent_actions
        ],
    }


def _tool_catalog_for_prompt() -> str:
    return """
AVAILABLE TOOLS (call by emitting JSON in your response, see format below):

  apollo.search_contacts(titles: list[str], industries: list[str]?, employee_range: str?, country: str?, limit: int?)
      Find prospects. Returns {ok, count, contacts: [{name, email, title, company, linkedin}]}.

  resend.send_email(to_email: str, subject: str, body_text: str, from_name: str?)
      Send a single outbound email. Body passes through brand voice gate.

  organic.post_draft(platform: str, content: str, topic: str?)
      platform = linkedin_company | linkedin_personal | twitter | facebook
      Drafts a post for Anthony approval. Never publishes directly.

  meta_ads.create_campaign(name: str, daily_budget_usd: float, objective: str, target_url: str, creative_text: str, audience: dict?)
      Creates a PAUSED Meta ad campaign for Anthony to enable.

  linkedin_ads.create_campaign(name: str, daily_budget_usd: float, target_url: str, ad_copy: str, audience_industries: list[str])

  google_ads.create_campaign(name: str, daily_budget_usd: float, keywords: list[str], target_url: str, headlines: list[str], descriptions: list[str])

  human.request_approval(action_summary: str, reason: str, proposed_payload: dict)
      Queue a decision for Anthony.

  log.observation(summary: str, data: dict)
      Record an analyst observation (used for end-of-day reflection).

CALLING TOOLS — reply ONLY with a JSON object:
{
  "thinking": "1-3 sentences on your reasoning for this tick",
  "tool_calls": [
    {"tool": "apollo.search_contacts", "args": {...}},
    {"tool": "organic.post_draft", "args": {...}}
  ],
  "end_of_tick_summary": "what you accomplished and what you'll evaluate next tick"
}

Limit yourself to %d tool calls per tick. Choose carefully.
""" % MAX_TOOL_CALLS_PER_TICK


def _build_tick_prompt(team_row: dict, state: dict) -> str:
    return (
        TEAM_SYSTEM_HEADER
        + _team_personality(team_row)
        + _tool_catalog_for_prompt()
        + f"\n\nCURRENT STATE:\n{json.dumps(state, indent=2, default=str)[:6000]}\n"
        "\nPlan and execute this tick now."
    )


async def _record_run_start(team_id: str, run_kind: str) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO klaravex_marketing_runs (team_id, run_kind, status)
            VALUES ($1, $2, 'running') RETURNING id::text
            """,
            team_id, run_kind,
        )


async def _record_run_finish(run_id: str, status: str, *, summary: str,
                             tokens_in: int, tokens_out: int, raw_out: dict,
                             error: Optional[str] = None) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE klaravex_marketing_runs
               SET status=$1, summary=$2, tokens_in=$3, tokens_out=$4,
                   raw_output=$5::jsonb, error=$6, finished_at=now()
             WHERE id=$7
            """,
            status, summary[:2000], tokens_in, tokens_out,
            json.dumps(raw_out)[:60000], error, run_id,
        )


async def _execute_tool_calls(team_id: str, run_id: str,
                              tool_calls: list[dict]) -> list[dict]:
    """Run each tool, returning results in the same order. Brand-voice classifier
    is applied to outbound text before the tool is even called."""
    results = []
    for i, call in enumerate(tool_calls[:MAX_TOOL_CALLS_PER_TICK]):
        name = call.get("tool", "")
        args = call.get("args", {}) or {}
        # Pre-flight: brand voice gate on outbound text
        text_to_check = (
            args.get("content") or args.get("body_text") or args.get("creative_text")
            or args.get("ad_copy") or ""
        )
        if text_to_check:
            gate = await tools.brand_voice_classifier(text_to_check)
            if not gate.get("ok"):
                blocked = {"ok": False, "reason": f"brand_voice_blocked: {gate.get('reason')}"}
                await tools._log_action(team_id, f"guardrail.{name}", call, blocked,
                                        status="blocked", run_id=run_id)
                results.append({"tool": name, "result": blocked})
                continue

        fn = tools.TOOL_CATALOG.get(name)
        if not fn:
            results.append({"tool": name, "result": {"ok": False, "error": "unknown_tool"}})
            continue
        try:
            res = await fn(team_id, **args, run_id=run_id) if "run_id" in fn.__code__.co_varnames else await fn(team_id, **args)
        except Exception as exc:
            log.exception("tool %s exception for team %s: %s", name, team_id, exc)
            res = {"ok": False, "error": str(exc)}
        results.append({"tool": name, "result": res})
    return results


async def run_tick(team_id: str) -> dict:
    """Execute one tick for the given team. Idempotent against retries via run row."""
    state = await _gather_state(team_id)
    team_row = state["team"]

    if team_row["status"] in ("retired", "winner", "paused"):
        return {"skipped": True, "reason": f"team_status:{team_row['status']}"}
    if state["budget_remaining"] <= 0:
        return {"skipped": True, "reason": "budget_exhausted"}
    if state["daily_cap_remaining"] <= 0:
        return {"skipped": True, "reason": "daily_cap_reached"}

    run_id = await _record_run_start(team_id, "tick")
    prompt = _build_tick_prompt(team_row, state)

    if not (LITELLM_URL and LITELLM_KEY):
        await _record_run_finish(run_id, "failed", summary="LITELLM not configured",
                                 tokens_in=0, tokens_out=0, raw_out={}, error="no_llm")
        return {"run_id": run_id, "error": "no_llm"}

    try:
        async with httpx.AsyncClient(timeout=120) as hc:
            r = await hc.post(
                f"{LITELLM_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                json={"model": "deepseek", "max_tokens": 3000, "messages": [{"role": "user", "content": prompt}]},
            )
            if r.status_code != 200:
                await _record_run_finish(run_id, "failed", summary=f"LLM error {r.status_code}",
                                         tokens_in=0, tokens_out=0, raw_out={}, error=f"llm_{r.status_code}")
                return {"run_id": run_id, "error": f"llm_{r.status_code}"}
            raw_text = r.json()["choices"][0]["message"]["content"].strip()
        # Strip code fences if Claude added them
        import re
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        tool_calls = parsed.get("tool_calls", []) or []
    except Exception as exc:
        await _record_run_finish(run_id, "failed",
                                 summary=f"plan parse failed: {exc}",
                                 tokens_in=0, tokens_out=0,
                                 raw_out={"raw_text": raw_text if 'raw_text' in dir() else ''},
                                 error=str(exc))
        return {"run_id": run_id, "error": "plan_parse_failed"}

    results = await _execute_tool_calls(team_id, run_id, tool_calls)
    summary = parsed.get("end_of_tick_summary", "") or parsed.get("thinking", "")[:500]

    # Token counting — best effort; the LiteLLM proxy does not return usage
    # in the same shape as OpenAI, so default to 0 when absent.
    try:
        usage = r.json().get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
    except Exception:
        tokens_in = 0
        tokens_out = 0

    await _record_run_finish(
        run_id, "completed",
        summary=summary,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        raw_out={"plan": parsed, "executions": results},
    )
    return {
        "run_id": run_id,
        "tool_calls_attempted": len(tool_calls),
        "tool_calls_executed": len(results),
        "summary": summary,
    }


# Autopilot is OFF by default. request_human_approval() has no rate limit or
# dedup (unlike organic_post_draft()), which let the two teams flood Anthony
# with an approval email on effectively every tick — paused 2026-07-16 pending
# a rebuild of the approval/notification path. Requires an explicit env var to
# turn back on, not just an absent/misconfigured flag defaulting to "on".
def _autopilot_enabled() -> bool:
    return os.environ.get("MARKETING_AUTOPILOT_ENABLED", "").strip().lower() == "true"


async def run_tick_for_team_code(team_code: str) -> dict:
    if not _autopilot_enabled():
        return {"paused": True, "reason": "marketing_autopilot_disabled"}
    pool = await get_pool()
    async with pool.acquire() as conn:
        team_id = await conn.fetchval(
            "SELECT id::text FROM klaravex_marketing_teams WHERE team_code=$1", team_code,
        )
    if not team_id:
        return {"error": f"team_code_not_found:{team_code}"}
    return await run_tick(team_id)


async def run_tick_for_all_active_teams() -> dict:
    if not _autopilot_enabled():
        return {"paused": True, "reason": "marketing_autopilot_disabled", "teams_ticked": 0}
    pool = await get_pool()
    async with pool.acquire() as conn:
        team_ids = await conn.fetch(
            "SELECT id::text FROM klaravex_marketing_teams WHERE status IN ('soft_launch','live')",
        )
    results = []
    for row in team_ids:
        results.append({"team": row["id"], "result": await run_tick(row["id"])})
    return {"teams_ticked": len(results), "results": results}
