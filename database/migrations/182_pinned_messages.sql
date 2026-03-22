-- Migration 182: Pinned Messages for Chat
-- Allows users to pin important AI chat messages for later reference

CREATE TABLE IF NOT EXISTS pinned_messages (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES ai_conversations(id) ON DELETE SET NULL,
    message_content TEXT NOT NULL,
    message_type VARCHAR(20) DEFAULT 'assistant',
    note TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pinned_messages_user ON pinned_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_pinned_messages_created ON pinned_messages(user_id, created_at DESC);
