-- ============================================================
-- 01-schema.sql  (Klaravex2.0 / US repoint)
-- Klara AI Vault MCP tables in schema `vault`
-- Target DB: Azure klaravex-db-r2 / database klaravex
--
-- WHY schema `vault` (not public / klaravex):
--   klaravex.note_submissions already exists as the RARV journal queue
--   (bigint id, submission_status enum, vault_path, commit_sha, …).
--   Vault MCP's note_submissions is a different UUID embedding queue.
--   Isolating into schema `vault` is the ownership boundary —
--   RARV owns klaravex.*; vault-mcp owns vault.*.
--
-- Requires: pgvector, pgcrypto (PostgreSQL 14+)
-- Apply:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 01-schema.sql
-- ============================================================

CREATE SCHEMA IF NOT EXISTS vault;

-- Enable extensions in public (Azure-friendly; schemas can use them)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

SET search_path TO vault, public;

-- -----------------------------------------------------------
-- vault_embeddings
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS vault.vault_embeddings (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    note_path       TEXT        NOT NULL UNIQUE,
    note_title      TEXT,
    content         TEXT        NOT NULL,
    content_hash    TEXT        NOT NULL,
    embedding       vector(768),
    metadata        JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS vault_embeddings_embedding_cos_idx
    ON vault.vault_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS vault_embeddings_note_path_idx
    ON vault.vault_embeddings (note_path);

CREATE INDEX IF NOT EXISTS vault_embeddings_content_hash_idx
    ON vault.vault_embeddings (content_hash);

CREATE INDEX IF NOT EXISTS vault_embeddings_metadata_idx
    ON vault.vault_embeddings USING GIN (metadata jsonb_path_ops);

-- -----------------------------------------------------------
-- note_submissions  (vault-mcp embedding queue — NOT RARV)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS vault.note_submissions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    content         TEXT        NOT NULL,
    metadata        JSONB       NOT NULL DEFAULT '{}',
    status          TEXT        NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS note_submissions_status_created_idx
    ON vault.note_submissions (status, created_at)
    WHERE status IN ('pending', 'processing');

-- -----------------------------------------------------------
-- memory_index
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS vault.memory_index (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    key             TEXT        NOT NULL UNIQUE,
    value           TEXT        NOT NULL,
    category        TEXT,
    tags            TEXT[]      NOT NULL DEFAULT '{}',
    source_note_path TEXT       REFERENCES vault.vault_embeddings(note_path) ON DELETE SET NULL,
    confidence      FLOAT       NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS memory_index_category_idx
    ON vault.memory_index (category);

CREATE INDEX IF NOT EXISTS memory_index_tags_idx
    ON vault.memory_index USING GIN (tags);

-- -----------------------------------------------------------
-- updated_at auto-trigger
-- -----------------------------------------------------------
CREATE OR REPLACE FUNCTION vault.fn_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_vault_embeddings_updated_at'
    ) THEN
        CREATE TRIGGER trg_vault_embeddings_updated_at
            BEFORE UPDATE ON vault.vault_embeddings
            FOR EACH ROW EXECUTE FUNCTION vault.fn_set_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_memory_index_updated_at'
    ) THEN
        CREATE TRIGGER trg_memory_index_updated_at
            BEFORE UPDATE ON vault.memory_index
            FOR EACH ROW EXECUTE FUNCTION vault.fn_set_updated_at();
    END IF;
END;
$$;
