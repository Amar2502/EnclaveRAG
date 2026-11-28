-- EnclaveRAG Phase S2: Department ABAC + Clearance RLS Policies
-- L1/L2 docs remain company-wide; L3/L4 docs require matching department, 'General', or Org Admin.

CREATE OR REPLACE FUNCTION rls_can_access_doc(
    doc_org_id UUID,
    doc_clearance INT,
    doc_department TEXT
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT
        doc_org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND doc_clearance <= COALESCE(NULLIF(current_setting('app.clearance_level', true), '')::int, 0)
        AND (
            doc_clearance <= 2
            OR doc_department = 'General'
            OR doc_department = NULLIF(current_setting('app.department', true), '')
            OR COALESCE(NULLIF(current_setting('app.is_org_admin', true), '')::boolean, false)
        );
$$;

-- Documents policies (SELECT / INSERT / UPDATE / DELETE)
DROP POLICY IF EXISTS documents_zero_trust_select ON documents;
CREATE POLICY documents_zero_trust_select ON documents
    FOR SELECT
    USING (rls_can_access_doc(org_id, clearance_level, department));

DROP POLICY IF EXISTS documents_zero_trust_insert ON documents;
CREATE POLICY documents_zero_trust_insert ON documents
    FOR INSERT
    WITH CHECK (rls_can_access_doc(org_id, clearance_level, department));

DROP POLICY IF EXISTS documents_zero_trust_update ON documents;
CREATE POLICY documents_zero_trust_update ON documents
    FOR UPDATE
    USING (rls_can_access_doc(org_id, clearance_level, department))
    WITH CHECK (rls_can_access_doc(org_id, clearance_level, department));

DROP POLICY IF EXISTS documents_zero_trust_delete ON documents;
CREATE POLICY documents_zero_trust_delete ON documents
    FOR DELETE
    USING (rls_can_access_doc(org_id, clearance_level, department));

-- Document Chunks policies (SELECT / INSERT / DELETE via live parent document check)
DROP POLICY IF EXISTS chunks_zero_trust_select ON document_chunks;
CREATE POLICY chunks_zero_trust_select ON document_chunks
    FOR SELECT
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND EXISTS (
            SELECT 1
            FROM documents d
            WHERE d.id = document_chunks.document_id
              AND rls_can_access_doc(d.org_id, d.clearance_level, d.department)
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
              AND rls_can_access_doc(d.org_id, d.clearance_level, d.department)
        )
    );

DROP POLICY IF EXISTS chunks_zero_trust_delete ON document_chunks;
CREATE POLICY chunks_zero_trust_delete ON document_chunks
    FOR DELETE
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND EXISTS (
            SELECT 1
            FROM documents d
            WHERE d.id = document_chunks.document_id
              AND rls_can_access_doc(d.org_id, d.clearance_level, d.department)
        )
    );
