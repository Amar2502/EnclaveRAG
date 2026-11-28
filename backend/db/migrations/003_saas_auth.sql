-- EnclaveRAG Phase S1: SaaS Multi-Tenant Auth, Invitations & Usage Metadata

ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS plan_tier TEXT NOT NULL DEFAULT 'free'
        CHECK (plan_tier IN ('free', 'pro', 'enterprise')),
    ADD COLUMN IF NOT EXISTS max_documents INT NOT NULL DEFAULT 50,
    ADD COLUMN IF NOT EXISTS monthly_query_limit INT NOT NULL DEFAULT 500;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_hash TEXT,
    ADD COLUMN IF NOT EXISTS is_org_admin BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS token_version INT NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS invitations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email            TEXT NOT NULL,
    role_title       TEXT NOT NULL,
    department       TEXT NOT NULL,
    clearance_level  INT  NOT NULL CHECK (clearance_level BETWEEN 1 AND 4),
    token_hash       TEXT NOT NULL UNIQUE,
    invited_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    expires_at       TIMESTAMPTZ NOT NULL,
    accepted_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_invitations_org_email ON invitations (org_id, email);

CREATE TABLE IF NOT EXISTS usage_monthly (
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    period_ym    TEXT NOT NULL,
    query_count  INT  NOT NULL DEFAULT 0,
    tokens_used  INT  NOT NULL DEFAULT 0,
    PRIMARY KEY (org_id, period_ym)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO enclave_app;

ALTER TABLE invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE invitations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS invitations_tenant_isolation ON invitations;
CREATE POLICY invitations_tenant_isolation ON invitations
    FOR ALL
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid);

ALTER TABLE usage_monthly ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_monthly FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS usage_monthly_tenant_isolation ON usage_monthly;
CREATE POLICY usage_monthly_tenant_isolation ON usage_monthly
    FOR ALL
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid);

-- Controlled SECURITY DEFINER lookup so unauthenticated invitees can validate/accept
-- an invitation token without exposing the invitations table across tenants.
CREATE OR REPLACE FUNCTION resolve_pending_invitation(p_token_hash TEXT)
RETURNS TABLE (
    id UUID,
    org_id UUID,
    org_name TEXT,
    email TEXT,
    role_title TEXT,
    department TEXT,
    clearance_level INT,
    expires_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT i.id, i.org_id, o.name, i.email, i.role_title, i.department,
           i.clearance_level, i.expires_at, i.accepted_at
    FROM invitations i
    JOIN organizations o ON o.id = i.org_id
    WHERE i.token_hash = p_token_hash
    LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION mark_invitation_accepted(p_invitation_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE invitations
    SET accepted_at = now()
    WHERE id = p_invitation_id
      AND accepted_at IS NULL
      AND expires_at > now()
    RETURNING true;
$$;

REVOKE ALL ON FUNCTION resolve_pending_invitation(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_invitation_accepted(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION resolve_pending_invitation(TEXT) TO enclave_app;
GRANT EXECUTE ON FUNCTION mark_invitation_accepted(UUID) TO enclave_app;
