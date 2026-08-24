# OpenClaw API Specification (v1)

The OpenClaw reasoning service is the LLM seam for every Klaravex `EngineerAgent`
subclass. The agent constructs a prompt and posts it here; the service runs the
LLM call and returns a structured next-action proposal.

Base URL: value of the `OPENCLAW_URL` environment variable (default
`http://localhost:8420`).

Consumer of record: `infra/loki_handlers/engineers/base.py::EngineerAgent._call_openclaw`.
This document is the producer/consumer contract — any change here MUST land with
the corresponding change in `base.py` in the same PR.

## Required Endpoints

### POST /v1/reason

Single round-trip reasoning call. Stateless on the server side — the agent
provides the full system prompt and ticket context on every call.

#### Request

`Content-Type: application/json`

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `engineer` | string | yes | Agent identifier — matches `EngineerAgent.name` (e.g. `"managed_security"`). Used for logging and per-engineer model routing. |
| `prompt` | string | yes | Full user prompt assembled by the agent. May exceed 4 KB. |
| `system_prompt` | string | yes | Agent's system prompt. Empty string is allowed but must still be sent. |
| `fallback_title` | string | yes | Title the agent will fall back to if the LLM omits one. Must be reflected back in `title` when the LLM returns no title. |

Example:

```json
{
  "engineer": "managed_security",
  "prompt": "<full assembled prompt>",
  "system_prompt": "<engineer system prompt>",
  "fallback_title": "Ticket response"
}
```

#### Response (200 OK)

`Content-Type: application/json`

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `action_type` | string | yes | One of: `investigation_plan`, `client_reply`, `playbook`, `documentation`, `escalation`. Unknown values fall back to `investigation_plan` on the consumer. |
| `title` | string | yes | Short human-readable title (<80 chars). Consumer falls back to `fallback_title` if missing or empty. |
| `body_markdown` | string | yes | Deliverable content in Markdown — the actual reply / plan / doc body. Consumer falls back to `""` if missing. |
| `proposed_payload` | object | yes | Action-type-specific payload (recipient + subject for `client_reply`, `doc_target` for `documentation`, `next_steps` array, etc.). Consumer falls back to `{}` if missing. |
| `reasoning` | string | yes | 1–3 sentences on why this is the next-best action. Consumer falls back to `""` if missing. |

Example:

```json
{
  "action_type": "client_reply",
  "title": "Re: TLS cert expiry on portal.example.com",
  "body_markdown": "Hi Anthony,\n\nWe renewed the cert ...",
  "proposed_payload": {
    "to": "anthony@example.com",
    "subject": "Re: TLS cert expiry",
    "next_steps": ["Confirm cert chain in browser", "Close ticket TCK-123"]
  },
  "reasoning": "Cert was renewed by the LE auto-renewal job; the customer just needs confirmation."
}
```

Forward-compatibility: the consumer reads only the five fields above via
`dict.get()` with type-correct defaults. Extra fields are ignored, not errored.

#### Failure modes — distinct error_type per branch

The wire layer is implemented by `HttpxOpenClawClient` in
`infra/loki_handlers/engineers/openclaw_client.py`. Every failure path maps to
exactly one of the `OpenClaw*Error` exception types, and the consumer
(`EngineerAgent._call_openclaw`) maps each exception to a distinct `error_type`
value in the fallback dict. A retry supervisor / dashboard / alert pipeline
branches on `error_type` (and `error_status` when the type is `http_status`).

| Failure | Client exception | Fallback `error_type` | Extra fields | Suggested caller policy |
|---------|------------------|-----------------------|--------------|--------------------------|
| Connection refused / DNS fail / reset | `OpenClawTransportError` | `transport` | — | Backoff + retry (treat as 5xx-class) |
| Request exceeded 30s end-to-end | `OpenClawTimeoutError` | `timeout` | — | Backoff + retry once, then alert |
| Non-2xx response | `OpenClawHTTPError` | `http_status` | `error_status: <int>` | 5xx retry, 4xx surface to operator |
| Response body was not valid JSON | `OpenClawDecodeError` | `decode` | — | Do NOT retry — alert (producer bug) |
| Anything else (client implementation bug) | `Exception` (caught defensively) | `unknown` | — | Surface, do not retry |

200 responses parse the JSON and return the consumer's five-field shape from
`/v1/reason` Response. No `error_type` field is present on success.

The 30s timeout is configured at `HttpxOpenClawClient.__init__(..., timeout=30.0)`.
The producer SHOULD respond — even with a 5xx body or structured error JSON —
within that budget.

## Versioning

The `/v1/` prefix is load-bearing. Breaking changes (renaming a request field,
removing a response field, narrowing an enum) MUST ship under `/v2/`. Adding
new optional response fields is backwards-compatible because the consumer
ignores unknown keys.

## Reference

Producer: external `openclaw` reasoning service (not in this repo).
Wire client: `infra/loki_handlers/engineers/openclaw_client.py::HttpxOpenClawClient`
(owns httpx, maps every failure to an `OpenClaw*Error`).
Consumer: `infra/loki_handlers/engineers/base.py::EngineerAgent._call_openclaw`
(maps each `OpenClaw*Error` to a distinct `error_type` in the fallback dict).
Tests pinning the contract: `infra/loki_handlers/tests/test_engineer_openclaw.py`
(request shape, response defaulting, structured error-path fallback).
