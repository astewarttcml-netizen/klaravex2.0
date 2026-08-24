-- Klaravex Loki backend — call transcripts table (T6.13.11)
-- Safe to re-run; uses CREATE ... IF NOT EXISTS.

BEGIN;

CREATE TABLE IF NOT EXISTS klaravex_call_transcripts (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  call_sid         TEXT NOT NULL UNIQUE,
  from_number      TEXT,
  to_number        TEXT,
  duration_seconds INT,
  recording_url    TEXT,
  transcript       TEXT,
  summary          TEXT,
  outcome          TEXT CHECK (outcome IN ('resolved','escalated','abandoned','payment_completed')),
  ticket_id        UUID REFERENCES klaravex_tickets(id),
  created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_transcripts_call_sid    ON klaravex_call_transcripts (call_sid);
CREATE INDEX IF NOT EXISTS idx_call_transcripts_created_at  ON klaravex_call_transcripts (created_at);

COMMIT;
