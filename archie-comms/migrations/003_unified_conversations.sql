-- Unified Conversations — one conversation thread, any channel
-- Replaces separate chat_messages + telegram_message_log for A.R.C.H.I.E. conversations
CREATE TABLE IF NOT EXISTS unified_conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    topic VARCHAR(500),
    status VARCHAR(20) DEFAULT 'active',  -- active, archived
    created_at TIMESTAMP DEFAULT NOW(),
    last_activity TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_unified_conv_user ON unified_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_unified_conv_active ON unified_conversations(status) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS unified_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES unified_conversations(id) ON DELETE CASCADE,
    channel VARCHAR(20) NOT NULL,       -- platform, telegram, claude, cli
    direction VARCHAR(10) NOT NULL,     -- inbound, outbound
    sender VARCHAR(100) NOT NULL,       -- kytran, archie, agent_name, claude
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',        -- source_agent, department, project_id, task_id, model, latency_ms
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_unified_msg_conv ON unified_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_unified_msg_channel ON unified_messages(channel);
CREATE INDEX IF NOT EXISTS idx_unified_msg_created ON unified_messages(created_at);
