-- ============================================================
-- 02-permissions.sql  (Klaravex2.0 / US repoint)
-- Grants for vault-mcp on schema vault in database klaravex.
-- Run AFTER 01-schema.sql as a role that can CREATE ROLE / GRANT.
--
-- For interim USA cutover, vault-mcp may connect as klaravexadmin
-- (already has full access). This file creates the least-privilege
-- service role when you are ready to drop admin creds from the
-- vault-mcp container.
-- ============================================================

-- Optional: create service role (skip if using klaravexadmin interim)
-- Password must be set manually:
--   CREATE ROLE vault_sync_service LOGIN PASSWORD '...';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vault_sync_service') THEN
        RAISE NOTICE 'vault_sync_service role missing — create it manually with a password, then re-run grants below';
    END IF;
END;
$$;

GRANT CONNECT ON DATABASE klaravex TO vault_sync_service;
GRANT USAGE ON SCHEMA vault TO vault_sync_service;
GRANT SELECT, INSERT, UPDATE ON vault.vault_embeddings TO vault_sync_service;
GRANT SELECT, INSERT, UPDATE ON vault.note_submissions TO vault_sync_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON vault.memory_index TO vault_sync_service;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA vault TO vault_sync_service;
ALTER DEFAULT PRIVILEGES IN SCHEMA vault
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vault_sync_service;
