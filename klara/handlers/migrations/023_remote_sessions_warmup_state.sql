-- Klaravex Klara AI backend — RustDesk remote-session warmup persistence (G34/iter-44)
-- Spec: docs/architecture/ai-remote-session.md §4 + the iter-37→43 producer-side thread.
-- Safe to re-run; uses ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
--
-- WHY: iter-37→43 wired the producer side of Pattern 19 (frame pump runs on
-- FINAL transport, voice tool schedules a background warmup that resolves it).
-- The warmup's terminal state (skipped_stub / aborted_killswitch / completed /
-- failed) is currently captured ONLY in the in-memory HashChainAuditLog. After
-- SessionManager.drop() — i.e. after end_rustdesk_session returns — that
-- in-memory state is gone, and post-mortem queries against
-- klaravex_remote_sessions see no warmup outcome.
--
-- WHAT: add 4 columns to klaravex_remote_sessions that mirror the terminal
-- warmup audit row's payload. RemoteSession.warmup_state() continues to be
-- the source of truth for live sessions; the new columns are the post-mortem
-- view that survives SessionManager.drop().
--
-- DEPLOY-SAFE BEFORE APPLY: the iter-44 _warmup_transport persistence call
-- catches asyncpg.UndefinedColumnError and falls back to in-memory-only.
-- So the code change can ship to staging BEFORE this migration runs without
-- breaking any session.

BEGIN;

-- iter-44 idempotent ADD COLUMN — safe to re-run.
ALTER TABLE klaravex_remote_sessions
    ADD COLUMN IF NOT EXISTS warmup_state          text
        CHECK (warmup_state IS NULL OR warmup_state IN (
            'skipped_stub',
            'aborted_killswitch',
            'completed',
            'failed'
        )),
    ADD COLUMN IF NOT EXISTS warmup_completed_at   timestamptz,
    ADD COLUMN IF NOT EXISTS warmup_error_type     text,
    ADD COLUMN IF NOT EXISTS warmup_error_message  text;
-- warmup_error_message is intentionally untyped (no length cap at the DB
-- level) — the application-side truncation budget (_AUDIT_ERROR_MAX_CHARS
-- = 512 chars in voice_tools.py) is the load-bearing guard. Migration
-- 099 (or whichever lands first) MAY add a CHECK (char_length(...) <= 1024)
-- once the application contract has soaked.

-- Index for the post-mortem dashboard query: "all sessions where warmup
-- failed in the last 24h, group by error_type". Partial index keeps it
-- small — only the failure subset is interesting for alerts.
CREATE INDEX IF NOT EXISTS ix_klaravex_remote_sessions_warmup_failed
    ON klaravex_remote_sessions (warmup_state, started_at DESC)
    WHERE warmup_state = 'failed';

-- Index for "show me everything not in a terminal warmup state and not
-- ended" — the live operations view. The warmup_state IS NULL case is
-- legacy rows (pre-iter-44) plus rows where the warmup hasn't terminated
-- yet. Index lets the ops dashboard run cheap polls.
CREATE INDEX IF NOT EXISTS ix_klaravex_remote_sessions_warmup_pending
    ON klaravex_remote_sessions (started_at DESC)
    WHERE warmup_state IS NULL AND ended_at IS NULL;

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- ROLLBACK (manual, NOT idempotent — only run if you really need to)
-- ─────────────────────────────────────────────────────────────────────────────
-- BEGIN;
--   DROP INDEX IF EXISTS ix_klaravex_remote_sessions_warmup_pending;
--   DROP INDEX IF EXISTS ix_klaravex_remote_sessions_warmup_failed;
--   ALTER TABLE klaravex_remote_sessions
--       DROP COLUMN IF EXISTS warmup_error_message,
--       DROP COLUMN IF EXISTS warmup_error_type,
--       DROP COLUMN IF EXISTS warmup_completed_at,
--       DROP COLUMN IF EXISTS warmup_state;
-- COMMIT;
--
-- Note: rolling back DROPs the columns. Any code path that has been
-- updated to write to them WILL ERROR on UndefinedColumnError. Revert
-- the iter-44 voice_tools.py / remote_sessions.py changes BEFORE the
-- rollback runs, or the running FastAPI worker will start emitting
-- warmup_persist_failed audit rows until restart.
