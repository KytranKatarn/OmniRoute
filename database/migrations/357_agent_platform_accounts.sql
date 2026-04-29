-- database/migrations/357_agent_platform_accounts.sql
-- Agent Social Identity — credential vault for per-agent platform accounts.
-- Supports both AI agent accounts (agent_id) and human accounts managed by agents (user_id).

CREATE TABLE IF NOT EXISTS agent_platform_accounts (
    id                  SERIAL PRIMARY KEY,
    agent_id            INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    user_id             INTEGER REFERENCES users(id) ON DELETE CASCADE,
    platform            VARCHAR(50) NOT NULL,
    username            VARCHAR(255),
    email               VARCHAR(255) NOT NULL,
    encrypted_password  TEXT,
    session_cookie_path TEXT,
    managed_by_agent_id INTEGER REFERENCES agents(id),
    account_type        VARCHAR(50) NOT NULL DEFAULT 'personal',
    platform_user_id    VARCHAR(255),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT owner_required CHECK (agent_id IS NOT NULL OR user_id IS NOT NULL),
    UNIQUE (agent_id, platform),
    UNIQUE (user_id, platform)
);

CREATE INDEX idx_apa_agent_platform ON agent_platform_accounts (agent_id, platform);
CREATE INDEX idx_apa_managed_by ON agent_platform_accounts (managed_by_agent_id) WHERE managed_by_agent_id IS NOT NULL;

COMMENT ON TABLE agent_platform_accounts IS
    'Per-agent/user platform credentials. agent_id for AI agents, user_id for human accounts managed by agents.';
COMMENT ON COLUMN agent_platform_accounts.managed_by_agent_id IS
    'Which agent manages this account. NULL = self-managed. agent_id=2 (ARCHIE) manages user_id=2 (Kytran).';
COMMENT ON COLUMN agent_platform_accounts.encrypted_password IS
    'Fernet-encrypted password. Key = CREDENTIAL_VAULT_KEY env var.';
