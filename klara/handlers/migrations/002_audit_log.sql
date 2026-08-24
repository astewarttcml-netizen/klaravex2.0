-- Klaravex Loki backend — audit log table (T8.12)
-- Safe to re-run; uses CREATE ... IF NOT EXISTS.

BEGIN;

CREATE TABLE IF NOT EXISTS klaravex_loki_audit (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  timestamp        TIMESTAMPTZ DEFAULT NOW(),
  method           TEXT,
  path             TEXT,
  client_email     TEXT,
  request_summary  TEXT,
  response_status  INT,
  redacted         BOOLEAN DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp    ON klaravex_loki_audit (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_client_email ON klaravex_loki_audit (client_email);
CREATE INDEX IF NOT EXISTS idx_audit_path         ON klaravex_loki_audit (path);

COMMIT;
