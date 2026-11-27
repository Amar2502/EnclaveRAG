-- EnclaveRAG Phase 1: Core Schema

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS organizations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email            TEXT NOT NULL UNIQUE,
    full_name        TEXT NOT NULL,
    role_title       TEXT NOT NULL,
    department       TEXT NOT NULL,
    clearance_level  INT  NOT NULL CHECK (clearance_level BETWEEN 1 AND 4),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    department          TEXT NOT NULL,
    clearance_level     INT  NOT NULL CHECK (clearance_level BETWEEN 1 AND 4),
    classification_tag  TEXT NOT NULL,
    source_uri          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_org_clearance
    ON documents (org_id, clearance_level);

CREATE TABLE IF NOT EXISTS document_chunks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INT  NOT NULL,
    content      TEXT NOT NULL,
    embedding    VECTOR(768) NOT NULL,
    fts          TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_org_doc ON document_chunks (org_id, document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_fts ON document_chunks USING GIN (fts);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS audit_logs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            UUID NOT NULL,
    user_id           UUID NOT NULL,
    user_clearance    INT  NOT NULL,
    query_text        TEXT NOT NULL,
    retrieved_doc_ids UUID[] NOT NULL DEFAULT '{}',
    latency_ms        INT  NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
