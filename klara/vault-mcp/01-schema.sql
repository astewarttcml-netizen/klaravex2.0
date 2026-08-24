-- ============================================================
-- 01-schema.sql
-- Klara AI SecondBrain: PostgreSQL schema initialization
-- Requires: pgvector extension, PostgreSQL 14+
-- ============================================================

-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()

-- -----------------------------------------------------------
-- vault_embeddings
-- Primary store: note content + semantic embedding vector
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS vault_embeddings (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    note_path       TEXT        NOT NULL UNIQUE,          -- relative path: "Projects/Klara AI/overview.md"
    note_title      TEXT,                                 -- human-readable title
    content         TEXT        NOT NULL,                 -- full note text
    content_hash    TEXT        NOT NULL,                 -- SHA-256 of content (dedup / change detection)
    embedding       vector(768),                          -- nomic-embed-text via Ollama (768-dim)
    metadata        JSONB       NOT NULL DEFAULT '{}',   -- arbitrary tags, source, links, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- IVFFlat index for ANN search (cosine distance)
-- Tune lists = sqrt(row_count) once you have data; 100 is a safe starting value.
CREATE INDEX IF NOT EXISTS vault_embeddings_embedding_cos_idx
    ON vault_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS vault_embeddings_note_path_idx
    ON vault_embeddings (note_path);

CREATE INDEX IF NOT EXISTS vault_embeddings_content_hash_idx
    ON vault_embeddings (content_hash);

CREATE INDEX IF NOT EXISTS vault_embeddings_metadata_idx
    ON vault_embeddings USING GIN (metadata jsonb_path_ops);

-- -----------------------------------------------------------
-- note_submissions
-- Async queue: notes received via vault_submit_note tool
-- Background worker drains this into vault_embeddings
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS note_submissions (
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
    ON note_submissions (status, created_at)
    WHERE status IN ('pending', 'processing');  -- partial index: only active rows

-- -----------------------------------------------------------
-- memory_index
-- Structured key-value memory layer (facts, preferences, context)
-- Optionally linked back to source note in vault_embeddings
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_index (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    key             TEXT        NOT NULL UNIQUE,
    value           TEXT        NOT NULL,
    category        TEXT,                                 -- e.g. "preference", "fact", "project"
    tags            TEXT[]      NOT NULL DEFAULT '{}',
    source_note_path TEXT       REFERENCES vault_embeddings(note_path) ON DELETE SET NULL,
    confidence      FLOAT       NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS memory_index_category_idx
    ON memory_index (category);

CREATE INDEX IF NOT EXISTS memory_index_tags_idx
    ON memory_index USING GIN (tags);

-- -----------------------------------------------------------
-- updated_at auto-trigger
-- -----------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_set_updated_at()
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
            BEFORE UPDATE ON vault_embeddings
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_memory_index_updated_at'
    ) THEN
        CREATE TRIGGER trg_memory_index_updated_at
            BEFORE UPDATE ON memory_index
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
    END IF;
END;
$$;
