-- Phase UX-4: Customizable org clearance labels & password reset tokens

ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS clearance_labels JSONB NOT NULL DEFAULT '{
        "1": "Company-Wide",
        "2": "Internal",
        "3": "Dept Confidential",
        "4": "Executive Only"
    }'::jsonb;

CREATE TABLE IF NOT EXISTS password_resets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_password_resets_token_hash ON password_resets (token_hash);

GRANT SELECT, INSERT, UPDATE, DELETE ON password_resets TO enclave_app;

ALTER TABLE password_resets ENABLE ROW LEVEL SECURITY;
ALTER TABLE password_resets FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS password_resets_tenant_isolation ON password_resets;
CREATE POLICY password_resets_tenant_isolation ON password_resets
    USING (org_id = app.current_org_id())
    WITH CHECK (org_id = app.current_org_id());

CREATE OR REPLACE FUNCTION app.consume_password_reset(p_token_hash TEXT)
RETURNS TABLE(reset_id UUID, org_id UUID, user_id UUID, expires_at TIMESTAMPTZ, used_at TIMESTAMPTZ)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, app
AS $$
    SELECT id, org_id, user_id, expires_at, used_at
    FROM password_resets
    WHERE token_hash = p_token_hash
    LIMIT 1;
$$;

REVOKE ALL ON FUNCTION app.consume_password_reset(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.consume_password_reset(TEXT) TO enclave_app;
