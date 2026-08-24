#!/bin/bash
# ============================================================
# init-permissions.sh
# Runs inside the postgres init container to create the
# vault_sync_service user and grant table privileges.
# Executed automatically by Docker's entrypoint on first start.
# ============================================================
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create service user if it doesn't exist
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vault_sync_service') THEN
            CREATE USER vault_sync_service
                WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                CONNECTION LIMIT 20
                PASSWORD '${VAULT_SYNC_PASSWORD}';
        ELSE
            ALTER USER vault_sync_service WITH PASSWORD '${VAULT_SYNC_PASSWORD}';
        END IF;
    END;
    \$\$;

    -- Grants
    GRANT CONNECT ON DATABASE loki_vault TO vault_sync_service;
    GRANT USAGE ON SCHEMA public TO vault_sync_service;
    GRANT SELECT, INSERT, UPDATE ON vault_embeddings  TO vault_sync_service;
    GRANT SELECT, INSERT, UPDATE ON note_submissions  TO vault_sync_service;
    GRANT SELECT, INSERT, UPDATE, DELETE ON memory_index TO vault_sync_service;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO vault_sync_service;

    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE ON TABLES TO vault_sync_service;
EOSQL

echo "[init-permissions] vault_sync_service user configured successfully."
