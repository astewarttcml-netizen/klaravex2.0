-- Klaravex Klara AI backend — RustDesk remote-session schema (G34.3)
-- Spec: docs/architecture/ai-remote-session.md §4 + §6
-- Safe to re-run; uses CREATE ... IF NOT EXISTS.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────────────────────────────────────
-- Remote sessions — one row per AI-controlled customer screen session.
-- Consent must be recorded (consent_accepted_at IS NOT NULL) BEFORE any frame
-- is forwarded; the controller refuses to send/recv frames until that gate
-- flips. The recording fields point to the on-disk encrypted H.264 capture.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS klaravex_remote_sessions (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id              text NOT NULL UNIQUE,            -- short hex id used in URLs + audit log
    customer_email          text NOT NULL,
    customer_region         text NOT NULL CHECK (customer_region IN ('us','eu','other')),
    goal                    text NOT NULL,                   -- "fix the customer's WiFi"
    state                   text NOT NULL DEFAULT 'pending_consent'
                            CHECK (state IN (
                                'pending_consent',
                                'pending_connect',
                                'connected',
                                'awaiting_confirm',
                                'executing',
                                'ended_fixed',
                                'ended_failed',
                                'ended_handoff',
                                'ended_killed'
                            )),

    -- Consent (spec §6 + §4 requirement 1)
    consent_text_version    text,
    consent_text            text,
    consent_accepted_at     timestamptz,                     -- NULL = no control allowed
    consent_ip              inet,
    consent_user_agent      text,
    consent_signature_sha256 text,                           -- sha256(consent_text + accepted_at + customer_email)

    -- Recording (spec §4 requirement 3)
    recording_path          text,                            -- /opt/loki-vault/remote_sessions/<sid>.mp4
    recording_encrypted     boolean NOT NULL DEFAULT false,
    recording_size_bytes    bigint,
    recording_started_at    timestamptz,
    recording_closed_at     timestamptz,
    recording_purge_after   timestamptz,                     -- 30 days post close (GDPR)
    recording_purged_at     timestamptz,

    -- Kill switch (spec §4 requirement 4)
    killed                  boolean NOT NULL DEFAULT false,
    killed_at               timestamptz,
    killed_by               text CHECK (killed_by IN (
                                'customer_tray',
                                'customer_hotkey',
                                'server_override',
                                'auto_abort_low_conf',
                                'auto_abort_rejections',
                                'auto_abort_timeout',
                                'session_end'
                            )),
    kill_reason             text,

    started_at              timestamptz NOT NULL DEFAULT now(),
    ended_at                timestamptz,
    outcome                 text CHECK (outcome IN ('fixed','failed','handoff','killed'))
);

CREATE INDEX IF NOT EXISTS ix_klaravex_remote_sessions_customer
    ON klaravex_remote_sessions (customer_email);
CREATE INDEX IF NOT EXISTS ix_klaravex_remote_sessions_state
    ON klaravex_remote_sessions (state);
CREATE INDEX IF NOT EXISTS ix_klaravex_remote_sessions_started
    ON klaravex_remote_sessions (started_at DESC);
-- Purge worker scans for recordings due for deletion (recording_purge_after < now()).
CREATE INDEX IF NOT EXISTS ix_klaravex_remote_sessions_purge
    ON klaravex_remote_sessions (recording_purge_after)
    WHERE recording_path IS NOT NULL AND recording_purged_at IS NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- Hash-chained event log — court-admissible audit trail (spec §6).
-- One row per chain entry. session_id + sequence is the natural key.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS klaravex_remote_session_events (
    id              bigserial PRIMARY KEY,
    session_id      text NOT NULL REFERENCES klaravex_remote_sessions(session_id) ON DELETE CASCADE,
    sequence        int  NOT NULL,
    event_type      text NOT NULL,            -- consent | action_predicted | action_confirmed |
                                              -- action_rejected | action_executed |
                                              -- killswitch_fired | session_end | recording_open |
                                              -- recording_close | transport_attached
    payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
    prev_hash       text NOT NULL,            -- hex sha256 of previous row (or 64 zeros)
    entry_hash      text NOT NULL,            -- hex sha256 of canonical(this entry)
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, sequence)
);

CREATE INDEX IF NOT EXISTS ix_klaravex_remote_session_events_session
    ON klaravex_remote_session_events (session_id, sequence);
CREATE INDEX IF NOT EXISTS ix_klaravex_remote_session_events_type
    ON klaravex_remote_session_events (event_type);
CREATE INDEX IF NOT EXISTS ix_klaravex_remote_session_events_time
    ON klaravex_remote_session_events (occurred_at DESC);

COMMIT;
