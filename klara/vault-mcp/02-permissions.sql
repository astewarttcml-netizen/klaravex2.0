-- ============================================================
-- 02-permissions.sql
-- Klara AI SecondBrain: Service user + least-privilege grants
-- Run this AFTER 01-schema.sql, as superuser (postgres).
-- The VAULT_SYNC_PASSWORD value is substituted by docker-compose
-- via the POSTGRES_VAULT_SYNC_PASSWORD env var using envsubst,
-- OR you can run this manually with the password substituted.
-- ============================================================

-- Create the application service user
-- Password is set via POSTGRES_VAULT_SYNC_PASSWORD env var.
-- In Docker init scripts, this file is processed by envsubst before execution.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vault_sync_service') THEN
        CREATE USER vault_sync_service WITH
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            CONNECTION LIMIT 20
            PASSWORD :'VAULT_SYNC_PASSWORD';
    ELSE
        ALTER USER vault_sync_service WITH PASSWORD :'VAULT_SYNC_PASSWORD';
    END IF;
END;
$$;

-- Database-level access
GRANT CONNECT ON DATABASE loki_vault TO vault_sync_service;

-- Schema access
GRANT USAGE ON SCHEMA public TO vault_sync_service;

-- Table-level grants (principle of least privilege)
GRANT SELECT, INSERT, UPDATE ON vault_embeddings   TO vault_sync_service;
GRANT SELECT, INSERT, UPDATE ON note_submissions   TO vault_sync_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON memory_index TO vault_sync_service;

-- Sequence access (for gen_random_uuid() via pgcrypto, not needed, but belt+suspenders)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO vault_sync_service;

-- Ensure future tables in public schema are also accessible
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO vault_sync_service;

-- Verify (expected output: vault_sync_service with appropriate privileges)
-- SELECT grantee, table_name, privilege_type
-- FROM information_schema.role_table_grants
-- WHERE grantee = 'vault_sync_service'
-- ORDER BY table_name, privilege_type;
