-- EnclaveRAG Phase 1: Zero-Trust Row-Level Security (RLS) Policies

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'enclave_app') THEN
        CREATE ROLE enclave_app LOGIN PASSWORD 'enclave_dev_password'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO enclave_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO enclave_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO enclave_app;

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS documents_zero_trust_select ON documents;
CREATE POLICY documents_zero_trust_select ON documents
    FOR SELECT
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND clearance_level <= COALESCE(NULLIF(current_setting('app.clearance_level', true), '')::int, 0)
    );

DROP POLICY IF EXISTS documents_zero_trust_insert ON documents;
CREATE POLICY documents_zero_trust_insert ON documents
    FOR INSERT
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND clearance_level <= COALESCE(NULLIF(current_setting('app.clearance_level', true), '')::int, 0)
    );

DROP POLICY IF EXISTS documents_zero_trust_update ON documents;
CREATE POLICY documents_zero_trust_update ON documents
    FOR UPDATE
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND clearance_level <= COALESCE(NULLIF(current_setting('app.clearance_level', true), '')::int, 0)
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND clearance_level <= COALESCE(NULLIF(current_setting('app.clearance_level', true), '')::int, 0)
    );

DROP POLICY IF EXISTS documents_zero_trust_delete ON documents;
CREATE POLICY documents_zero_trust_delete ON documents
    FOR DELETE
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND clearance_level <= COALESCE(NULLIF(current_setting('app.clearance_level', true), '')::int, 0)
    );

DROP POLICY IF EXISTS chunks_zero_trust_select ON document_chunks;
CREATE POLICY chunks_zero_trust_select ON document_chunks
    FOR SELECT
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND EXISTS (
            SELECT 1
            FROM documents d
            WHERE d.id = document_chunks.document_id
              AND d.org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
              AND d.clearance_level <= COALESCE(NULLIF(current_setting('app.clearance_level', true), '')::int, 0)
        )
    );

DROP POLICY IF EXISTS chunks_zero_trust_insert ON document_chunks;
CREATE POLICY chunks_zero_trust_insert ON document_chunks
    FOR INSERT
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND EXISTS (
            SELECT 1
            FROM documents d
            WHERE d.id = document_chunks.document_id
              AND d.org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
              AND d.clearance_level <= COALESCE(NULLIF(current_setting('app.clearance_level', true), '')::int, 0)
        )
    );

DROP POLICY IF EXISTS audit_logs_tenant_isolation ON audit_logs;
CREATE POLICY audit_logs_tenant_isolation ON audit_logs
    FOR ALL
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid);
