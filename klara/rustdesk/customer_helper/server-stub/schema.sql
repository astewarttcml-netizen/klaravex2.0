-- customer_helper_tokens — production schema for the token redeem table.
-- Lives in the Cloud86 Postgres `klaravex_` schema (see CLAUDE.md infra).
--
-- Migration filename when productionized:
--   infra/migrations/2026XXXX_customer_helper_tokens.sql

CREATE SCHEMA IF NOT EXISTS klaravex;

CREATE TABLE IF NOT EXISTS klaravex.customer_helper_tokens (
    -- sha256(token) — NEVER store the token itself; we only compare hashes.
    token_sha256        BYTEA       PRIMARY KEY,

    -- Stripe payment intent that triggered token issuance. Token cannot be
    -- redeemed until payment_confirmed is true (set by Stripe webhook).
    stripe_payment_id   TEXT        NOT NULL,
    payment_confirmed   BOOLEAN     NOT NULL DEFAULT FALSE,

    -- The 9-digit RustDesk ID the operator will dial. We generate this
    -- server-side at issue time so we can pre-register it with hbbs.
    customer_session_id TEXT        NOT NULL,
    -- One-session password baked into the customer's RustDesk2.toml.
    session_password    TEXT        NOT NULL,

    -- Per-session metadata shown in the helper UI.
    display_topic       TEXT,
    operator_label      TEXT,

    -- Lifecycle.
    issued_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,
    redeemed_at         TIMESTAMPTZ,
    ended_at            TIMESTAMPTZ,

    -- Audit trail.
    customer_email      TEXT        NOT NULL,
    issued_by_agent_id  TEXT        NOT NULL DEFAULT 'klara-vapi',
    note_submission_id  BIGINT      -- FK into note_submissions(id), populated by the issuer
);

CREATE INDEX IF NOT EXISTS idx_cht_expires_at
    ON klaravex.customer_helper_tokens (expires_at)
    WHERE redeemed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_cht_customer_email
    ON klaravex.customer_helper_tokens (customer_email);

-- Once a session ends, retain the row for 30 days then garbage-collect.
-- (Implemented as a nightly cron in infra/cron/, not as a partition.)

-- ────────────────────────────────────────────────────────────────────────
-- Replay protection: a single token can only flip from
-- redeemed_at IS NULL → redeemed_at = now() exactly once. The redeem API
-- uses:
--
--   UPDATE klaravex.customer_helper_tokens
--      SET redeemed_at = now()
--    WHERE token_sha256 = $1
--      AND payment_confirmed = TRUE
--      AND redeemed_at IS NULL
--      AND expires_at > now()
--   RETURNING customer_session_id, session_password,
--            expires_at, display_topic, operator_label;
--
-- If 0 rows are returned, redeem returns 410 Gone.
-- ────────────────────────────────────────────────────────────────────────
