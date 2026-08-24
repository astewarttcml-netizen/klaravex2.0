"""Vault search — Vapi tool endpoint.

Lets the voice assistant query the Klaravex observation vault for
relevant decisions, change records, and notes.

  POST /search-knowledge-vault
  Body: { "query": "...", "limit": 5 }

Calls vault-mcp at VAULT_MCP_URL (default http://100.66.236.56:3142)
using the MCP ``vault_search`` tool over HTTP.

Returns a voice-safe summary: plain English, no markdown, ≤3 sentences
per result, capped to `limit` (max 5) items.

Behind x-vapi-secret (mounted in vapi/router.py).
"""

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

log = logging.getLogger("klaravex.vapi.search_knowledge_vault")
router = APIRouter()

VAULT_MCP_URL = os.environ.get("VAULT_MCP_URL", "http://100.66.236.56:3142")
# Hard cap — vault results can be long; don't blow the voice context window.
_MAX_LIMIT = 5
# Budget per result in characters — keeps spoken summaries short.
_RESULT_CHAR_BUDGET = 300
# httpx timeout (seconds) — voice calls expect <8s total.
_HTTP_TIMEOUT = 6.0


class SearchKnowledgeVaultRequest(BaseModel):
    query: str = Field(default="")
    limit: int = Field(default=3, ge=1, le=_MAX_LIMIT)
    test: bool = Field(default=False, alias="_test")


def _voice_safe_result(hit: dict[str, Any]) -> str:
    """Flatten a vault hit to a short plain-English sentence."""
    title = (hit.get("title") or hit.get("topic") or "").strip()
    body = (hit.get("content") or hit.get("body") or hit.get("note") or "").strip()
    ts = (hit.get("created_at") or hit.get("timestamp") or "").strip()

    # Keep it terse — one sentence per result.
    parts: list[str] = []
    if title:
        parts.append(title)
    if body:
        trimmed = body[: _RESULT_CHAR_BUDGET]
        if len(body) > _RESULT_CHAR_BUDGET:
            trimmed = trimmed.rstrip() + "…"
        parts.append(trimmed)
    if ts:
        # Only the date portion — avoid reading a full ISO timestamp aloud.
        date_part = ts[:10]
        parts.append(f"(recorded {date_part})")

    return " — ".join(parts) if parts else "(no detail available)"


async def _call_vault_search(query: str, limit: int) -> list[dict[str, Any]]:
    """POST to vault-mcp MCP endpoint and return a list of hit dicts.

    vault-mcp exposes MCP over HTTP. We call the ``vault_search`` tool via
    the standard MCP HTTP tool-call path:
      POST /tools/call  { "name": "vault_search", "arguments": {...} }
    """
    payload = {
        "name": "vault_search",
        "arguments": {"query": query, "limit": limit},
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(f"{VAULT_MCP_URL}/tools/call", json=payload)
        resp.raise_for_status()
        data = resp.json()

    # MCP HTTP response: { "content": [ { "type": "text", "text": "..." } ] }
    # The text may be JSON-encoded results or a plain string.
    content = data.get("content") or []
    if not content:
        return []

    import json as _json

    results: list[dict[str, Any]] = []
    for item in content:
        raw = (item.get("text") or "").strip()
        if not raw:
            continue
        # Try to decode as JSON list/dict; fall back to treating as plain text.
        try:
            decoded = _json.loads(raw)
        except _json.JSONDecodeError:
            decoded = raw

        if isinstance(decoded, list):
            results.extend(decoded)
        elif isinstance(decoded, dict):
            results.append(decoded)
        else:
            # Plain text block — wrap it so downstream code can handle it.
            results.append({"content": str(decoded)})

    return results[:limit]


@router.post("/search-knowledge-vault")
async def search_knowledge_vault(req: SearchKnowledgeVaultRequest) -> dict[str, Any]:
    if req.test:
        return {
            "status": "ok",
            "test": True,
            "summary": "Vault search test acknowledged.",
            "results": [],
        }

    query = (req.query or "").strip()
    if not query:
        return {
            "status": "error",
            "reason": "No query provided. Ask the caller what they would like to know.",
        }

    limit = max(1, min(req.limit, _MAX_LIMIT))

    try:
        hits = await _call_vault_search(query, limit)
    except httpx.TimeoutException:
        log.warning("vault-mcp timeout for query=%r", query)
        return {
            "status": "error",
            "reason": (
                "The knowledge vault did not respond in time. "
                "Please try again in a moment."
            ),
        }
    except Exception as exc:
        log.exception("vault-mcp call failed for query=%r: %s", query, exc)
        return {
            "status": "error",
            "reason": (
                "Could not reach the knowledge vault right now. "
                "I can still help with general information."
            ),
        }

    if not hits:
        return {
            "status": "ok",
            "summary": "No matching records found in the vault for that query.",
            "results": [],
            "query": query,
        }

    voice_lines = [_voice_safe_result(h) for h in hits]

    # Compact spoken summary — list the count then enumerate results.
    count_word = "one result" if len(voice_lines) == 1 else f"{len(voice_lines)} results"
    summary = (
        f"Found {count_word} in the vault. "
        + " | ".join(voice_lines)
    )

    return {
        "status": "ok",
        "summary": summary,
        "results": voice_lines,
        "query": query,
    }
