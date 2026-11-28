-- EnclaveRAG Phase UX-1: Private Multi-Turn Conversations & Document Versioning

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS storage_key TEXT;

ALTER TABLE ingestion_jobs
    ADD COLUMN IF NOT EXISTS replace_existing BOOLEAN NOT NULL DEFAULT true;

CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_org_user
    ON conversations (org_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    citations_json   JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conv_created
    ON messages (conversation_id, created_at ASC);

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO enclave_app;

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS conversations_user_isolation ON conversations;
CREATE POLICY conversations_user_isolation ON conversations
    FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
    );

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS messages_user_isolation ON messages;
CREATE POLICY messages_user_isolation ON messages
    FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
    );
