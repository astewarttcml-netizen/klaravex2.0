-- Klaravex Loki backend — portal OAuth linked accounts (T14.1)
-- Adds Google + Microsoft OAuth alongside the existing magic-link login.
-- Spec: HANDOFF-2026-06-11-19 §A1.
-- Safe to re-run; uses CREATE ... IF NOT EXISTS.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- Linked OAuth accounts — one row per (provider, provider_sub) pair.
-- A single portal email may have multiple linked providers (e.g. both Google
-- and Microsoft) — they're keyed by provider_sub (issuer's stable user id),
-- never by email, because providers let users change the email on the account.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS klaravex_portal_linked_accounts (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email               text NOT NULL,                  -- portal canonical email (lowercased)
    provider            text NOT NULL CHECK (provider IN ('google','microsoft')),
    provider_sub        text NOT NULL,                  -- issuer-stable user id (oidc 'sub')
    provider_email      text,                           -- email at the provider (may differ)
    provider_name       text,                           -- display name from id_token
    id_token_iss        text,                           -- issuer (for audit)
    linked_at           timestamptz NOT NULL DEFAULT now(),
    last_login_at       timestamptz,
    UNIQUE (provider, provider_sub)
);
CREATE INDEX IF NOT EXISTS ix_klaravex_portal_linked_accounts_email
    ON klaravex_portal_linked_accounts (email);

-- ─────────────────────────────────────────────────────────────────────────────
-- OAuth state — short-lived CSRF/PKCE/nonce store. One row per /oauth/start.
-- Cleaned up by the verify handler (single-use) or by background sweeper.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS klaravex_portal_oauth_states (
    state               text PRIMARY KEY,               -- 32-byte url-safe token
    provider            text NOT NULL CHECK (provider IN ('google','microsoft')),
    code_verifier       text NOT NULL,                  -- PKCE verifier (S256)
    nonce               text NOT NULL,                  -- id_token nonce
    return_to           text,                           -- post-login redirect (whitelisted)
    expires_at          timestamptz NOT NULL,
    used_at             timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_klaravex_portal_oauth_states_expires
    ON klaravex_portal_oauth_states (expires_at);

COMMIT;
