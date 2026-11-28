-- EnclaveRAG Phase S3: Async Ingestion Jobs Table, Tenant RLS & Quota Count Function

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    uploaded_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    document_id     UUID REFERENCES documents(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    department      TEXT NOT NULL,
    clearance_level INT  NOT NULL CHECK (clearance_level BETWEEN 1 AND 4),
    filename        TEXT NOT NULL,
    storage_key     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'indexed', 'failed')),
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_org_status
    ON ingestion_jobs (org_id, status, created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO enclave_app;

ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_jobs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ingestion_jobs_tenant_isolation ON ingestion_jobs;
CREATE POLICY ingestion_jobs_tenant_isolation ON ingestion_jobs
    FOR ALL
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid);

-- Returns only the aggregate document count for quota enforcement without exposing rows.
CREATE OR REPLACE FUNCTION org_document_count(p_org_id UUID)
RETURNS INT
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COUNT(*)::int FROM documents WHERE org_id = p_org_id;
$$;

REVOKE ALL ON FUNCTION org_document_count(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION org_document_count(UUID) TO enclave_app;
