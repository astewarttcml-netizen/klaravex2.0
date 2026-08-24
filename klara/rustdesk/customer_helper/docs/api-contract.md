# API Contract — `/api/customer-helper/*`

Authoritative contract between the customer helper (G34.2) and the
Klaravex API (`infra/main.py`). Production wiring is OUT OF SCOPE for
G34.2 — but the helper depends on this shape, so it is pinned here.

## `POST /api/customer-helper/redeem/:token`

### Request

- Path param `:token` — opaque, ≥20 chars, ≤128 chars, URL-safe base64.
- No request body.
- No request auth — the token IS the auth.

### Response — `200 OK`

```json
{
  "customer_session_id": "942 851 037",
  "session_password": "Xa39kQwLpRm2vBnD",
  "expires_at": "2026-06-12T18:42:00Z",
  "display_topic": "macOS Mail won't send",
  "operator_label": "Klara (AI)"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `customer_session_id` | string | yes | 9-digit RustDesk ID. Server-generated, pre-registered with hbbs. |
| `session_password` | string | yes | ≥8 char alphanumeric. Helper bakes into `RustDesk2.toml`. |
| `expires_at` | string (RFC3339) | yes | TTL. Helper refuses to launch RustDesk if past. |
| `display_topic` | string | no | Shown in indicator subtitle. Server-trusted, customer-visible — keep short. |
| `operator_label` | string | no | Defaults to "Klara (AI)" when unset. |

### Response — `404 Not Found`

```json
{ "error": "unknown token" }
```

Token has never been issued. Helper shows: *"This support link is not
valid. Please check the email Klaravex sent you."*

### Response — `410 Gone`

```json
{ "error": "token already redeemed" }
```

or

```json
{ "error": "token expired" }
```

Helper shows: *"This support link has already been used or has expired."*

### Response — `5xx`

Helper retries 3× with exponential backoff (500ms → 1s → 2s), then
surfaces the body. Customer is told to email `support@klaravex.{com,de}`.

## Lifecycle invariants

1. **Single redemption.** Once a token's `redeemed_at` is non-null,
   subsequent redeems return 410. Enforced by the `UPDATE … RETURNING`
   pattern in `server-stub/schema.sql`.
2. **Payment-gated.** A token cannot be redeemed until
   `payment_confirmed = true` is set by the Stripe webhook. Without
   this, redeem returns 410 (we DO NOT leak "exists but not paid").
3. **Server-generated session ID.** The customer's RustDesk ID is
   chosen by Klaravex at issuance time and pre-registered with hbbs so
   the operator can dial it without round-tripping.
4. **TTL bound by service tier.**
   - Foundation: 30 min
   - Assurance: 60 min
   - Directive: 120 min
   The helper does NOT enforce — it trusts `expires_at`.
5. **Note submission.** Every redeem MUST produce a `note_submissions`
   row per Klaravex Memory Policy (topic: `api-integration`).

## Out-of-scope (handled elsewhere)

- Token issuance (`POST /api/customer-helper/issue`) — invoked by Klara
  (the voice agent) when she decides a remote session is warranted, NOT
  by the customer.
- Stripe webhook flipping `payment_confirmed = true` — see
  `infra/loki_handlers/stripe_webhook.py` (G33).
- Operator-side connect (Klara AI dials the customer ID) — see
  `infra/rustdesk_controller/session.py` (G34.1).

## Versioning

The path is unversioned for v1. When breaking changes land, add a
`/v2/` prefix and ship a parallel helper version. The helper sends
`User-Agent: klaravex-helper/<semver>` so the server can negotiate.
