-- database/migrations/add_chat_tables.sql
-- ARCHIE Chat tables (Project #178)
-- Idempotent: safe to re-run

-- Conversations
CREATE TABLE IF NOT EXISTS chat_conversations (
    id SERIAL PRIMARY KEY,
    conversation_uuid UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    team_id INTEGER,
    title VARCHAR(255),
    agent_target VARCHAR(100),
    is_archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_conversations_user ON chat_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_team ON chat_conversations(team_id) WHERE team_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_chat_conversations_updated ON chat_conversations(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_uuid ON chat_conversations(conversation_uuid);

-- Messages
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES chat_conversations(id),
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    thinking_steps JSONB,
    agent_used VARCHAR(100),
    model_used VARCHAR(100),
    station_code VARCHAR(20),
    governance_events JSONB,
    duration_ms INTEGER,
    token_count INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation ON chat_messages(conversation_id, created_at);

-- API Keys
CREATE TABLE IF NOT EXISTS chat_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    key_hash VARCHAR(64) NOT NULL,
    key_prefix VARCHAR(8) NOT NULL,
    name VARCHAR(100) NOT NULL,
    scopes JSONB DEFAULT '["chat"]'::jsonb,
    rate_limit INTEGER DEFAULT 30,
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_api_keys_hash ON chat_api_keys(key_hash) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_chat_api_keys_user ON chat_api_keys(user_id);
