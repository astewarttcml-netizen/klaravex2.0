-- Klaravex Klara AI backend — Phase 6 core schema
-- Target: shared Cloud86 Postgres (lend.your-database.de:5432/dediviac_db0)
-- Tables prefixed klaravex_ (per CLAUDE.md tenancy isolation).
-- Safe to re-run; uses CREATE ... IF NOT EXISTS.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────────────────────────────────────
-- Clients (lightweight registry; populated from Stripe customers + intake)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS klaravex_clients (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           text NOT NULL UNIQUE,
    name            text,
    segment         text NOT NULL CHECK (segment IN ('consumer','b2b')),
    stripe_customer_id text,
    company         text,
    phone           text,
    timezone        text DEFAULT 'America/New_York',
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_klaravex_clients_segment ON klaravex_clients (segment);
CREATE INDEX IF NOT EXISTS ix_klaravex_clients_stripe ON klaravex_clients (stripe_customer_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Tickets — every chat + escalation + workflow event lands here.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS klaravex_tickets (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid REFERENCES klaravex_clients(id) ON DELETE SET NULL,
    client_email    text NOT NULL,            -- denormalized for fast lookup
    severity        text NOT NULL CHECK (severity IN ('low','standard','high','emergency')),
    status          text NOT NULL CHECK (status IN ('open','in_progress','waiting_client','resolved','closed','escalated')),
    assignee        text,                     -- 'loki' or operator email
    source          text NOT NULL,            -- 'chat','intake_consumer','intake_b2b','stripe','smartlead','calendly','workflow'
    archetype       text,                     -- A1..A8
    sku             text,                     -- product SKU when known
    workflow_state  text,                     -- current YAML state
    subject         text NOT NULL,
    summary         text,
    resolution      text,
    history         jsonb NOT NULL DEFAULT '[]'::jsonb,   -- append-only log of events
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    resolved_at     timestamptz
);
CREATE INDEX IF NOT EXISTS ix_klaravex_tickets_client ON klaravex_tickets (client_email);
CREATE INDEX IF NOT EXISTS ix_klaravex_tickets_status ON klaravex_tickets (status);
CREATE INDEX IF NOT EXISTS ix_klaravex_tickets_severity ON klaravex_tickets (severity);
CREATE INDEX IF NOT EXISTS ix_klaravex_tickets_created ON klaravex_tickets (created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Portal magic-link sessions
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS klaravex_portal_tokens (
    token_hash      bytea PRIMARY KEY,                -- sha256(plaintext)
    email           text NOT NULL,
    purpose         text NOT NULL DEFAULT 'login',    -- 'login' | 'session'
    expires_at      timestamptz NOT NULL,
    used_at         timestamptz,
    ip              inet,
    user_agent      text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_klaravex_portal_tokens_email ON klaravex_portal_tokens (email);
CREATE INDEX IF NOT EXISTS ix_klaravex_portal_tokens_expires ON klaravex_portal_tokens (expires_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- Block-hour ledger (A7)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS klaravex_hours_ledger (
    id              bigserial PRIMARY KEY,
    client_id       uuid REFERENCES klaravex_clients(id) ON DELETE CASCADE,
    client_email    text NOT NULL,
    delta_hours     numeric(6,2) NOT NULL,            -- +purchase, -consumption
    reason          text NOT NULL,                    -- 'purchase' | 'consumption' | 'adjustment'
    ticket_id       uuid REFERENCES klaravex_tickets(id) ON DELETE SET NULL,
    sku             text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_klaravex_hours_ledger_email ON klaravex_hours_ledger (client_email);

-- ─────────────────────────────────────────────────────────────────────────────
-- Escalations — anything Klara AI couldn't resolve
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS klaravex_escalations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       uuid REFERENCES klaravex_tickets(id) ON DELETE CASCADE,
    client_email    text NOT NULL,
    severity        text NOT NULL,
    summary         text NOT NULL,
    attempted       text,                             -- what Klara AI tried
    recommended     text,                             -- recommended next step
    delivered_via   jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {telegram: bool, email: bool, errors: []}
    acknowledged_at timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_klaravex_escalations_ack ON klaravex_escalations (acknowledged_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- KB chunks — chunked + embedded knowledge-base content
-- Note: keeps embeddings as float4[] to avoid hard dependency on pgvector;
-- semantic search falls back to text-search if embeddings absent.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS klaravex_kb_chunks (
    id              bigserial PRIMARY KEY,
    source_url      text NOT NULL,
    source_title    text NOT NULL,
    chunk_index     int  NOT NULL,
    content         text NOT NULL,
    content_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    embedding       real[],                           -- nullable; populated when embedding provider available
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_url, chunk_index)
);
CREATE INDEX IF NOT EXISTS ix_klaravex_kb_chunks_tsv ON klaravex_kb_chunks USING gin (content_tsv);

COMMIT;
